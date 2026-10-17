"""Nodo: handle_error — fail-safe.

Si cualquier nodo previo seteó `error`, este nodo registra el problema como
una escalación a humano y deja la conversación en `escalated`. NUNCA intenta
responder al cliente.

No va bajo `guarded`: si falla la persistencia, la excepción se propaga y
`AgentService` la re-lanza tras su último intento, para que el turno se
reintente (worker) o falle con 500 (webhook de chat) en vez de cerrarse sin
escalación.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    get_open_escalation_for_conversation,
    insert_escalation,
    update_conversation_status,
)
from apps.api.integrations.anthropic_client import PROVIDER_UNAVAILABLE_CATEGORY

logger = logging.getLogger(__name__)


def make_handle_error_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    tracker = deps.reasoning_tracker

    async def _node(state: AgentState) -> dict:
        tenant_id_str = state.get("tenant_id")
        conversation_id_str = state.get("conversation_id")
        error_msg = state.get("error") or "unknown_error"

        # Sin tenant/conversation no podemos persistir — sólo loguear.
        # Esto sólo puede ocurrir si el state inicial fue mal construido.
        if not tenant_id_str or not conversation_id_str:
            logger.error(
                "handle_error sin tenant/conversation context: error=%s state_keys=%s",
                error_msg,
                list(state.keys()),
            )
            return {}

        tenant_id = UUID(tenant_id_str)
        conversation_id = UUID(conversation_id_str)
        inbound_id = (
            UUID(state["inbound_message_id"])
            if state.get("inbound_message_id")
            else None
        )

        # Caída del proveedor LLM: razón propia (no "agent_error: …") para que el equipo CX
        # del cliente y el dashboard la distingan de un fallo puntual.
        reason = (
            error_msg
            if error_msg.startswith(PROVIDER_UNAVAILABLE_CATEGORY)
            else f"agent_error: {error_msg}"
        )

        metadata = {
            "error": error_msg,
            "langfuse_trace_id": state.get("langfuse_trace_id"),
            "model_used": state.get("model_used"),
        }

        async with tenant_scope(tenant_id) as conn:
            existing = await get_open_escalation_for_conversation(
                conn, tenant_id, conversation_id
            )
            if existing is None:
                esc = await insert_escalation(
                    conn,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    reason=reason,
                    triggered_by_message_id=inbound_id,
                    metadata=metadata,
                )
                await update_conversation_status(
                    conn, tenant_id, conversation_id, "escalated"
                )
            else:
                esc = existing
        # Cierra la línea de razonamiento del dashboard: sin esto el turno fallido
        # terminaba en el último paso que sí corrió, sin decir que escaló ni por qué.
        tracker.emit(
            tenant_id=tenant_id_str,
            conversation_id=conversation_id_str,
            phase="response",
            event_type="choice",
            label="Escalated to human",
            detail={"reason": reason, "escalation_id": str(esc.id)},
            status="error",
        )
        return {
            "escalation_id": str(esc.id),
            # Solo al crear: el caller empuja la nota interna + asignación al
            # helpdesk del cliente una única vez (igual que escalate). Sin esta
            # señal, los errores de sistema no llegaban al equipo CX del cliente.
            "escalation_created": existing is None,
            # La nota interna del helpdesk usa outcome.escalation_reason; sin
            # esto llegaría como "unspecified_escalation".
            "escalation_reason": reason,
        }

    return _node
