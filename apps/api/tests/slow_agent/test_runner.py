"""Tests del runner del slow agent — mockean DB y Anthropic."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.db.models import Conversation, SlowAgentRun
from apps.api.slow_agent.judge import OPUS_JUDGE_MODEL, SONNET_JUDGE_MODEL
from apps.api.slow_agent.runner import RunStats, _estimate_cost

TENANT = uuid.uuid4()
RUN_ID = uuid.uuid4()
NOW = datetime(2026, 5, 19, 12, 0, 0)


# ─── _estimate_cost ───────────────────────────────────────────────────────────


def test_estimate_cost_zero():
    assert _estimate_cost(0, 0, 0, 0) == 0.0


def test_estimate_cost_sonnet_only():
    # 1M input Sonnet = $3, 1M output = $15
    cost = _estimate_cost(1_000_000, 0, 0, 0)
    assert abs(cost - 3.0) < 0.001


def test_estimate_cost_opus_only():
    # 1M input Opus = $15
    cost = _estimate_cost(0, 0, 1_000_000, 0)
    assert abs(cost - 15.0) < 0.001


def test_estimate_cost_mixed():
    # 500k Sonnet input + 500k Opus output
    cost = _estimate_cost(500_000, 0, 0, 500_000)
    expected = 500_000 * 3.0 / 1_000_000 + 500_000 * 75.0 / 1_000_000
    assert abs(cost - expected) < 0.001


# ─── RunStats ─────────────────────────────────────────────────────────────────


def test_run_stats_defaults():
    stats = RunStats()
    assert stats.conversations_evaluated == 0
    assert stats.proposals_generated == 0
    assert stats.sonnet_tokens == 0
    assert stats.opus_tokens == 0
    assert stats.cost_usd == 0.0
    assert stats.errors == []


def test_run_stats_token_accumulation():
    stats = RunStats(
        sonnet_input_tokens=1000,
        sonnet_output_tokens=500,
        opus_input_tokens=200,
        opus_output_tokens=100,
    )
    assert stats.sonnet_tokens == 1500
    assert stats.opus_tokens == 300


# ─── run_slow_agent_for_tenant (integración con mocks) ───────────────────────


def _fake_conv(status: str = "escalated") -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        end_customer_id=uuid.uuid4(),
        channel="chat",
        status=status,  # type: ignore[arg-type]
        created_at=datetime.now(UTC),
    )


def _fake_run() -> SlowAgentRun:
    return SlowAgentRun(
        id=RUN_ID,
        tenant_id=TENANT,
        status="running",
        conversations_evaluated=0,
        proposals_generated=0,
        sonnet_tokens=0,
        opus_tokens=0,
        run_started_at=NOW,
        created_at=NOW,
    )


def _mock_anthropic_no_proposal() -> MagicMock:
    content = MagicMock()
    content.text = json.dumps({"should_propose": False, "confidence": 0.9})
    usage = MagicMock()
    usage.input_tokens = 300
    usage.output_tokens = 50
    msg = MagicMock()
    msg.content = [content]
    msg.usage = usage
    anthropic = MagicMock()
    anthropic.messages.create = AsyncMock(return_value=msg)
    return anthropic


@pytest.mark.asyncio
async def test_run_slow_agent_no_candidates(monkeypatch):
    """Si no hay conversaciones recientes, el run termina con 0 evaluadas."""
    from apps.api.slow_agent import runner

    fake_run = _fake_run()
    conn = AsyncMock()

    def fake_tenant_scope(tid):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _scope(t=None):
            yield conn

        return _scope(tid)

    monkeypatch.setattr("apps.api.slow_agent.runner.tenant_scope", fake_tenant_scope)
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.insert_slow_agent_run",
        AsyncMock(return_value=fake_run),
    )
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.list_judged_conversation_ids",
        AsyncMock(return_value=set()),
    )
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.list_conversations",
        AsyncMock(return_value=[]),  # sin conversaciones
    )
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.get_tenant_pii_salt",
        AsyncMock(return_value="salt"),
    )
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.get_tenant_configuration",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.update_slow_agent_run",
        AsyncMock(),
    )

    anthropic = _mock_anthropic_no_proposal()
    stats = await runner.run_slow_agent_for_tenant(
        anthropic=anthropic,
        tenant_id=TENANT,
        since_days=7,
        max_conversations=50,
    )

    assert stats.conversations_evaluated == 0
    assert stats.proposals_generated == 0


@pytest.mark.asyncio
async def test_run_slow_agent_respects_max_conversations(monkeypatch):
    """No evalúa más de max_conversations aunque haya más candidatos."""
    from apps.api.slow_agent import runner

    fake_run = _fake_run()
    convs = [_fake_conv("escalated") for _ in range(20)]
    conn = AsyncMock()

    def fake_tenant_scope(tid):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _scope(t=None):
            yield conn

        return _scope(tid)

    judged_calls = []

    async def fake_judge_one(**kwargs):
        judged_calls.append(kwargs["conv"].id)
        kwargs["stats"].conversations_evaluated += 1

    monkeypatch.setattr("apps.api.slow_agent.runner.tenant_scope", fake_tenant_scope)
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.insert_slow_agent_run",
        AsyncMock(return_value=fake_run),
    )
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.list_judged_conversation_ids",
        AsyncMock(return_value=set()),
    )
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.list_conversations",
        AsyncMock(return_value=convs),
    )
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.get_tenant_pii_salt",
        AsyncMock(return_value="salt"),
    )
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.get_tenant_configuration",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        "apps.api.slow_agent.runner.update_slow_agent_run",
        AsyncMock(),
    )
    monkeypatch.setattr("apps.api.slow_agent.runner._judge_one", fake_judge_one)

    anthropic = _mock_anthropic_no_proposal()
    stats = await runner.run_slow_agent_for_tenant(
        anthropic=anthropic,
        tenant_id=TENANT,
        since_days=7,
        max_conversations=5,
    )

    assert stats.conversations_evaluated == 5
    assert len(judged_calls) == 5


@pytest.mark.asyncio
async def test_run_cost_counts_sonnet_and_opus_calls_at_current_rates(monkeypatch):
    """Sonnet duda y escala a Opus: el run cobra las dos llamadas con la tarifa vigente."""
    from apps.api.slow_agent import runner

    responses = {
        SONNET_JUDGE_MODEL: (
            {"should_propose": False, "confidence": 0.5},
            SimpleNamespace(input_tokens=4000, output_tokens=300),
        ),
        OPUS_JUDGE_MODEL: (
            {"should_propose": False, "confidence": 0.9},
            SimpleNamespace(input_tokens=4000, output_tokens=500),
        ),
    }

    async def create(**kwargs):
        payload, usage = responses[kwargs["model"]]
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))], usage=usage)

    anthropic = MagicMock()
    anthropic.messages.create = AsyncMock(side_effect=create)

    @asynccontextmanager
    async def fake_scope(_tenant_id):
        yield AsyncMock()

    update_run = AsyncMock()
    for name, value in {
        "tenant_scope": fake_scope,
        "insert_slow_agent_run": AsyncMock(return_value=_fake_run()),
        "list_judged_conversation_ids": AsyncMock(return_value=set()),
        "list_conversations": AsyncMock(return_value=[_fake_conv("escalated")]),
        "get_tenant_pii_salt": AsyncMock(return_value="salt"),
        "get_tenant_configuration": AsyncMock(return_value=MagicMock()),
        "get_messages_for_conversation": AsyncMock(return_value=[]),
        "list_skill_audit_log": AsyncMock(return_value=[]),
        "get_last_intent_for_conversation": AsyncMock(return_value=None),
        "get_open_escalation_for_conversation": AsyncMock(return_value=None),
        "insert_conversation_judgment": AsyncMock(),
        "update_slow_agent_run": update_run,
    }.items():
        monkeypatch.setattr(runner, name, value)

    await runner.run_slow_agent_for_tenant(anthropic=anthropic, tenant_id=TENANT)

    # Sonnet: 4000*$3 + 300*$15 = $0.0165. Opus 4.7: 4000*$5 + 500*$25 = $0.0325.
    kwargs = update_run.call_args.kwargs
    assert kwargs["cost_usd"] == pytest.approx(0.049)
    assert kwargs["sonnet_tokens"] == 4300
    assert kwargs["opus_tokens"] == 4500
