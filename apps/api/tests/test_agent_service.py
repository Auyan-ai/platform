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


def _fake_observability(trace_id: str = "trace-abc") -> MagicMock:
    obs = MagicMock()
    obs.start_conversation_trace.return_value = MagicMock(id=trace_id)
    obs.trace_id.return_value = trace_id
    obs.finalize_trace = MagicMock()
    return obs


async def _unused_handle_error(state: dict) -> dict:
    raise AssertionError("handle_error solo corre si el grafo lanza")


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
        obs = _fake_observability()
        service = AgentService(graph=graph, observability=obs, handle_error=_unused_handle_error)

        outcome = await service.process_inbound(**_kwargs())

        assert isinstance(outcome, AgentOutcome)
        assert outcome.decision == "respond"
        assert outcome.response_text == "3-5 días."
        assert outcome.output_message_id == str(OUTBOUND_MSG_ID)
        assert outcome.error is None
        assert outcome.trace_id == "trace-abc"
        obs.start_conversation_trace.assert_called_once()
        obs.finalize_trace.assert_called_once()

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
        service = AgentService(
            graph=graph, observability=_fake_observability(), handle_error=_unused_handle_error
        )

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
        service = AgentService(
            graph=graph, observability=_fake_observability(), handle_error=_unused_handle_error
        )

        outcome = await service.process_inbound(**_kwargs())

        assert outcome.decision == "error"
        assert outcome.error == "load_tenant_context: tenant_not_found"
        assert outcome.escalation_id == "esc-fallback"

    @pytest.mark.asyncio
    async def test_error_never_delivers_the_unsupervised_draft(self) -> None:
        """Si el supervisor revienta tras un `reason` con borrador, el borrador NO se
        entrega (visto en A4: llegó al cliente una propuesta de reembolso que nadie
        aprobó). handle_error solo escala; el equipo humano responde."""
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(
            return_value={
                "decision": "respond",
                "agent_response": "¿Confirmas el reembolso de 10 USD?",
                "error": "supervise: anthropic 400",
                "escalation_id": "esc-1",
                "escalation_created": True,
            }
        )
        service = AgentService(
            graph=graph, observability=_fake_observability(), handle_error=_unused_handle_error
        )

        outcome = await service.process_inbound(**_kwargs())

        assert outcome.decision == "error"
        assert outcome.response_text is None
        assert outcome.resolves_on_delivery is False

    @pytest.mark.asyncio
    async def test_unhandled_graph_exception_escalates_via_handle_error(self) -> None:
        """#362: si el grafo entero lanza, el turno escala igual con razón explícita."""
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(side_effect=RuntimeError("Recursion limit of 25 reached"))
        obs = _fake_observability()
        handle_error = AsyncMock(
            return_value={
                "escalation_id": "esc-graph",
                "escalation_created": True,
                "escalation_reason": (
                    "agent_error: unhandled_graph_exception: RuntimeError: "
                    "Recursion limit of 25 reached"
                ),
            }
        )
        service = AgentService(graph=graph, observability=obs, handle_error=handle_error)

        outcome = await service.process_inbound(**_kwargs())

        state = handle_error.await_args.args[0]
        assert state["error"] == (
            "unhandled_graph_exception: RuntimeError: Recursion limit of 25 reached"
        )
        assert state["conversation_id"] == str(CONVERSATION_ID)
        assert outcome.decision == "error"
        assert outcome.escalation_id == "esc-graph"
        assert outcome.escalated is True
        assert outcome.escalation_created is True
        assert outcome.escalation_reason == (
            "agent_error: unhandled_graph_exception: RuntimeError: Recursion limit of 25 reached"
        )
        assert obs.finalize_trace.call_args.kwargs["error"] == state["error"]

    @pytest.mark.asyncio
    async def test_graph_failure_without_escalation_reraises(self) -> None:
        """Si ni siquiera se puede escalar (DB caída), el turno no se da por cerrado: se
        re-lanza para que el worker reintente o el webhook responda 500."""
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(side_effect=RuntimeError("db down"))
        obs = _fake_observability()
        handle_error = AsyncMock(side_effect=OSError("db down"))
        service = AgentService(graph=graph, observability=obs, handle_error=handle_error)

        with pytest.raises(OSError, match="db down"):
            await service.process_inbound(**_kwargs())

        assert obs.finalize_trace.call_args.kwargs["error"] == (
            "unhandled_graph_exception: RuntimeError: db down"
        )

    @pytest.mark.asyncio
    async def test_initial_state_carries_all_ids(self) -> None:
        """Verifica que el state inicial pasado al grafo tiene los IDs correctos."""
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(return_value={"decision": "respond", "agent_response": "x"})
        service = AgentService(
            graph=graph, observability=_fake_observability(), handle_error=_unused_handle_error
        )

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
        graph.ainvoke = AsyncMock(return_value={"error": "boom", "decision": None})
        obs = _fake_observability()
        service = AgentService(graph=graph, observability=obs, handle_error=_unused_handle_error)

        await service.process_inbound(**_kwargs())

        # El kwarg `error` debe llegar a finalize_trace
        kwargs = obs.finalize_trace.call_args.kwargs
        assert kwargs["error"] == "boom"

    @pytest.mark.asyncio
    async def test_observability_disabled_still_works(self) -> None:
        """Si observabilidad no está configurada, el agente sigue funcionando."""
        obs = MagicMock()
        obs.start_conversation_trace.return_value = None
        obs.trace_id.return_value = None
        obs.finalize_trace = MagicMock()
        graph = AsyncMock()
        graph.ainvoke = AsyncMock(return_value={"decision": "respond", "agent_response": "ok"})
        service = AgentService(graph=graph, observability=obs, handle_error=_unused_handle_error)

        outcome = await service.process_inbound(**_kwargs())

        assert outcome.decision == "respond"
        assert outcome.trace_id is None


def _escalated(**overrides: object) -> AgentOutcome:
    base: dict = {
        "decision": "escalate",
        "response_text": None,
        "escalation_reason": "supervisor_rejected (structural): plazo sin respaldo",
        "output_message_id": None,
        "escalation_id": "esc-1",
        "resolves_on_delivery": False,
        "trace_id": None,
        "confidence": 0.9,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "model_used": None,
        "error": None,
    }
    return AgentOutcome(**{**base, **overrides})


class TestEscalationNote:
    def test_rejected_draft_goes_to_the_note_marked_as_rejected(self) -> None:
        outcome = _escalated(rejected_draft="Tu pedido llega mañana.")

        assert outcome.escalation_note == (
            "supervisor_rejected (structural): plazo sin respaldo\n\n"
            "Borrador rechazado por el supervisor (no se envió al cliente):\n"
            "Tu pedido llega mañana."
        )

    def test_without_rejected_draft_the_note_is_the_reason(self) -> None:
        assert _escalated(escalation_reason="out_of_scope").escalation_note == "out_of_scope"
        assert _escalated(escalation_reason=None).escalation_note == "unspecified_escalation"
