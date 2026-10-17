"""Conversación de pedidos sin avance → el código escala (EX-03)."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from apps.api.agents.nodes.reason import make_reason_node
from apps.api.services.conversation_progress import (
    NO_PROGRESS_AGENT_REPLIES,
    NO_PROGRESS_MESSAGE,
    no_progress_reason,
    order_found_in,
)
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry


class _In(SkillInput):
    order_id: str = ""


class _Out(SkillOutput):
    ok: bool = True


class _OrderStatus(Skill):
    slug = "test.order_status"
    description = "Estado de un pedido."
    tier: SkillTier = "L1"
    input_schema = _In
    output_schema = _Out
    default_threshold = 0.5
    identity_scope = "order"
    min_level = "guest"

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        return _Out()


class _MyOrders(_OrderStatus):
    slug = "test.my_orders"
    identity_scope = "own_orders"


class _Product(_OrderStatus):
    slug = "test.product"
    identity_scope = "public"


@pytest.fixture(autouse=True)
def _skills() -> Generator[None, None, None]:
    SkillRegistry._reset()
    for skill in (_OrderStatus, _MyOrders, _Product):
        SkillRegistry.register(skill)
    yield
    SkillRegistry._reset()


def _history(agent_replies: int) -> list[dict]:
    history: list[dict] = []
    for _ in range(agent_replies):
        history += [
            {"role": "customer", "content": "tengo un problema"},
            {"role": "agent_ai", "content": "¿Me das el número de pedido?"},
        ]
    return [*history, {"role": "customer", "content": "no sé"}]


def _reason(**overrides: object) -> str | None:
    args: dict = {
        "allowed_skills": ["test.order_status", "test.my_orders"],
        "history": _history(NO_PROGRESS_AGENT_REPLIES),
        "order_refs_given": False,
        "order_in_context": False,
    }
    args.update(overrides)
    return no_progress_reason(**args)


def test_order_conversation_without_any_order_escalates_after_the_limit() -> None:
    reason = _reason()
    assert reason is not None and reason.startswith("no_progress:")


@pytest.mark.parametrize(
    "overrides",
    [
        {"history": _history(NO_PROGRESS_AGENT_REPLIES - 1)},
        {"order_refs_given": True},
        {"order_in_context": True},
        {"allowed_skills": ["test.product"]},
    ],
)
def test_no_escalation_while_there_is_progress_or_no_order_aop(overrides: dict) -> None:
    assert _reason(**overrides) is None


def test_order_found_in_reads() -> None:
    assert order_found_in([("test.order_status", {"name": "#1234"})])
    assert order_found_in([("test.my_orders", {"total_found": 2})])
    assert not order_found_in([("test.my_orders", {"total_found": 0, "orders": []})])
    assert not order_found_in([("test.product", {"title": "Camiseta"})])
    assert order_found_in([("unknown.skill", {"verified": True})]) is False


@pytest.mark.asyncio
async def test_reason_escalates_before_calling_the_llm(fake_deps, monkeypatch) -> None:
    llm = AsyncMock()
    monkeypatch.setattr("apps.api.agents.nodes.reason.call_claude_with_tools", llm)
    state = {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "system_prompt": "Eres el agente de Acme.",
        "retrieved_chunks": [],
        "conversation_history": _history(NO_PROGRESS_AGENT_REPLIES),
        "model_used": "claude-sonnet-4-6",
        "tenant_config": {"escalation_threshold": 0.70},
        "allowed_skills": ["test.order_status"],
        "tool_permissions": {"test.order_status": {"is_enabled": True}},
        "tool_results": [],
    }

    out = await make_reason_node(fake_deps)(state)

    llm.assert_not_awaited()
    assert out["decision"] == "escalate"
    assert out["agent_response"] == NO_PROGRESS_MESSAGE
    assert out["escalation_reason"].startswith("no_progress:")
