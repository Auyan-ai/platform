"""Orquestador entre webhook router y el grafo.

Responsabilidades:
- Abrir/cerrar trace de observabilidad alrededor de la invocación del grafo.
- Construir el `AgentState` inicial.
- Invocar el grafo compilado (`ainvoke`).
- Mapear el final state a `AgentOutcome` para el caller.

El service NO toca DB ni canales externos — los datos ya vienen persistidos
por el router antes de llamar a `process_inbound`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.agents.state import AgentState

if TYPE_CHECKING:
    from apps.api.integrations.observability import ObservabilityClient
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentOutcome:
    """Resultado del procesamiento del agente para un mensaje inbound."""

    decision: str  # 'respond' | 'escalate' | 'error'
    response_text: str | None
    escalation_reason: str | None
    output_message_id: str | None
    escalation_id: str | None
    # True si la respuesta resuelve la conversación. El caller la entrega y, solo
    # si llegó, llama a services.agent_resolution.finalize_agent_resolution.
    resolves_on_delivery: bool
    trace_id: str | None
    confidence: float | None
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model_used: str | None
    error: str | None
    # True solo cuando se creó una escalación nueva (no al reusar una activa). El
    # caller empuja la nota interna + asignación al helpdesk solo en ese caso.
    escalation_created: bool = False


class AgentService:
    def __init__(self, *, graph: CompiledStateGraph, observability: ObservabilityClient) -> None:
        self._graph = graph
        self._observability = observability

    async def process_inbound(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        inbound_message_id: UUID,
        inbound_message_content: str,
        channel: str,
        end_customer_id: UUID,
    ) -> AgentOutcome:
        trace = self._observability.start_conversation_trace(
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            end_customer_id=str(end_customer_id),
            channel=channel,
            input_text=inbound_message_content,
        )
        trace_id = self._observability.trace_id(trace)

        primary_trace = trace.primary if trace else None
        initial_state: AgentState = {
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation_id),
            "inbound_message_id": str(inbound_message_id),
            "inbound_message_content": inbound_message_content,
            "channel": channel,
            "end_customer_id": str(end_customer_id),
            # Backward-compatible field name. Its value is the primary
            # observability trace id (LangSmith when enabled).
            "langfuse_trace_id": trace_id,
            # LangSmith node-level tracing — the wrapper in build_graph reads these.
            "_trace_run_id": str(primary_trace.run_id) if primary_trace else None,
            "_trace_dotted_order": primary_trace.dotted_order if primary_trace else None,
            # ReAct loop defaults — load_tenant_context puede overridear desde
            # tenant_config.extra. allowed_skills queda vacío hasta Sprint 7
            # (select_aop) salvo opt-in explícito del tenant.
            "tool_results": [],
            "tool_iterations": 0,
            "max_tool_iterations": 5,
            "allowed_skills": [],
        }

        try:
            final_state: AgentState = await self._graph.ainvoke(initial_state)
        except Exception as exc:
            # Esto sólo ocurre si algo se rompe en LangGraph mismo (no en nodos —
            # esos están guarded). Logueamos y devolvemos outcome de error.
            logger.exception(
                "graph_invocation_failed",
                extra={"tenant_id": str(tenant_id), "conversation_id": str(conversation_id)},
            )
            self._observability.finalize_trace(
                trace,
                decision=None,
                confidence=None,
                response_text=None,
                escalation_reason=None,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                model=None,
                error=f"unhandled_graph_exception: {exc!s}",
            )
            return AgentOutcome(
                decision="error",
                response_text=None,
                escalation_reason=None,
                output_message_id=None,
                escalation_id=None,
                resolves_on_delivery=False,
                trace_id=trace_id,
                confidence=None,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                model_used=None,
                error=f"unhandled_graph_exception: {exc!s}",
            )

        error = final_state.get("error")
        decision = "error" if error else final_state.get("decision", "error")
        # Con error, `agent_response` es un borrador que no pasó (o hizo caer) al
        # supervisor: NUNCA se entrega. handle_error ya escaló; responde el equipo.
        response_text = None if error else final_state.get("agent_response")

        self._observability.finalize_trace(
            trace,
            decision=decision,
            confidence=final_state.get("confidence"),
            response_text=response_text,
            escalation_reason=final_state.get("escalation_reason"),
            tokens_in=final_state.get("tokens_in", 0),
            tokens_out=final_state.get("tokens_out", 0),
            cost_usd=final_state.get("cost_usd", 0.0),
            model=final_state.get("model_used"),
            error=error,
        )

        return AgentOutcome(
            decision=decision,
            response_text=response_text,
            escalation_reason=final_state.get("escalation_reason"),
            output_message_id=final_state.get("output_message_id"),
            escalation_id=final_state.get("escalation_id"),
            resolves_on_delivery=(
                decision == "respond"
                and bool(final_state.get("resolves_on_delivery", False))
                and not error
            ),
            trace_id=trace_id,
            confidence=final_state.get("confidence"),
            tokens_in=final_state.get("tokens_in", 0),
            tokens_out=final_state.get("tokens_out", 0),
            cost_usd=final_state.get("cost_usd", 0.0),
            model_used=final_state.get("model_used"),
            error=error,
            escalation_created=bool(final_state.get("escalation_created", False)),
        )
