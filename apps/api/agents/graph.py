"""Construcción y compilación del grafo de LangGraph.

Diagrama actual (Sprint 8 — AOPs + ReAct loop + Supervisor):

    START
      ↓
    load_tenant_context
      ↓
    load_conversation
      ↓
    resolve_identity    ← grants de identidad (código, sin LLM)
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

      respond ── texto vacío tras normalizar ──→ escalate (empty_reply)
      respond / escalate / handle_error
                  ↓
            finalize_trace
                  ↓
                 END

Fallos: cada nodo de `TURN_NODES` corre bajo `guarded` y, tras cada uno, un `error`
en el state (excepción capturada o error de negocio) lleva a `handle_error`, que
escala con razón explícita. No hay arista que lo salte.

Supervisor: se activa cuando el AOP tiene require_supervision=true o la
tool pendiente es L2/L3. Usa Sonnet para L1/L2, Opus para L3.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.nodes.escalate import make_escalate_node
from apps.api.agents.nodes.execute_skill import make_execute_skill_node
from apps.api.agents.nodes.finalize_trace import make_finalize_trace_node
from apps.api.agents.nodes.handle_error import make_handle_error_node
from apps.api.agents.nodes.load_conversation import make_load_conversation_node
from apps.api.agents.nodes.load_tenant_context import make_load_tenant_context_node
from apps.api.agents.nodes.reason import make_reason_node
from apps.api.agents.nodes.resolve_identity import make_resolve_identity_node
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
# El 25 por defecto de LangGraph se queda corto: un turno con 5 tools L2 supervisadas,
# supervisión final y un rechazo táctico ronda 26 pasos. Los bucles los frena
# max_tool_iterations; esto solo evita cortar un turno legítimo.
GRAPH_RECURSION_LIMIT = 50

# Allowlist de keys que cada nodo puede emitir a LangSmith. Allowlist, NO denylist:
# un nodo sin entrada aquí emite `{}` (solo el span con timing). Esto evita filtrar
# credenciales (load_tenant_context.commerce_integration_ctx.credentials.token) y PII
# (load_conversation.conversation_history / end_customer) a un SaaS de terceros.
# NUNCA agregar aquí keys que carguen secretos: commerce_integration_ctx, tenant_config.
_NODE_OUTPUT_KEYS: dict[str, list[str]] = {
    "resolve_identity": ["identity_summary", "identity_error"],
    "select_aop": ["aop_slug", "aop_version", "intent_confidence"],
    "reason": ["decision", "confidence", "pending_tool_call", "agent_response"],
    "execute_skill": ["tool_results", "pending_approval_id", "escalation_reason"],
    "supervise": [
        "supervisor_verdict",
        "supervisor_reason",
        "supervisor_reject_kind",
        "escalation_reason",
    ],
    "respond": ["output_message_id", "resolves_on_delivery"],
    "escalate": ["escalation_id", "escalation_reason"],
    "handle_error": ["error"],
}

# Keys sensibles que se redactan recursivamente como defensa en profundidad, por si
# una key permitida llegara a anidar un secreto en el futuro.
_REDACT_KEYS = frozenset(
    {
        "token",
        "access_token",
        "credentials",
        "secret",
        "api_key",
        "password",
        "authorization",
        # PII: la dirección de envío que devuelve get_order_status (tool_results).
        "shipping_address",
    }
)


def _redact(value: object) -> object:
    """Reemplaza recursivamente valores bajo keys sensibles por '[REDACTED]'."""
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if k.lower() in _REDACT_KEYS else _redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Variante tipada de `_redact` para outputs (siempre un dict en el top level)."""
    return {k: ("[REDACTED]" if k.lower() in _REDACT_KEYS else _redact(v)) for k, v in data.items()}


def _traced(
    name: str,
    node_fn: Callable[[AgentState], Awaitable[dict[str, Any]]],
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Envuelve un nodo del grafo para registrar un child run en LangSmith."""
    obs = deps.observability

    async def wrapper(state: AgentState) -> dict[str, Any]:
        if obs is None:
            return await node_fn(state)

        trace_run_id = state.get("_trace_run_id")
        trace_dotted_order = state.get("_trace_dotted_order")
        if not trace_run_id or not trace_dotted_order:
            return await node_fn(state)

        start = datetime.now(UTC)
        error_msg: str | None = None
        result: dict[str, Any] = {}
        try:
            result = await node_fn(state)
            error_msg = result.get("error")
            return result
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            # Allowlist estricta: nodo sin keys declaradas → no se emite output.
            # Evita filtrar credenciales/PII de nodos como load_tenant_context.
            keep_keys = _NODE_OUTPUT_KEYS.get(name, [])
            outputs = _redact_dict({k: result[k] for k in keep_keys if k in result})
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


def route_after_resolve_identity(state: AgentState) -> str:
    """Routing tras `resolve_identity`: un texto fijo de identidad cierra el turno sin LLM."""
    if state.get("decision") == "respond" and state.get("agent_response"):
        return "respond"
    if state.get("decision") == "escalate" and state.get("agent_response"):
        return "escalate"
    return "select_aop"


def route_after_reason(state: AgentState) -> str:
    """Routing tras `reason`. Cinco destinos posibles (incluye supervise)."""
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
    - decision 'escalate' → la skill se negó por una regla en código (`SkillRefusal`)
      y dejó mensaje y motivo fijos → escalate sin pasar por el LLM.
    - resto → volver a reason. Si se agotaron las iteraciones, `reason` hace un
      último turno forzado a decidir (respond/escalate) con lo ya obtenido: antes se
      escalaba en seco y el cliente se quedaba sin respuesta (E2E A4, queja que usa
      sus 4 tools previstas). El loop sigue acotado: ese turno no puede pedir skills.
    """
    if state.get("pending_approval_id") or state.get("decision") == "escalate":
        return "escalate"
    if state.get("decision") == "respond" and state.get("agent_response"):
        # Texto fijo de identidad (`identity.check_order_contact`): no vuelve al LLM.
        return "respond"
    return "reason"


def route_after_respond(state: AgentState) -> str:
    """Routing tras `respond`: texto vacío al normalizarlo (`empty_reply`) o idioma
    equivocado por segunda vez (`language_mismatch`) → escalar; idioma equivocado la
    primera vez → `reason` lo reescribe."""
    if state.get("decision") == "escalate":
        return "escalate"
    if state.get("decision") == "regenerate":
        return "reason"
    return "finalize_trace"


NodeFn = Callable[[AgentState], Awaitable[dict[str, Any]]]
NodeFactory = Callable[[AgentDependencies], NodeFn]
Route = str | Callable[[AgentState], str]

# Nodos del turno: nombre → (factory, siguiente nodo o router). `build_graph` los envuelve
# todos con `guarded` y antepone a su salida el desvío a `handle_error`; un nodo añadido
# fuera de esta tabla rompe test_graph_failures.
TURN_NODES: dict[str, tuple[NodeFactory, Route]] = {
    "load_tenant_context": (make_load_tenant_context_node, "load_conversation"),
    "load_conversation": (make_load_conversation_node, "resolve_identity"),
    "resolve_identity": (make_resolve_identity_node, route_after_resolve_identity),
    "select_aop": (make_select_aop_node, "retrieve_knowledge"),
    "retrieve_knowledge": (make_retrieve_knowledge_node, "reason"),
    "reason": (make_reason_node, route_after_reason),
    "execute_skill": (make_execute_skill_node, route_after_execute_skill),
    "supervise": (make_supervise_node, route_after_supervise),
    "respond": (make_respond_node, route_after_respond),
    "escalate": (make_escalate_node, "finalize_trace"),
}


def _or_handle_error(route: Route) -> Callable[[AgentState], str]:
    def next_node(state: AgentState) -> str:
        if state.get("error"):
            return "handle_error"
        return route if isinstance(route, str) else route(state)

    return next_node


def build_graph(deps: AgentDependencies) -> CompiledStateGraph:
    """Construye y compila el grafo. Llamar UNA vez en startup; reusar la instancia."""
    graph: StateGraph = StateGraph(AgentState)

    for name, (factory, route) in TURN_NODES.items():
        # `guarded` por fuera de `_traced`: el span del nodo registra la excepción.
        graph.add_node(name, guarded(name)(_traced(name, factory(deps), deps)))
        graph.add_conditional_edges(name, _or_handle_error(route))
    for name, factory in (
        ("handle_error", make_handle_error_node),
        ("finalize_trace", make_finalize_trace_node),
    ):
        graph.add_node(name, _traced(name, factory(deps), deps))

    graph.add_edge(START, "load_tenant_context")
    graph.add_edge("handle_error", "finalize_trace")
    graph.add_edge("finalize_trace", END)

    return graph.compile().with_config(recursion_limit=GRAPH_RECURSION_LIMIT)
