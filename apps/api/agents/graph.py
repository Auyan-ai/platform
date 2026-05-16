"""Construcción y compilación del grafo de LangGraph.

Diagrama (ver `docs/architecture.md` para el detalle):

    START
      ↓
    load_tenant_context
      ↓
    load_conversation
      ↓
    retrieve_knowledge
      ↓
    reason
      ↓
    (conditional) → respond | escalate | handle_error
      ↓                 ↓                ↓
                  finalize_trace
                        ↓
                      END

Los nodos `load_*`, `retrieve_*` y `reason` están envueltos por `@guarded`:
si alguno setea `error` (o lanza), los siguientes hacen passthrough y el
routing condicional lleva a `handle_error`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes.escalate import make_escalate_node
from apps.api.agents.nodes.finalize_trace import make_finalize_trace_node
from apps.api.agents.nodes.handle_error import make_handle_error_node
from apps.api.agents.nodes.load_conversation import make_load_conversation_node
from apps.api.agents.nodes.load_tenant_context import make_load_tenant_context_node
from apps.api.agents.nodes.reason import make_reason_node
from apps.api.agents.nodes.respond import make_respond_node
from apps.api.agents.nodes.retrieve_knowledge import make_retrieve_knowledge_node
from apps.api.agents.state import AgentState
from langgraph.graph import END, START, StateGraph

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


def route_after_reason(state: AgentState) -> str:
    """Conditional edge tras `reason`. Tres destinos posibles."""
    if state.get("error"):
        return "handle_error"
    decision = state.get("decision")
    if decision == "respond":
        return "respond"
    if decision == "escalate":
        return "escalate"
    # Si llegamos sin decisión válida, escalamos via error path.
    return "handle_error"


def build_graph(deps: AgentDependencies) -> CompiledStateGraph:
    """Construye y compila el grafo. Llamar UNA vez en startup; reusar la instancia."""
    graph: StateGraph = StateGraph(AgentState)

    graph.add_node("load_tenant_context", make_load_tenant_context_node(deps))
    graph.add_node("load_conversation", make_load_conversation_node(deps))
    graph.add_node("retrieve_knowledge", make_retrieve_knowledge_node(deps))
    graph.add_node("reason", make_reason_node(deps))
    graph.add_node("respond", make_respond_node(deps))
    graph.add_node("escalate", make_escalate_node(deps))
    graph.add_node("handle_error", make_handle_error_node(deps))
    graph.add_node("finalize_trace", make_finalize_trace_node(deps))

    graph.add_edge(START, "load_tenant_context")
    graph.add_edge("load_tenant_context", "load_conversation")
    graph.add_edge("load_conversation", "retrieve_knowledge")
    graph.add_edge("retrieve_knowledge", "reason")

    graph.add_conditional_edges(
        "reason",
        route_after_reason,
        {
            "respond": "respond",
            "escalate": "escalate",
            "handle_error": "handle_error",
        },
    )

    graph.add_edge("respond", "finalize_trace")
    graph.add_edge("escalate", "finalize_trace")
    graph.add_edge("handle_error", "finalize_trace")
    graph.add_edge("finalize_trace", END)

    return graph.compile()
