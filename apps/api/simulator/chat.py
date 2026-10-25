"""Sesiones de "Probar agente" (ADR 0015 §5): un super_admin chatea con el grafo real de un
tenant como lo haría un cliente, sin entregar nada a ningún canal.

Cada sesión es una conversación `is_simulation` (fuera de la cola y de las métricas, #359)
más una fila de `simulation_runs` con `termination_reason='interactive'`. El gasto de cada
turno se suma a esa fila mientras sigue `running`, y las queries del tope diario (#372) la
cuentan. El grafo se invoca igual que en el simulador: `simulation_mode`, sin `AgentService`,
así que `respond` y `escalate` solo guardan el mensaje y nunca tocan el helpdesk.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from apps.api.agents.state import AgentState
from apps.api.core.errors import NotFoundError
from apps.api.db.client import tenant_scope
from apps.api.db.models import SimulationRun
from apps.api.db.queries import (
    append_interactive_turn,
    create_conversation,
    create_end_customer,
    get_simulation_run,
    insert_interactive_run,
    list_skill_audit_log,
)
from apps.api.integrations.llm_ledger import open_ledger
from apps.api.simulator.cost_guard import ensure_simulation_budget
from apps.api.simulator.runner import (
    _chat_ack,
    _finalize_trace,
    _persist_customer_message,
    _persist_escalation_ack,
    simulated_chat_reply,
)

if TYPE_CHECKING:
    from apps.api.integrations.observability import ObservabilityClient
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

INTERACTIVE = "interactive"
CHAT_AOP_SLUG = "interactive"
TURN_TIMEOUT_SECONDS = 120


class ChatTurnTimeout(Exception):
    """El grafo no terminó el turno dentro de `TURN_TIMEOUT_SECONDS`."""


@dataclass(frozen=True)
class ChatTurn:
    decision: str
    response_text: str
    escalation_reason: str | None
    skills: list[str]
    trace_id: str | None
    cost_cents: float
    error: str | None
    session_cost_cents: float


def chat_customer_email(chat_id: object) -> str:
    return f"chat-{chat_id}@simulator.auyan.internal"


def build_chat_state(
    *,
    tenant_id: UUID,
    run: SimulationRun,
    end_customer_id: UUID,
    text: str,
    turn_number: int,
    trace: Any | None,
) -> AgentState:
    """Estado inicial de un turno de chat. `commerce_mode` queda sin fijar: se deriva de
    `simulation_mode`, como en el simulador. La identidad es `chat`: solo cuenta lo que teclea."""
    assert run.conversation_id is not None
    return {
        "tenant_id": str(tenant_id),
        "conversation_id": str(run.conversation_id),
        "end_customer_id": str(end_customer_id),
        "inbound_message_content": text,
        "channel": "chat",
        "simulation_mode": True,
        "simulation_fixtures": {},
        "simulation_identity": "chat",
        "langfuse_trace_id": f"chat-{run.id}-t{turn_number}",
        "_trace_run_id": str(trace.run_id) if trace else None,
        "_trace_dotted_order": trace.dotted_order if trace else None,
        "tool_results": [],
        "tool_iterations": 0,
        "max_tool_iterations": 5,
        "allowed_skills": [],
    }


async def create_chat(tenant_id: UUID, *, triggered_by: UUID | None) -> SimulationRun:
    chat_id = uuid4()
    async with tenant_scope(tenant_id) as conn:
        customer = await create_end_customer(
            conn,
            tenant_id=tenant_id,
            email=chat_customer_email(chat_id),
            full_name="[SIM] Probar agente",
            metadata={"simulation": True, "interactive": True},
        )
        conversation = await create_conversation(
            conn,
            tenant_id=tenant_id,
            end_customer_id=customer.id,
            channel="chat",
            subject="[SIM] Probar agente",
            is_simulation=True,
        )
        return await insert_interactive_run(
            conn,
            tenant_id=tenant_id,
            aop_slug=CHAT_AOP_SLUG,
            conversation_id=conversation.id,
            triggered_by=triggered_by,
        )


async def get_chat(tenant_id: UUID, chat_id: UUID) -> SimulationRun:
    async with tenant_scope(tenant_id) as conn:
        run = await get_simulation_run(conn, tenant_id, chat_id)
    if run is None or run.termination_reason != INTERACTIVE:
        raise NotFoundError("chat_not_found", code="chat_not_found")
    return run


async def _end_customer_id(tenant_id: UUID, conversation_id: UUID) -> UUID:
    async with tenant_scope(tenant_id) as conn:
        value = await conn.fetchval(
            "SELECT end_customer_id FROM conversations WHERE tenant_id = $1 AND id = $2",
            tenant_id,
            conversation_id,
        )
    if value is None:
        raise NotFoundError("chat_conversation_not_found", code="chat_not_found")
    return value


async def _skill_slugs(tenant_id: UUID, conversation_id: UUID) -> dict[UUID, str]:
    async with tenant_scope(tenant_id) as conn:
        rows = await list_skill_audit_log(
            conn, tenant_id=tenant_id, conversation_id=conversation_id, limit=200
        )
    return {r.id: r.skill_slug for r in rows}


async def send_message(
    tenant_id: UUID,
    chat_id: UUID,
    text: str,
    *,
    graph: CompiledStateGraph,
    observability: ObservabilityClient | None,
) -> ChatTurn:
    """Un turno real del grafo. Comprueba el tope diario antes de gastar nada."""
    run = await get_chat(tenant_id, chat_id)
    assert run.conversation_id is not None
    await ensure_simulation_budget(tenant_id)

    end_customer_id = await _end_customer_id(tenant_id, run.conversation_id)
    turn_number = (run.turns_count or 0) + 1
    skills_before = await _skill_slugs(tenant_id, run.conversation_id)
    await _persist_customer_message(tenant_id, run.conversation_id, text)

    trace = (
        observability.start_conversation_trace(
            tenant_id=str(tenant_id),
            conversation_id=str(run.conversation_id),
            end_customer_id=str(end_customer_id),
            channel="chat",
            input_text=text,
            extra_metadata={"simulation": True, "simulation_run_id": str(run.id)},
            extra_tags=["simulation", "interactive"],
        )
        if observability is not None
        else None
    )
    primary = trace.primary if trace else None
    state = build_chat_state(
        tenant_id=tenant_id,
        run=run,
        end_customer_id=end_customer_id,
        text=text,
        turn_number=turn_number,
        trace=primary,
    )
    trace_id = str(primary.run_id) if primary else None

    final_state: AgentState | None = None
    error: str | None = None
    with open_ledger() as ledger:
        try:
            final_state = await asyncio.wait_for(graph.ainvoke(state), timeout=TURN_TIMEOUT_SECONDS)
        except TimeoutError:
            error = "turn_timeout"
        except Exception:
            logger.exception("chat_graph_invoke_failed run_id=%s turn=%d", run.id, turn_number)
            error = "graph_invoke_failed"
    if final_state is not None:
        final_state = ledger.overlay(final_state)  # type: ignore[assignment]
    _finalize_trace(observability, trace, final_state, error=error, ledger=ledger)

    if final_state is None:
        decision, reply, reason = "error", "", None
        cost_usd, tokens = ledger.cost_usd, 0
    else:
        if error is None and final_state.get("error"):
            error = str(final_state["error"])
        decision = "error" if error else str(final_state.get("decision", "respond"))
        reply = simulated_chat_reply(final_state)
        reason = final_state.get("escalation_reason")
        cost_usd = float(final_state.get("cost_usd", 0.0))
        tokens = int(final_state.get("tokens_in", 0)) + int(final_state.get("tokens_out", 0))
        ack = _chat_ack(final_state)
        if ack is not None:
            await _persist_escalation_ack(tenant_id, run.conversation_id, ack)

    skills_after = await _skill_slugs(tenant_id, run.conversation_id)
    skills = [slug for sid, slug in skills_after.items() if sid not in skills_before]
    cost_cents = round(cost_usd * 100, 4)
    reason_text = str(reason) if reason else None
    entries = [
        {"role": "customer", "content": text, "turn_number": turn_number},
        {
            "role": "agent",
            "content": reply,
            "turn_number": turn_number,
            "decision": decision,
            "escalation_reason": reason_text,
            "skills": skills,
            "trace_id": trace_id,
            "cost_cents": cost_cents,
            "error": error,
        },
    ]
    async with tenant_scope(tenant_id) as conn:
        updated = await append_interactive_turn(
            conn, run.id, tenant_id, entries=entries, cost_cents=cost_cents, tokens_agent=tokens
        )
    session_cost = float(updated.cost_cents or 0) if updated else cost_cents

    if error == "turn_timeout":
        raise ChatTurnTimeout(f"El turno superó {TURN_TIMEOUT_SECONDS}s")
    return ChatTurn(
        decision=decision,
        response_text=reply,
        escalation_reason=reason_text,
        skills=skills,
        trace_id=trace_id,
        cost_cents=cost_cents,
        error=error,
        session_cost_cents=session_cost,
    )
