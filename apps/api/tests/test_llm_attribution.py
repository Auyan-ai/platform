"""Atribución de coste y tokens por rol del ModelRegistry (#378, #379)."""

from __future__ import annotations

import ast
import warnings
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.agents.service import AgentService
from apps.api.core.config import ModelRegistry
from apps.api.integrations.anthropic_client import create_message
from apps.api.integrations.langsmith_client import LangSmithClient
from apps.api.integrations.llm_ledger import MODEL_ROLES, ModelRole, open_ledger
from apps.api.integrations.pricing import LLMUsage, compute_llm_cost

from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    INBOUND_MSG_ID,
    TENANT_ID,
)

API_ROOT = Path(__file__).resolve().parents[1]
HAIKU = "claude-haiku-4-5-20251001"


def _response(
    *, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0
) -> SimpleNamespace:
    return SimpleNamespace(
        content=[],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


def _client(*responses: SimpleNamespace) -> MagicMock:
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=list(responses))
    return client


async def _call(client: Any, model: str, role: ModelRole) -> None:
    await create_message(
        client, {"model": model, "max_tokens": 10}, role=role, attempts=1, timeout_seconds=5
    )


class TestRoles:
    def test_every_registry_role_is_a_model_role(self) -> None:
        """Un rol nuevo en el registro obliga a declararlo en `ModelRole` (y viceversa)."""
        assert set(get_args(ModelRole)) == set(ModelRegistry().by_role())
        assert set(get_args(ModelRole)) == MODEL_ROLES

    @pytest.mark.asyncio
    async def test_create_message_cannot_be_called_without_a_role(self) -> None:
        with pytest.raises(TypeError, match="role"):
            await create_message(  # type: ignore[call-arg]
                MagicMock(), {"model": "m"}, attempts=1, timeout_seconds=5
            )

    def test_only_the_central_client_calls_the_messages_api(self) -> None:
        """Una llamada al LLM fuera de `create_message` no pasaría por el libro del turno."""
        offenders = []
        for path in API_ROOT.rglob("*.py"):
            rel = path.relative_to(API_ROOT)
            if rel.parts[0] in {".venv", "tests"}:
                continue
            if rel == Path("integrations/anthropic_client.py"):
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "create"
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr == "messages"
                ):
                    offenders.append(f"{rel}:{node.lineno}")
        assert offenders == []


class TestLedger:
    @pytest.mark.asyncio
    async def test_turn_with_classifier_reason_and_l3_supervisor_has_one_entry_per_role(
        self,
    ) -> None:
        classifier = _response(input_tokens=2000, output_tokens=150)
        reason = _response(input_tokens=400, output_tokens=100, cache_read=1000)
        supervisor = _response(input_tokens=300, output_tokens=50, cache_write=700)
        client = _client(classifier, reason, supervisor)

        with open_ledger() as ledger:
            await _call(client, HAIKU, "intent_classifier_model")
            await _call(client, "claude-sonnet-4-6", "default_agent_model")
            await _call(client, "claude-opus-4-7", "supervisor_model_l3")

        by_role = ledger.by_role()
        assert set(by_role) == {
            "intent_classifier_model",
            "default_agent_model",
            "supervisor_model_l3",
        }
        assert by_role["default_agent_model"]["model"] == "claude-sonnet-4-6"
        assert by_role["supervisor_model_l3"]["model"] == "claude-opus-4-7"
        assert by_role["default_agent_model"]["input"] == 1400
        assert by_role["default_agent_model"]["cache_read"] == 1000
        assert by_role["supervisor_model_l3"]["cache_write"] == 700
        expected = (
            compute_llm_cost(HAIKU, LLMUsage(input_tokens=2000, output_tokens=150))
            + compute_llm_cost(
                "claude-sonnet-4-6",
                LLMUsage(input_tokens=400, output_tokens=100, cache_read_tokens=1000),
            )
            + compute_llm_cost(
                "claude-opus-4-7",
                LLMUsage(input_tokens=300, output_tokens=50, cache_write_5m_tokens=700),
            )
        )
        assert ledger.cost_usd == pytest.approx(expected)
        assert sum(r["cost_usd"] for r in by_role.values()) == pytest.approx(ledger.cost_usd)
        assert ledger.telemetry()["tokens_in"] == 2000 + 1400 + 1000

    @pytest.mark.asyncio
    async def test_calls_outside_a_turn_are_not_recorded(self) -> None:
        client = _client(_response(input_tokens=1, output_tokens=1))
        await _call(client, HAIKU, "judge_sonnet_model")
        with open_ledger() as ledger:
            pass
        assert ledger.calls == []

    def test_overlay_keeps_state_totals_when_no_call_was_recorded(self) -> None:
        with open_ledger() as ledger:
            pass
        assert ledger.overlay({"cost_usd": 0.5})["cost_usd"] == 0.5


class TestAgentServiceTotals:
    @pytest.mark.asyncio
    async def test_outcome_and_trace_carry_the_cost_of_every_call(self) -> None:
        client = _client(
            _response(input_tokens=2000, output_tokens=150),
            _response(input_tokens=500, output_tokens=80),
        )

        async def invoke(state: dict) -> dict:
            await _call(client, HAIKU, "intent_classifier_model")
            await _call(client, "claude-sonnet-4-6", "default_agent_model")
            # El state solo sabe de `reason`, como antes de #378.
            return {"decision": "respond", "agent_response": "ok", "cost_usd": 0.0001}

        graph = AsyncMock()
        graph.ainvoke = invoke
        obs = MagicMock()
        obs.trace_id.return_value = "t"
        service = AgentService(graph=graph, observability=obs, handle_error=AsyncMock())

        outcome = await service.process_inbound(
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            inbound_message_id=INBOUND_MSG_ID,
            inbound_message_content="hola",
            channel="chat",
            end_customer_id=CUSTOMER_ID,
        )

        classifier = compute_llm_cost(HAIKU, LLMUsage(input_tokens=2000, output_tokens=150))
        reason = compute_llm_cost("claude-sonnet-4-6", LLMUsage(input_tokens=500, output_tokens=80))
        assert outcome.cost_usd == pytest.approx(classifier + reason)
        assert outcome.tokens_in == 2500
        kwargs = obs.finalize_trace.call_args.kwargs
        assert kwargs["cost_usd"] == pytest.approx(classifier + reason)
        assert [c.role for c in kwargs["llm_calls"]] == [
            "intent_classifier_model",
            "default_agent_model",
        ]


class TestLangSmithPerCallRuns:
    @pytest.mark.asyncio
    async def test_one_llm_run_per_call_and_their_cost_adds_up_to_the_turn(self) -> None:
        client = _client(
            _response(input_tokens=2000, output_tokens=150),
            _response(input_tokens=300, output_tokens=50),
        )
        with open_ledger() as ledger:
            await _call(client, HAIKU, "intent_classifier_model")
            await _call(client, "claude-opus-4-7", "supervisor_model_l3")

        inner = MagicMock()
        ls = LangSmithClient(inner, project_name="p")
        trace = ls.start_conversation_trace(
            tenant_id="t", conversation_id="c", end_customer_id="e", channel="chat", input_text="x"
        )
        inner.create_run.reset_mock()

        ls.finalize_trace(
            trace,
            decision="respond",
            confidence=None,
            response_text="x",
            escalation_reason=None,
            tokens_in=ledger.usage.prompt_tokens,
            tokens_cache_write=0,
            tokens_cache_read=0,
            tokens_out=ledger.usage.output_tokens,
            cost_usd=ledger.cost_usd,
            model=None,
            error=None,
            llm_calls=ledger.calls,
        )

        runs = [c.kwargs for c in inner.create_run.call_args_list]
        assert [r["name"] for r in runs] == ["intent_classifier_model", "supervisor_model_l3"]
        assert all(r["run_type"] == "llm" for r in runs)
        assert [r["extra"]["metadata"]["model"] for r in runs] == [HAIKU, "claude-opus-4-7"]
        total = sum(r["extra"]["metadata"]["usage_metadata"]["total_cost"] for r in runs)
        assert total == pytest.approx(ledger.cost_usd)


class TestTurnTelemetry:
    @pytest.mark.asyncio
    async def test_open_ledger_wins_over_partial_state_totals(self) -> None:
        from apps.api.integrations.llm_ledger import turn_telemetry

        client = _client(_response(input_tokens=100, output_tokens=10))
        state = {"cost_usd": 0.0001, "tokens_in": 1}
        assert turn_telemetry(state)["tokens_in"] == 1
        with open_ledger():
            await _call(client, HAIKU, "intent_classifier_model")
            telemetry = turn_telemetry(state)
        assert telemetry["tokens_in"] == 100
        assert list(telemetry["usage_by_role"]) == ["intent_classifier_model"]
