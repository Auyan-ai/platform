"""Nodo: load_conversation.

Carga la conversación, el cliente final y el historial (últimos N mensajes,
default 20). El inbound actual ya debe estar persistido por el caller — por eso
viene en el historial, no separado.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    get_conversation,
    get_end_customer,
    get_recent_messages,
)


def make_load_conversation_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    @guarded(name="load_conversation")
    async def _node(state: AgentState) -> dict:
        tenant_id = UUID(state["tenant_id"])
        conversation_id = UUID(state["conversation_id"])
        customer_id = UUID(state["end_customer_id"])
        history_limit = deps.settings.history_limit

        async with tenant_scope(tenant_id) as conn:
            conversation = await get_conversation(conn, tenant_id, conversation_id)
            if conversation is None:
                return {"error": "conversation_not_found"}

            customer = await get_end_customer(conn, tenant_id, customer_id)
            if customer is None:
                return {"error": "end_customer_not_found"}

            messages = await get_recent_messages(
                conn, tenant_id, conversation_id, limit=history_limit
            )

        return {
            "conversation_history": [m.model_dump(mode="json") for m in messages],
            "end_customer": customer.model_dump(mode="json"),
        }

    return _node
