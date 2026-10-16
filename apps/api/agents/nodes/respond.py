"""Nodo: respond.

Persiste el mensaje outbound del agente y actualiza `conversations.last_message_at`.
NO envía la respuesta al canal ni marca la resolución: solo decide si la respuesta
resuelve (`resolves_on_delivery`). El caller post-grafo entrega la respuesta y, solo
si llegó, marca `resolved` + billing + cierre (`services.agent_resolution`).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.nodes._reply import EMPTY_REPLY, finalize_agent_reply
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import insert_message, update_conversation_last_message

logger = logging.getLogger(__name__)


def make_respond_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    tracker = deps.reasoning_tracker

    @guarded(name="respond")
    async def _node(state: AgentState) -> dict:
        tenant_id = UUID(state["tenant_id"])
        conversation_id = UUID(state["conversation_id"])
        content, surface = finalize_agent_reply(state, state.get("agent_response") or "")

        if not content.strip():
            # El normalizador puede vaciar un texto válido (p. ej. solo emojis): nunca se
            # entrega en blanco. El grafo sigue a `escalate` con esta razón.
            logger.error(
                EMPTY_REPLY,
                extra={
                    "tenant_id": state["tenant_id"],
                    "conversation_id": state["conversation_id"],
                    "raw_chars": len(state.get("agent_response") or ""),
                },
            )
            return {
                "decision": "escalate",
                "escalation_reason": EMPTY_REPLY,
                "agent_response": None,
            }

        metadata = {
            # Enlaza la respuesta con el inbound que la originó: el worker lo usa para
            # no responder dos veces si reintenta un turno que ya había respondido.
            "inbound_message_id": state.get("inbound_message_id"),
            "langfuse_trace_id": state.get("langfuse_trace_id"),
            "model": state.get("model_used"),
            "prompt_tokens": state.get("tokens_in", 0),
            "cache_write_tokens": state.get("tokens_cache_write", 0),
            "cache_read_tokens": state.get("tokens_cache_read", 0),
            "completion_tokens": state.get("tokens_out", 0),
            "cost_usd": state.get("cost_usd", 0.0),
            "confidence": state.get("confidence"),
            "writing_surface": surface,
        }

        # El agente resuelve salvo que su respuesta pida más datos al cliente
        # (pregunta de clarificación). La resolución se materializa fuera del grafo,
        # solo tras confirmar que la respuesta llegó al cliente.
        resolves = not state.get("awaiting_customer_reply", False)

        async with tenant_scope(tenant_id) as conn:
            msg = await insert_message(
                conn,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role="agent_ai",
                direction="outbound",
                content=content,
                metadata=metadata,
            )
            await update_conversation_last_message(conn, tenant_id, conversation_id)

        tracker.emit(
            tenant_id=state["tenant_id"],
            conversation_id=state["conversation_id"],
            phase="response",
            event_type="choice",
            label="Agent responded",
            detail={"message_id": str(msg.id), "resolves_on_delivery": resolves},
            status="done",
        )

        # `agent_response` vuelve normalizado: es el texto que el caller entrega.
        return {
            "output_message_id": str(msg.id),
            "resolves_on_delivery": resolves,
            "agent_response": content,
        }

    return _node
