"""Nodo: load_conversation.

Carga la conversación, el cliente final y el historial (últimos N mensajes,
default 20). El inbound actual ya debe estar persistido por el caller — por eso
viene en el historial, no separado.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    get_approved_actions_for_conversation,
    get_conversation,
    get_end_customer,
    get_recent_messages,
    get_recent_read_outputs_for_conversation,
)


def _json_compact(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _format_known_facts(
    read_outputs: list[tuple[str, dict]],
    approved_actions: list[tuple[str, dict]],
) -> str:
    """Bloque de contexto: acciones ya hechas + datos ya recuperados (JSON compacto)."""
    sections: list[str] = []
    if approved_actions:
        lines = [
            "Acciones que YA ejecutaste y se aplicaron en esta conversación. NO "
            "vuelvas a llamar estas skills ni repitas la acción — ya están hechas. "
            "Si el cliente agradece o confirma, responde solo con cortesía:",
        ]
        lines += [f"- {slug}: {_json_compact(inputs)}" for slug, inputs in approved_actions]
        sections.append("\n".join(lines))
    if read_outputs:
        lines = [
            "Resultados de herramientas que YA obtuviste en esta conversación. Úsalos "
            "directamente y NO vuelvas a consultarlos salvo que el cliente pida un cambio:",
        ]
        lines += [f"- {slug}: {_json_compact(output)}" for slug, output in read_outputs]
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


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

            inbound_id = state.get("inbound_message_id")
            messages = await get_recent_messages(
                conn,
                tenant_id,
                conversation_id,
                limit=history_limit,
                up_to_message_id=UUID(inbound_id) if inbound_id else None,
            )
            read_outputs = await get_recent_read_outputs_for_conversation(
                conn, tenant_id, conversation_id
            )
            approved_actions = await get_approved_actions_for_conversation(
                conn, tenant_id, conversation_id
            )

        return {
            "conversation_history": [m.model_dump(mode="json") for m in messages],
            "end_customer": customer.model_dump(mode="json"),
            "known_facts": _format_known_facts(read_outputs, approved_actions),
        }

    return _node
