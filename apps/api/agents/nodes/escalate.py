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
from apps.api.agents.nodes._reply import finalize_agent_reply
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    get_open_escalation_for_conversation,
    insert_escalation,
    insert_message,
    update_conversation_last_message,
    update_conversation_status,
)
from apps.api.services.approval_reply import (
    done_followup_message,
    gate_message,
    waiting_message,
)


def make_escalate_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    tracker = deps.reasoning_tracker

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

        # Si la escalación es por pending_approval, construir un mensaje cálido y
        # contextual por skill si el agente no generó uno propio:
        #  - primera vez → gate ("lo paso a mi equipo");
        #  - re-disparo con la acción aún pendiente → "sigue en revisión";
        #  - re-disparo con la acción ya aprobada/aplicada → "ya quedó aplicado"
        #    (NO "sigue en revisión", que contradiría el cambio ya confirmado).
        pending_approval_id = state.get("pending_approval_id")
        if pending_approval_id and not state.get("agent_response"):
            skill_slug = state.get("pending_approval_skill_slug")
            if state.get("pending_approval_is_repeat"):
                if state.get("pending_approval_reused_status") == "approved":
                    agent_response = done_followup_message(skill_slug)
                else:
                    agent_response = waiting_message(skill_slug)
            else:
                agent_response = gate_message(skill_slug)
        else:
            agent_response = state.get("agent_response") or ""
        agent_response, surface = finalize_agent_reply(state, agent_response)

        metadata: dict = {
            "confidence": state.get("confidence"),
            "langfuse_trace_id": state.get("langfuse_trace_id"),
            "model_used": state.get("model_used"),
        }
        if state.get("pending_approval_id"):
            metadata["pending_approval_id"] = state["pending_approval_id"]

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

            result: dict = {
                "escalation_id": str(esc.id),
                "decision": "escalate",
                # Solo al crear: el caller empuja la nota + asignación al helpdesk
                # una única vez (no en cada re-escalado de la misma conversación).
                "escalation_created": existing is None,
            }

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
                        "writing_surface": surface,
                    },
                )
                await update_conversation_last_message(conn, tenant_id, conversation_id)
                result["output_message_id"] = str(msg.id)
                # Exponer el mensaje en el outcome para que el webhook lo entregue
                # al helpdesk (antes en escalate quedaba sin enviar al cliente).
                result["agent_response"] = agent_response

        tracker.emit(
            tenant_id=state["tenant_id"],
            conversation_id=state["conversation_id"],
            phase="response",
            event_type="choice",
            label="Escalated to human",
            detail={"reason": reason, "escalation_id": result.get("escalation_id")},
            status="done",
        )

        return result

    return _node
