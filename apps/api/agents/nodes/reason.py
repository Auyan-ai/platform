"""Nodo: reason — núcleo del agente con loop ReAct.

1. Compone system prompt = base_tenant + bloque RAG.
2. Construye historial en formato Anthropic + ciclos tool_use/tool_result de
   iteraciones previas (loop ReAct multi-turn).
3. Construye la lista de tools: decide tool + skills permitidas por el AOP.
4. Llama a Claude con `tool_choice={"type":"any"}` — fuerza el uso de alguna
   tool pero deja al LLM elegir cuál.
5. Si eligió el decide tool: valida output, aplica threshold override, setea
   `decision`/`agent_response`/`escalation_reason`.
6. Si eligió una skill tool: setea `pending_tool_call` para que `execute_skill`
   la corra. NO setea decision (eso vendrá en la próxima vuelta del loop).
7. Acumula tokens y costo entre iteraciones.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._reply import surface_of
from apps.api.agents.prompts.builder import (
    build_message_history,
    build_system_blocks,
    conversation_context_block,
)
from apps.api.agents.schemas import RESPOND_OR_ESCALATE_TOOL, AgentDecisionTool
from apps.api.agents.state import AgentState
from apps.api.core.config import get_models
from apps.api.integrations.anthropic_client import call_claude_with_tools
from apps.api.integrations.pricing import LLMUsage, compute_llm_cost
from apps.api.services.identity import IdentityContext
from apps.api.services.skill_access import visible_skills
from apps.api.skills.registry import SkillRegistry
from pydantic import ValidationError

logger = logging.getLogger(__name__)

DECIDE_TOOL_NAME: str = RESPOND_OR_ESCALATE_TOOL["name"]

# Cortesía al escalar por loop de tools sin decisión (caso defensivo, ver abajo).
ITERATIONS_EXHAUSTED_MESSAGE: str = (
    "Gracias por escribirnos. He pasado tu consulta a una persona del equipo, "
    "que la revisará y te responderá lo antes posible."
)

# Zona horaria por defecto del vertical e-commerce ES. Cada tenant puede sobrescribirla
# en tenant_facts["timezone"].
_DEFAULT_TENANT_TZ = "Europe/Madrid"


def _tenant_now_str(tenant_facts: dict | None) -> str:
    """Fecha y hora ACTUAL en la zona horaria de la tienda (tenant_facts['timezone'],
    default Europe/Madrid), con hora + etiqueta de zona.

    Reemplaza el viejo `datetime.now(UTC).date()`: en UTC, cerca de medianoche el 'hoy'
    se desplazaba un día para tiendas ES → off-by-one en ventanas de devolución. Si la
    zona es inválida cae a Europe/Madrid; si falta la tzdata del sistema, a UTC.
    """
    tz_name = (tenant_facts or {}).get("timezone") or _DEFAULT_TENANT_TZ
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz_name = _DEFAULT_TENANT_TZ
        try:
            tz = ZoneInfo(_DEFAULT_TENANT_TZ)
        except ZoneInfoNotFoundError:
            tz_name, tz = "UTC", UTC
    now = datetime.now(tz)
    return f"{now.strftime('%Y-%m-%d %H:%M')} ({tz_name})"


def agent_system_blocks(state: AgentState) -> list[dict[str, Any]]:
    """El system de `reason`: prompt compilado (cacheado) + bloque volátil del turno.

    El supervisor lo lee como evidencia: si viera menos que el agente, rechazaría como
    inventado lo que el agente sacó de ahí (#261, #327)."""
    return build_system_blocks(
        state["system_prompt"],
        state.get("retrieved_chunks", []),
        current_date=_tenant_now_str(state.get("tenant_facts")),
        known_facts=state.get("known_facts"),
        supervisor_feedback=state.get("supervisor_feedback"),
        conversation_context=conversation_context_block(
            state.get("conversation_history") or [], state.get("end_customer")
        ),
        writing_surface=surface_of(state),
        identity_note=state.get("identity_note"),
    )


def _append_tool_result_blocks(
    messages: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Appendea los ciclos tool_use/tool_result de iteraciones previas al historial.

    Anthropic espera, después del último mensaje user del cliente:
        [{role: assistant, content: [tool_use block]},
         {role: user,      content: [tool_result block]},
         ...]
    """
    for result in tool_results:
        anthropic_name = result["slug"].replace(".", "_")
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": result["id"],
                        "name": anthropic_name,
                        "input": result["input"],
                    }
                ],
            }
        )
        if result["is_error"]:
            tool_result_text = result.get("error") or "unknown_error"
        else:
            tool_result_text = json.dumps(result["output"], ensure_ascii=False)
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": result["id"],
                        "content": tool_result_text,
                        "is_error": result["is_error"],
                    }
                ],
            }
        )
    return messages


def _select_reason_model(state: AgentState) -> str:
    """Router por complejidad (palanca de latencia): Haiku para turnos sin riesgo.

    Un turno es "simple" cuando NO puede tocar la tienda: el AOP activo no tiene
    skills permitidas, no venimos de un hop del loop ReAct (sin tool_results) y no
    hay una tool pendiente. En ese caso `_build_tools` solo expone el decide tool,
    así que el único desenlace posible es respond/escalate puro — Haiku basta y es
    mucho más rápido (saludos, "gracias", FAQ conversacional). Apenas el turno
    pueda usar una herramienta, se mantiene el modelo del tenant (Sonnet).

    Invariante: `state["model_used"]` aquí es el modelo del tenant. El state se
    reconstruye por cada mensaje inbound (no hay checkpointer) y un turno simple es
    de una sola vuelta, así que la elección Haiku nunca contamina el base de otro turno.
    """
    tenant_model = state["model_used"]
    if _visible_skills(state):
        return tenant_model
    if state.get("tool_results") or state.get("pending_tool_call"):
        return tenant_model
    return get_models().simple_turn_model


def _visible_skills(state: AgentState) -> list[str]:
    """Skills del AOP que el LLM puede ver (ADR 0013 §5): las que el tenant tiene
    encendidas en `tenant_tool_permissions` y que la identidad del turno permite. El
    código no ofrece lo que el gate de `execute_skill` rechazaría."""
    return visible_skills(
        state.get("allowed_skills") or [],
        state.get("tool_permissions") or {},
        IdentityContext.from_state(state.get("identity")),
        commerce=bool(state.get("commerce_integration_ctx") or state.get("simulation_mode")),
    )


def _build_tools(allowed_skills: list[str]) -> list[dict[str, Any]]:
    """Construye la lista de tools que ve el LLM: decide tool + skills visibles."""
    tools: list[dict[str, Any]] = [RESPOND_OR_ESCALATE_TOOL]
    for slug in allowed_skills:
        try:
            skill_cls = SkillRegistry.get(slug)
        except ValueError:
            logger.warning("allowed_skill_not_in_registry: %s", slug)
            continue
        tools.append(skill_cls().to_anthropic_tool())
    return tools


def _slug_from_anthropic_name(tool_name: str, allowed_skills: list[str]) -> str | None:
    """Mapea nombre Anthropic ('shopify_list_my_orders') → slug interno.

    El mapeo `slug.replace('.', '_')` no es bijectivo, así que buscamos en
    `allowed_skills` cuál coincide.
    """
    for slug in allowed_skills:
        if slug.replace(".", "_") == tool_name:
            return slug
    return None


def _handle_decide_tool(
    tool_input: dict[str, Any],
    state: AgentState,
    tokens_update: dict[str, Any],
) -> dict[str, Any]:
    """Procesa el output del decide tool: respond/escalate + threshold override."""
    try:
        parsed = AgentDecisionTool.model_validate(tool_input)
    except ValidationError as exc:
        return {"error": f"invalid_tool_output: {exc.errors()}", **tokens_update}

    decision = parsed.decision
    escalation_reason: str | None = parsed.escalation_reason
    agent_response: str | None = parsed.response_text
    # Umbral por-AOP si está presente (lo propaga select_aop desde el AOP compilado);
    # si no hay AOP activo, cae al umbral global del tenant.
    aop_threshold = state.get("aop_confidence_threshold")
    threshold = (
        float(aop_threshold)
        if aop_threshold is not None
        else float(state["tenant_config"]["escalation_threshold"])
    )

    if decision == "respond" and parsed.confidence < threshold:
        decision = "escalate"
        escalation_reason = f"low_confidence: {parsed.confidence:.2f} < threshold {threshold:.2f}"
        agent_response = None

    return {
        "decision": decision,
        "confidence": parsed.confidence,
        "agent_response": agent_response,
        "escalation_reason": escalation_reason,
        # El agente resuelve salvo que su respuesta pida más datos al cliente.
        # Un escalado nunca es una resolución autónoma.
        "awaiting_customer_reply": parsed.awaiting_customer_reply or decision == "escalate",
        # Anular una tool pendiente de la pasada anterior (retry post-rechazo
        # del supervisor). LangGraph solo pisa las keys presentes en el parche:
        # sin este None, route_after_reason prioriza la tool residual y re-procesa
        # la acción YA rechazada en vez de la decisión nueva de este retry.
        "pending_tool_call": None,
        **tokens_update,
    }


def make_reason_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    tracker = deps.reasoning_tracker

    async def _node(state: AgentState) -> dict[str, Any]:
        conv_id = state.get("conversation_id")
        tenant_id = state.get("tenant_id")

        # Determinar el step actual del AOP (si está definido).
        steps: list[dict[str, Any]] = state.get("aop_steps") or []
        current_iter: int = state.get("tool_iterations", 0)
        current_step: dict[str, Any] | None = (
            steps[current_iter] if current_iter < len(steps) else None
        )

        # Emitir step_entered antes de llamar al LLM.
        if current_step and conv_id and tenant_id:
            tracker.emit(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                phase="decision",
                event_type="step_entered",
                label=current_step["id"],
                detail={"step_name": current_step["name"], "iteration": current_iter},
                status="done",
            )

        system_blocks = agent_system_blocks(state)
        messages = build_message_history(state["conversation_history"])
        messages = _append_tool_result_blocks(messages, state.get("tool_results", []))

        allowed_skills = _visible_skills(state)
        tools = _build_tools(allowed_skills)

        model = _select_reason_model(state)

        # Iteraciones agotadas: último turno SOLO para decidir (respond/escalate) con
        # lo ya obtenido. Las tools siguen definidas (el historial trae tool_use de
        # skills) pero `tool_choice` fuerza el decide tool.
        tool_iterations: int = state.get("tool_iterations", 0)
        max_iterations: int = state.get("max_tool_iterations") or 5
        iterations_exhausted = tool_iterations >= max_iterations
        tool_choice: dict[str, Any] = (
            {"type": "tool", "name": DECIDE_TOOL_NAME} if iterations_exhausted else {"type": "any"}
        )

        response = await call_claude_with_tools(
            client=deps.anthropic,
            model=model,
            system=system_blocks,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            max_retries=deps.settings.llm_max_retries,
            timeout_seconds=deps.settings.llm_timeout_seconds,
            cache=True,
            trace_label="reason",
        )

        # Extraer el primer tool_use block. tool_choice=any garantiza que exista.
        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block is None:
            return {"error": "claude_did_not_use_tool"}

        # Acumular tokens/costo con lo que ya hubiera de iteraciones previas.
        usage = LLMUsage.from_anthropic(response.usage)
        tokens_update: dict[str, Any] = {
            "tokens_in": state.get("tokens_in", 0) + usage.prompt_tokens,
            "tokens_cache_write": state.get("tokens_cache_write", 0) + usage.cache_write_tokens,
            "tokens_cache_read": state.get("tokens_cache_read", 0) + usage.cache_read_tokens,
            "tokens_out": state.get("tokens_out", 0) + usage.output_tokens,
            "cost_usd": state.get("cost_usd", 0.0) + compute_llm_cost(model, usage),
            "model_used": model,
        }

        tool_name: str = tool_block.name

        if iterations_exhausted and tool_name != DECIDE_TOOL_NAME:
            # Defensa: forzado a decidir y aun así pidió otra skill → cortar el loop
            # escalando, con un mensaje de cortesía para que el cliente no quede
            # sin respuesta.
            return {
                "decision": "escalate",
                "escalation_reason": (
                    f"max_tool_iterations_exceeded ({tool_iterations}/{max_iterations})"
                ),
                "agent_response": ITERATIONS_EXHAUSTED_MESSAGE,
                "pending_tool_call": None,
                **tokens_update,
            }

        # ¿Decide tool o skill tool?
        if tool_name == DECIDE_TOOL_NAME:
            result = _handle_decide_tool(tool_block.input, state, tokens_update)
            if conv_id and tenant_id and not result.get("error"):
                decision = result.get("decision", "unknown")
                # Emitir step_completed antes del choice event.
                if current_step:
                    tracker.emit(
                        tenant_id=tenant_id,
                        conversation_id=conv_id,
                        phase="decision",
                        event_type="step_completed",
                        label=current_step["id"],
                        detail={"outcome": decision},
                        status="done",
                    )
                # Emitir evento de decisión final (respond o escalate).
                tracker.emit(
                    tenant_id=tenant_id,
                    conversation_id=conv_id,
                    phase="response",
                    event_type="choice",
                    label=f"Decision: {decision}",
                    detail={
                        "decision": decision,
                        "confidence": result.get("confidence"),
                        "escalation_reason": result.get("escalation_reason"),
                    },
                    status="done",
                )
            return result

        # Skill tool — mapear name → slug y emitir pending_tool_call.
        slug = _slug_from_anthropic_name(tool_name, allowed_skills)
        if slug is None:
            return {
                "error": f"llm_chose_unknown_tool: {tool_name}",
                **tokens_update,
            }

        if conv_id and tenant_id:
            # Emitir step_completed (el LLM eligió llamar una tool en este step).
            if current_step:
                tracker.emit(
                    tenant_id=tenant_id,
                    conversation_id=conv_id,
                    phase="decision",
                    event_type="step_completed",
                    label=current_step["id"],
                    detail={"outcome": f"tool:{slug}"},
                    status="done",
                )
            # Emitir evento de tool_call antes de ejecutar.
            tracker.emit(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                phase="decision",
                event_type="tool_call",
                label=slug,
                detail={"input": tool_block.input},
                status="pending",
            )

        return {
            "pending_tool_call": {
                "id": tool_block.id,
                "slug": slug,
                "input": tool_block.input,
            },
            # Anular la decisión de la pasada anterior (espejo del caso decide):
            # si el supervisor rechazó un respond y el retry pide una tool, el
            # agent_response rechazado quedaría en el state y escalate lo
            # reenviaría al cliente si este turno muere por max_tool_iterations.
            "decision": None,
            "agent_response": None,
            "escalation_reason": None,
            **tokens_update,
        }

    return _node
