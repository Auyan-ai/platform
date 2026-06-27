"""Construcción y compilación del grafo de LangGraph.

Diagrama actual (Sprint 8 — AOPs + ReAct loop + Supervisor):

    START
      ↓
    load_tenant_context
      ↓
    load_conversation
      ↓
    select_aop          ← clasifica intent → elige AOP → compila system_prompt
      ↓
    retrieve_knowledge
      ↓
    reason  ←──────────────────────┐ (reintento si supervisor rechaza tactical)
      ↓                            │
    (conditional)                  │
      ↓                            │
    ┌──────────────┬───────────────┴──┬──────────────┐
    ▼              ▼                  ▼              ▼
  execute_skill supervise          respond      handle_error
      ↓              ↓ approve→ respond|escalate
    ─→ reason    reject+structural→ escalate
    | escalate   reject+tactical → reason (una vez)

      respond / escalate / handle_error
                  ↓
            finalize_trace
                  ↓
                 END

Supervisor: se activa cuando el AOP tiene require_supervision=true o la
tool pendiente es L2/L3. Usa Sonnet para L1/L2, Opus para L3.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes.escalate import make_escalate_node
from apps.api.agents.nodes.execute_skill import make_execute_skill_node
from apps.api.agents.nodes.finalize_trace import make_finalize_trace_node
from apps.api.agents.nodes.handle_error import make_handle_error_node
from apps.api.agents.nodes.load_conversation import make_load_conversation_node
from apps.api.agents.nodes.load_tenant_context import make_load_tenant_context_node
from apps.api.agents.nodes.reason import make_reason_node
from apps.api.agents.nodes.respond import make_respond_node
from apps.api.agents.nodes.retrieve_knowledge import make_retrieve_knowledge_node
from apps.api.agents.nodes.select_aop import make_select_aop_node
from apps.api.agents.nodes.supervise import make_supervise_node, needs_supervision
from apps.api.agents.state import AgentState
from langgraph.graph import END, START, StateGraph

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


logger = logging.getLogger(__name__)

DEFAULT_MAX_TOOL_ITERATIONS = 5

_NODE_OUTPUT_KEYS: dict[str, list[str]] = {
    "select_aop": ["aop_slug", "aop_version", "intent_confidence"],
    "reason": ["decision", "confidence", "pending_tool_call", "agent_response"],
    "execute_skill": ["tool_results", "pending_approval_id"],
    "supervise": ["supervisor_verdict", "supervisor_reason", "supervisor_reject_kind"],
    "respond": ["output_message_id", "conversation_resolved"],
    "escalate": ["escalation_id", "escalation_reason"],
    "handle_error": ["error"],
}


def _traced(
    name: str,
    node_fn: Callable[[AgentState], Awaitable[dict]],
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    """Envuelve un nodo del grafo para registrar un child run en LangSmith."""
    obs = deps.observability

    async def wrapper(state: AgentState) -> dict:
        if obs is None:
            return await node_fn(state)

        trace_run_id = state.get("_trace_run_id")
        trace_dotted_order = state.get("_trace_dotted_order")
        if not trace_run_id or not trace_dotted_order:
            return await node_fn(state)

        start = datetime.now(UTC)
        error_msg: str | None = None
        result: dict = {}
        try:
            result = await node_fn(state)
            return result
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            keep_keys = _NODE_OUTPUT_KEYS.get(name)
            outputs = {k: v for k, v in result.items() if k in keep_keys} if keep_keys else result
            try:
                obs.record_node_run(
                    trace_run_id=trace_run_id,
                    trace_dotted_order=trace_dotted_order,
                    node_name=name,
                    start_time=start,
                    end_time=datetime.now(UTC),
                    outputs=outputs,
                    error=error_msg,
                )
            except Exception:
                logger.debug("node_trace_failed node=%s", name, exc_info=True)

    return wrapper


def route_after_reason(state: AgentState) -> str:
    """Routing tras `reason`. Cinco destinos posibles (incluye supervise)."""
    if state.get("error"):
        return "handle_error"
    if state.get("pending_tool_call"):
        # Skill pendiente — ¿necesita supervisión antes de ejecutar?
        if needs_supervision(state):
            return "supervise"
        return "execute_skill"
    decision = state.get("decision")
    if decision == "respond":
        # ¿La respuesta necesita supervisión? (AOP con require_supervision=true)
        if needs_supervision(state):
            return "supervise"
        return "respond"
    if decision == "escalate":
        return "escalate"
    # Sin decisión válida y sin pending_tool_call: defensive — handle_error.
    return "handle_error"


def route_after_supervise(state: AgentState) -> str:
    """Routing tras `supervise`.

    approve → destino según la decisión original (respond | escalate | execute_skill)
    reject sin escalation_reason → tactical primer rechazo → volver a reason
    reject con escalation_reason → structural o segundo rechazo → escalar

    El nodo `supervise` setea `escalation_reason` cuando no hay reintento posible
    (structural o segundo rechazo tactical). Usamos su presencia como señal.
    """
    if state.get("error"):
        return "handle_error"

    verdict = state.get("supervisor_verdict")

    if verdict == "approve":
        if state.get("pending_tool_call"):
            return "execute_skill"
        decision = state.get("decision")
        if decision == "respond":
            return "respond"
        return "escalate"

    # Reject: si el nodo puso escalation_reason → no reintentar
    if state.get("escalation_reason"):
        return "escalate"

    # Primer rechazo tactical: el nodo no puso escalation_reason → reintentar reason
    return "reason"


def route_after_execute_skill(state: AgentState) -> str:
    """Routing tras `execute_skill`.

    - pending_approval_id → skill L3 esperando aprobación humana → escalate.
    - max_iter superado → escalate.
    - error de sistema → handle_error.
    - resto → volver a reason (siguiente iteración del loop ReAct).
    """
    if state.get("error"):
        return "handle_error"
    if state.get("pending_approval_id"):
        return "escalate"
    max_iter = state.get("max_tool_iterations") or DEFAULT_MAX_TOOL_ITERATIONS
    if state.get("tool_iterations", 0) >= max_iter:
        return "escalate"
    return "reason"


def build_graph(deps: AgentDependencies) -> CompiledStateGraph:
    """Construye y compila el grafo. Llamar UNA vez en startup; reusar la instancia."""
    graph: StateGraph = StateGraph(AgentState)

    def traced(name: str, factory: Callable) -> Callable:
        return _traced(name, factory(deps), deps)

    graph.add_node("load_tenant_context", traced("load_tenant_context", make_load_tenant_context_node))
    graph.add_node("load_conversation", traced("load_conversation", make_load_conversation_node))
    graph.add_node("select_aop", traced("select_aop", make_select_aop_node))
    graph.add_node("retrieve_knowledge", traced("retrieve_knowledge", make_retrieve_knowledge_node))
    graph.add_node("reason", traced("reason", make_reason_node))
    graph.add_node("execute_skill", traced("execute_skill", make_execute_skill_node))
    graph.add_node("supervise", traced("supervise", make_supervise_node))
    graph.add_node("respond", traced("respond", make_respond_node))
    graph.add_node("escalate", traced("escalate", make_escalate_node))
    graph.add_node("handle_error", traced("handle_error", make_handle_error_node))
    graph.add_node("finalize_trace", traced("finalize_trace", make_finalize_trace_node))

    graph.add_edge(START, "load_tenant_context")
    graph.add_edge("load_tenant_context", "load_conversation")
    graph.add_edge("load_conversation", "select_aop")
    graph.add_edge("select_aop", "retrieve_knowledge")
    graph.add_edge("retrieve_knowledge", "reason")

    graph.add_conditional_edges(
        "reason",
        route_after_reason,
        {
            "execute_skill": "execute_skill",
            "supervise": "supervise",
            "respond": "respond",
            "escalate": "escalate",
            "handle_error": "handle_error",
        },
    )

    graph.add_conditional_edges(
        "supervise",
        route_after_supervise,
        {
            "execute_skill": "execute_skill",
            "respond": "respond",
            "escalate": "escalate",
            "reason": "reason",
            "handle_error": "handle_error",
        },
    )

    graph.add_conditional_edges(
        "execute_skill",
        route_after_execute_skill,
        {
            "reason": "reason",
            "escalate": "escalate",
            "handle_error": "handle_error",
        },
    )

    graph.add_edge("respond", "finalize_trace")
    graph.add_edge("escalate", "finalize_trace")
    graph.add_edge("handle_error", "finalize_trace")
    graph.add_edge("finalize_trace", END)

    return graph.compile()
