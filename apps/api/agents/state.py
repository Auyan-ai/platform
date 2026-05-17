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
