"""Nodo: respond.

Persiste el mensaje outbound del agente y actualiza `conversations.last_message_at`.
NO envía la respuesta al canal — eso lo hace el caller post-grafo.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import insert_message, update_conversation_last_message


def make_respond_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    tracker = deps.reasoning_tracker

    @guarded(name="respond")
    async def _node(state: AgentState) -> dict:
        tenant_id = UUID(state["tenant_id"])
        conversation_id = UUID(state["conversation_id"])
        content = state.get("agent_response") or ""

        if not content.strip():
            # Defensa: reason debería haber validado esto. Si llegamos sin texto,
            # algo se rompió — escalamos via error.
            return {"error": "respond_without_text"}

        metadata = {
            "langfuse_trace_id": state.get("langfuse_trace_id"),
            "model": state.get("model_used"),
            "prompt_tokens": state.get("tokens_in", 0),
            "completion_tokens": state.get("tokens_out", 0),
            "cost_usd": state.get("cost_usd", 0.0),
            "confidence": state.get("confidence"),
        }

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
            detail={"message_id": str(msg.id)},
            status="done",
        )

        return {"output_message_id": str(msg.id)}

    return _node
