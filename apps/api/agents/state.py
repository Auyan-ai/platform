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
    # Nombre comercial del tenant: fallback de la firma de correo (`El equipo de {nombre}`).
    tenant_name: str
    system_prompt: str
    model_used: str
    # Credenciales descifradas de la integración commerce activa del tenant.
    # Estructura: {"tenant_id": str, "credentials": {"domain": ..., "token": ...}, "config": dict}.
    # None si el tenant no tiene integración commerce configurada.
    commerce_integration_ctx: dict | None
    # Playbook y facts del tenant — inyectados en el system prompt del agente por compile_aop.
    # Ambos son None si el tenant aún no completó el onboarding.
    tenant_playbook: dict | None  # TenantPlaybook.model_dump()
    tenant_facts: dict | None     # TenantFacts.data (el JSONB plano)

    # --- Producido por load_conversation ---
    conversation_history: list[dict]
    end_customer: dict

    # --- Producido por resolve_identity (ADR 0013) ---
    # Grants del turno, solo con hashes (`IdentityContext.to_state()`).
    identity: dict
    # Nivel y métodos para trazas; nunca claims ni contactos.
    identity_summary: dict
    # Línea de código para el bloque volátil de reason.
    identity_note: str
    # Sal del tenant para hashear los claims de los pedidos. No se traza.
    claim_salt: str

    # --- Producido por retrieve_knowledge ---
    retrieved_chunks: list[dict]

    # --- Producido por reason ---
    # None explícito cuando reason pide una skill: anula la decisión de una
    # pasada anterior rechazada por el supervisor (el merge de LangGraph
    # conserva las keys que el parche no incluye).
    decision: Decision | None
    confidence: float
    escalation_reason: str | None
    agent_response: str | None
    # True si la respuesta del agente pide más datos al cliente (pregunta de
    # clarificación) o si se escaló: en esos casos NO se marca resolución autónoma.
    awaiting_customer_reply: bool
    # Seteado por respond: la respuesta resuelve la conversación si llega al
    # cliente. El caller post-grafo la entrega y solo entonces marca 'resolved'
    # + billing + cierre del ticket (services.agent_resolution).
    resolves_on_delivery: bool

    # --- Telemetría del LLM (acumulada en reason) ---
    tokens_in: int
    tokens_out: int
    cost_usd: float

    # --- Producido por respond / escalate / handle_error ---
    output_message_id: str
    escalation_id: str
    # True solo cuando escalate creó una escalación nueva (no al reusar una activa).
    # El caller post-grafo empuja la nota interna + asignación al helpdesk solo en
    # ese caso, para no duplicar notas en cada mensaje de una conversación ya escalada.
    escalation_created: bool

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

    # Pasos del AOP activo — lista de {id, name, decision_point}.
    # Vacía si el AOP no define steps[] (backward compat total).
    # Usada por reason para emitir step_entered/step_completed.
    aop_steps: list[dict]

    # pending_intent: slug del intent alternativo detectado por el clasificador
    # (multi-intent en un mismo mensaje). Reservado para desambiguación futura.
    pending_intent: str

    # Propagados desde el AOP compilado por select_aop (PR graph-fixes).
    # aop_confidence_threshold: umbral para escalar la RESPUESTA, por-AOP. reason lo usa
    #   en vez de tenant_config.escalation_threshold cuando hay un AOP activo.
    # aop_require_supervision: el AOP pide supervisar la respuesta (no solo por tier de tool).
    aop_confidence_threshold: float
    aop_require_supervision: bool

    # --- Tool Permissions (Sprint 10) ---
    # Mapa slug → {is_enabled: bool, human_approval_required: bool, threshold_override: float|None}
    # Cargado por load_tenant_context desde tenant_tool_permissions.
    # execute_skill lo consulta para decidir si puede ejecutar la skill.
    tool_permissions: dict

    # Seteado por execute_skill cuando una skill L3 requiere aprobación humana.
    # El nodo escalate lo incluye en el contexto de escalación.
    pending_approval_id: str | None
    # Slug de la skill que quedó pendiente de aprobación. El nodo escalate lo usa
    # para redactar un mensaje del gate cálido y contextual (no plantilla genérica).
    pending_approval_skill_slug: str | None
    # True si la aprobación ya existía (el cliente volvió a escribir mientras seguía
    # en revisión). escalate emite un mensaje de espera en vez de repetir el gate.
    pending_approval_is_repeat: bool

    # Bloque de "datos ya verificados" en esta conversación (outputs de skills de
    # lectura previas), inyectado por load_conversation en el contexto de reason y
    # del supervisor para no re-consultar lo mismo cada turno. "" si no hay.
    known_facts: str
    # Status del approval reusado en un re-disparo ("pending" | "approved" | None).
    # escalate elige el mensaje: "sigue en revisión" si pending, "ya aplicado" si
    # approved (no contradecir un cambio ya confirmado).
    pending_approval_reused_status: str | None

    # --- LangSmith node-level tracing ---
    _trace_run_id: str | None
    _trace_dotted_order: str | None

    # --- Simulator (Bloque 0, Sub-PR 0.10) ---
    # simulation_mode: cuando es True, execute_skill inyecta un mock de commerce
    # (MockShopifyAdapter) en vez del adapter real. El grafo no hace I/O externo
    # (helpdesk y Langfuse los maneja el caller), así que no hace falta tocar más nodos.
    # simulation_fixtures: respuestas predefinidas por método del adapter, p.ej.
    # {"shopify": {"get_order_by_name": {...}, "search_orders_by_email": [...]}}.
    simulation_mode: bool
    simulation_fixtures: dict
    # forced_aop_slug: si está presente en modo simulación, select_aop carga ese AOP
    # directamente sin llamar al intent classifier. Permite que los scenarios controlen
    # qué AOP usa el grafo, aislando el test del clasificador de intent.
    forced_aop_slug: str

    # --- Supervisor pattern (Sprint 8) ---
    # El nodo `supervise` evalúa la decisión propuesta por `reason` cuando el AOP
    # tiene require_supervision=true o cuando la tool es L2/L3.
    supervisor_verdict: Literal["approve", "reject"]   # resultado del supervisor
    supervisor_reason: str                             # explicación del supervisor
    supervisor_reject_kind: Literal["tactical", "structural"]  # tactical=reintentable
    # ya se reintentó → si rechaza de nuevo, escala
    supervisor_retried: bool
    # Corrección a aplicar tras un reject tactical. reason lo inyecta como bloque
    # dinámico (NO cacheado), no concatenado al system_prompt: si fuera al system_prompt
    # rompería el prefijo cacheado (#211) y el retry pagaría todo el input sin caché.
    supervisor_feedback: str | None
    supervisor_model_used: str                         # qué modelo fue el supervisor
    supervisor_tokens_in: int                          # tokens del supervisor
    supervisor_tokens_out: int                         # tokens del supervisor
