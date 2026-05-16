"""Nodo: escalate.

Crea fila en `escalations` con razón explícita (regla dura de CLAUDE.md) y
deja la conversación en status='escalated' para que aparezca en el inbox humano.

Si ya existe una escalación activa (pending/claimed) para la conversación, no
crea una nueva — devuelve la existente y persiste igualmente el mensaje del agente.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    get_open_escalation_for_conversation,
    insert_escalation,
    insert_message,
    update_conversation_last_message,
    update_conversation_status,
)


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
        agent_response = state.get("agent_response") or ""

        metadata = {
            "confidence": state.get("confidence"),
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

            result: dict = {"escalation_id": str(esc.id)}

            if agent_response.strip():
                msg = await insert_message(
                    conn,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    role="agent_ai",
                    direction="outbound",
                    content=agent_response,
                    metadata={
                        "langfuse_trace_id": state.get("langfuse_trace_id"),
                        "model": state.get("model_used"),
                        "prompt_tokens": state.get("tokens_in", 0),
                        "completion_tokens": state.get("tokens_out", 0),
                        "cost_usd": state.get("cost_usd", 0.0),
                        "confidence": state.get("confidence"),
                    },
                )
                await update_conversation_last_message(conn, tenant_id, conversation_id)
                result["output_message_id"] = str(msg.id)

        return result

    return _node
