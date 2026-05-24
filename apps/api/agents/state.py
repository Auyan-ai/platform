"""Estado del grafo del agente.

LangGraph requiere `TypedDict`. Usamos `total=False` para que cada nodo pueda
devolver un dict parcial — LangGraph mergea por key.

Los UUIDs viajan como `str` para que el state sea trivialmente JSON-serializable
(necesario si en el futuro habilitamos checkpointing). Los nodos convierten a
`UUID(...)` cuando lo necesitan.
"""

from __future__ import annotations

from typing import Literal, TypedDict

Decision = Literal["respond", "escalate"]


class AgentState(TypedDict, total=False):
    """Estado completo del grafo. Ver docs/architecture.md para el diagrama."""

    # --- Inputs poblados por el caller (router del webhook) ---
    tenant_id: str
    conversation_id: str
    inbound_message_id: str
    inbound_message_content: str
    channel: str
    end_customer_id: str

    # --- Producido por load_tenant_context ---
    tenant_config: dict
    system_prompt: str
    model_used: str
    # Credenciales descifradas de la integración commerce activa del tenant.
    # Estructura: {"tenant_id": str, "credentials": {"domain": ..., "token": ...}, "config": dict}.
    # None si el tenant no tiene integración commerce configurada.
    commerce_integration_ctx: dict | None

    # --- Producido por load_conversation ---
    conversation_history: list[dict]
    end_customer: dict

    # --- Producido por retrieve_knowledge ---
    retrieved_chunks: list[dict]

    # --- Producido por reason ---
    decision: Decision
    confidence: float
    escalation_reason: str | None
    agent_response: str | None

    # --- Telemetría del LLM (acumulada en reason) ---
    tokens_in: int
    tokens_out: int
    cost_usd: float

    # --- Producido por respond / escalate / handle_error ---
    output_message_id: str
    escalation_id: str

    # --- Trace (poblado por el caller antes de invocar el grafo) ---
    langfuse_trace_id: str | None

    # --- Control de flujo: si está poblado, el grafo rutea a handle_error ---
    error: str | None

    # --- ReAct loop (Sprint 6.3+) ---
    # pending_tool_call: lo setea reason cuando el LLM pidió una skill.
    # execute_skill lo consume, ejecuta y lo limpia.
    # Estructura: {"id": str, "slug": str, "input": dict}
    pending_tool_call: dict | None

    # tool_results: historial acumulado de skill executions en este turno.
    # Cada entry: {"id", "slug", "input", "output", "is_error", "error"}.
    # reason lo lee para reconstruir el contexto multi-turn de Anthropic.
    tool_results: list[dict]

    # Contadores del loop ReAct.
    tool_iterations: int
    max_tool_iterations: int

    # Skills habilitadas para este turno (lo setea select_aop en Sprint 7).
    # Lista vacía = ninguna skill permitida (fail-safe).
    allowed_skills: list[str]

    # --- AOP (Sprint 7+) ---
    # select_aop setea estos campos. Si no están presentes, reason usa el
    # system_prompt legacy de tenant_prompts (backward compat sin AOPs).
    aop_slug: str
    aop_version: int
    aop_workspace: str
    intent_confidence: float

    # Control de persistencia del AOP entre turnos.
    # aop_locked_until_turn: nº de turno hasta el que el AOP está locked (Sprint 9+).
    # aop_completed_signal: el flujo del AOP terminó, reclasificar en el próximo turno.
    # pending_intent: slug del intent alternativo detectado por el clasificador.
    aop_locked_until_turn: int
    aop_completed_signal: bool
    pending_intent: str

    # --- Tool Permissions (Sprint 10) ---
    # Mapa slug → {is_enabled: bool, human_approval_required: bool, threshold_override: float|None}
    # Cargado por load_tenant_context desde tenant_tool_permissions.
    # execute_skill lo consulta para decidir si puede ejecutar la skill.
    tool_permissions: dict

    # Seteado por execute_skill cuando una skill L3 requiere aprobación humana.
    # El nodo escalate lo incluye en el contexto de escalación.
    pending_approval_id: str | None

    # --- Supervisor pattern (Sprint 8) ---
    # El nodo `supervise` evalúa la decisión propuesta por `reason` cuando el AOP
    # tiene require_supervision=true o cuando la tool es L2/L3.
    supervisor_verdict: Literal["approve", "reject"]   # resultado del supervisor
    supervisor_reason: str                             # explicación del supervisor
    supervisor_reject_kind: Literal["tactical", "structural"]  # tactical=reintentable
    # ya se reintentó → si rechaza de nuevo, escala
    supervisor_retried: bool
    supervisor_model_used: str                         # qué modelo fue el supervisor
    supervisor_tokens_in: int                          # tokens del supervisor
    supervisor_tokens_out: int                         # tokens del supervisor
