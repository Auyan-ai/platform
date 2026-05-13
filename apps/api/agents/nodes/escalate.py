"""Nodo: escalate.

Crea fila en `escalations` con razón explícita (regla dura de CLAUDE.md) y
deja la conversación en status='escalated' para que aparezca en el inbox humano.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import insert_escalation, update_conversation_status


def make_escalate_node(
    deps: AgentDependencies,  # noqa: ARG001
) -> Callable[[AgentState], Awaitable[dict]]:
    @guarded(name="escalate")
    async def _node(state: AgentState) -> dict:
        tenant_id = UUID(state["tenant_id"])
        conversation_id = UUID(state["conversation_id"])
        inbound_id = (
            UUID(state["inbound_message_id"])
            if state.get("inbound_message_id")
            else None
        )
        reason = state.get("escalation_reason") or "unspecified_escalation"

        metadata = {
            "confidence": state.get("confidence"),
            "langfuse_trace_id": state.get("langfuse_trace_id"),
            "model_used": state.get("model_used"),
        }

        async with tenant_scope(tenant_id) as conn:
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

        return {"escalation_id": str(esc.id)}

    return _node
