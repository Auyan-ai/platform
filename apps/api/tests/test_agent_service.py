"""Tests del orquestador `AgentService`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.agents.service import AgentOutcome, AgentService
from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    INBOUND_MSG_ID,
    OUTBOUND_MSG_ID,
    TENANT_ID,
)


def _fake_langfuse(trace_id: str = "trace-abc") -> MagicMock:
    lf = MagicMock()
    lf.start_conversation_trace.return_value = MagicMock(id=trace_id)
    lf.trace_id.return_value = trace_id
    lf.finalize_trace = MagicMock()
    return lf


def _kwargs() -> dict:
    return {
        "tenant_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "inbound_message_id": INBOUND_MSG_ID,
        "inbound_message_content": "¿envíos a Argentina?",
        "channel": "chat",
        "end_customer_id": CUSTOMER_ID,
    }


class TestProcessInbound:
    @pytest.mark.asyncio
    async def test_respond_outcome(self) -> None:
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(
            return_value={
                "decision": "respond",
                "agent_response": "3-5 días.",
                "confidence": 0.92,
                "tokens_in": 120,
                "tokens_out": 35,
                "cost_usd": 0.0008,
                "model_used": "claude-sonnet-4-6",
                "output_message_id": str(OUTBOUND_MSG_ID),
            }
        )
        lf = _fake_langfuse()
        service = AgentService(graph=graph, langfuse=lf)

        outcome = await service.process_inbound(**_kwargs())

        assert isinstance(outcome, AgentOutcome)
        assert outcome.decision == "respond"
        assert outcome.response_text == "3-5 días."
        assert outcome.output_message_id == str(OUTBOUND_MSG_ID)
        assert outcome.error is None
        assert outcome.trace_id == "trace-abc"
        lf.start_conversation_trace.assert_called_once()
        lf.finalize_trace.assert_called_once()

    @pytest.mark.asyncio
    async def test_escalate_outcome(self) -> None:
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(
            return_value={
                "decision": "escalate",
                "escalation_reason": "out_of_scope",
                "confidence": 0.30,
                "escalation_id": "esc-1",
                "model_used": "claude-sonnet-4-6",
                "tokens_in": 80,
                "tokens_out": 5,
                "cost_usd": 0.0003,
            }
        )
        service = AgentService(graph=graph, langfuse=_fake_langfuse())

        outcome = await service.process_inbound(**_kwargs())

        assert outcome.decision == "escalate"
        assert outcome.escalation_reason == "out_of_scope"
        assert outcome.response_text is None
        assert outcome.escalation_id == "esc-1"

    @pytest.mark.asyncio
    async def test_final_state_with_error_maps_to_decision_error(self) -> None:
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(
            return_value={
                "error": "load_tenant_context: tenant_not_found",
                "escalation_id": "esc-fallback",
            }
        )
        service = AgentService(graph=graph, langfuse=_fake_langfuse())

        outcome = await service.process_inbound(**_kwargs())

        assert outcome.decision == "error"
        assert outcome.error == "load_tenant_context: tenant_not_found"
        assert outcome.escalation_id == "esc-fallback"

    @pytest.mark.asyncio
    async def test_unhandled_graph_exception_yields_error_outcome(self) -> None:
        """Si el grafo lanza (no debería, los nodos están guarded), igual recuperamos."""
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(side_effect=RuntimeError("graph_internal_error"))
        lf = _fake_langfuse()
        service = AgentService(graph=graph, langfuse=lf)

        outcome = await service.process_inbound(**_kwargs())

        assert outcome.decision == "error"
        assert outcome.error is not None
        assert "graph_internal_error" in outcome.error
        # finalize_trace siempre se llama, incluso ante excepción
        lf.finalize_trace.assert_called_once()

    @pytest.mark.asyncio
    async def test_initial_state_carries_all_ids(self) -> None:
        """Verifica que el state inicial pasado al grafo tiene los IDs correctos."""
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(return_value={"decision": "respond", "agent_response": "x"})
        service = AgentService(graph=graph, langfuse=_fake_langfuse())

        await service.process_inbound(**_kwargs())

        initial = graph.ainvoke.await_args.args[0]
        assert initial["tenant_id"] == str(TENANT_ID)
        assert initial["conversation_id"] == str(CONVERSATION_ID)
        assert initial["inbound_message_id"] == str(INBOUND_MSG_ID)
        assert initial["end_customer_id"] == str(CUSTOMER_ID)
        assert initial["channel"] == "chat"
        assert initial["langfuse_trace_id"] == "trace-abc"

    @pytest.mark.asyncio
    async def test_finalize_passes_error_level_when_error_present(self) -> None:
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(
            return_value={"error": "boom", "decision": None}
        )
        lf = _fake_langfuse()
        service = AgentService(graph=graph, langfuse=lf)

        await service.process_inbound(**_kwargs())

        # El kwarg `error` debe llegar a finalize_trace
        kwargs = lf.finalize_trace.call_args.kwargs
        assert kwargs["error"] == "boom"

    @pytest.mark.asyncio
    async def test_langfuse_disabled_still_works(self) -> None:
        """Si Langfuse no está configurado, start_trace devuelve None — todo sigue funcionando."""
        lf = MagicMock()
        lf.start_conversation_trace.return_value = None
        lf.trace_id.return_value = None
        lf.finalize_trace = MagicMock()
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(
            return_value={"decision": "respond", "agent_response": "ok"}
        )
        service = AgentService(graph=graph, langfuse=lf)

        outcome = await service.process_inbound(**_kwargs())

        assert outcome.decision == "respond"
        assert outcome.trace_id is None
