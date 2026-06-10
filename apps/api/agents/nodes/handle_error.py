"""Nodo: handle_error — fail-safe.

Si cualquier nodo previo seteó `error`, este nodo registra el problema como
una escalación a humano y deja la conversación en `escalated`. NUNCA intenta
responder al cliente.

No usa el decorador `@guarded` — si falla la persistencia, queremos que la
excepción se propague para visibilidad (y de todas formas el grafo va a `END`).
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

logger = logging.getLogger(__name__)


def make_handle_error_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
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

        metadata = {
            "error": error_msg,
            "langfuse_trace_id": state.get("langfuse_trace_id"),
            "model_used": state.get("model_used"),
        }

        try:
            async with tenant_scope(tenant_id) as conn:
                existing = await get_open_escalation_for_conversation(
                    conn, tenant_id, conversation_id
                )
                if existing is None:
                    esc = await insert_escalation(
                        conn,
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        reason=f"agent_error: {error_msg}",
                        triggered_by_message_id=inbound_id,
                        metadata=metadata,
                    )
                    await update_conversation_status(
                        conn, tenant_id, conversation_id, "escalated"
                    )
                else:
                    esc = existing
            return {
                "escalation_id": str(esc.id),
                # Solo al crear: el caller empuja la nota interna + asignación al
                # helpdesk del cliente una única vez (igual que escalate). Sin esta
                # señal, los errores de sistema no llegaban al equipo CX del cliente.
                "escalation_created": existing is None,
                # La nota interna del helpdesk usa outcome.escalation_reason; sin
                # esto llegaría como "unspecified_escalation".
                "escalation_reason": f"agent_error: {error_msg}",
            }
        except Exception:
            # No tenemos otra capa donde caer. Log y seguir — el trace ya quedó.
            logger.exception(
                "handle_error_persistence_failed",
                extra={
                    "tenant_id": tenant_id_str,
                    "conversation_id": conversation_id_str,
                    "original_error": error_msg,
                },
            )
            return {}

    return _node
