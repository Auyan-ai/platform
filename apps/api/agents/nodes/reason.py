"""Nodo: reason — núcleo del agente con loop ReAct.

1. Compone system prompt = base_tenant + bloque RAG.
2. Construye historial en formato Anthropic + ciclos tool_use/tool_result de
   iteraciones previas (loop ReAct multi-turn).
3. Construye la lista de tools: decide tool + skills permitidas por el AOP.
4. Pide a Claude una decisión con alguna tool (`call_claude_for_decision`): forzada
   en los modelos que lo aceptan, `auto` + instrucción en los 5.5. Sin decisión
   (refusal, sin tool tras el reintento) → `error` explícito y `handle_error` escala.
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
from datetime import datetime
from typing import Any, Literal

from apps.api.agents.commerce_mode import commerce_mode
from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._reply import surface_of
from apps.api.agents.prompts.builder import (
    build_message_history,
    build_system_blocks,
    conversation_context_block,
    supervisor_feedback_block,
)
from apps.api.agents.schemas import RESPOND_OR_ESCALATE_TOOL, AgentDecisionTool
from apps.api.agents.state import AgentState
from apps.api.core.config import get_models
from apps.api.integrations.anthropic_client import (
    NoDecision,
    ToolDecision,
    call_claude_for_decision,
    operator_messages_supported,
    operator_note,
)
from apps.api.integrations.pricing import compute_llm_cost
from apps.api.services.conversation_progress import no_progress_reason
from apps.api.services.fixed_texts import fixed_text
from apps.api.services.identity import IdentityContext
from apps.api.services.language import state_languages
from apps.api.services.returns_policy import ActivePolicy, policy_note
from apps.api.services.skill_access import visible_skills
from apps.api.services.tenant_time import tenant_zone
from apps.api.skills.registry import SkillRegistry
from pydantic import ValidationError

logger = logging.getLogger(__name__)

DECIDE_TOOL_NAME: str = RESPOND_OR_ESCALATE_TOOL["name"]


def _fixed_reply(state: AgentState, key: str) -> str:
    """Texto fijo al cliente en el idioma de la conversación."""
    language, tenant_default = state_languages(state)
    return fixed_text(key, language, tenant_default=tenant_default)


def _tenant_now_str(tenant_facts: dict | None) -> str:
    """Fecha y hora ACTUAL en la zona horaria de la tienda (tenant_facts['timezone'],
    default Europe/Madrid), con hora + etiqueta de zona.

    Reemplaza el viejo `datetime.now(UTC).date()`: en UTC, cerca de medianoche el 'hoy'
    se desplazaba un día para tiendas ES → off-by-one en ventanas de devolución. Si la
    zona es inválida cae a Europe/Madrid; si falta la tzdata del sistema, a UTC.
    """
    tz_name, tz = tenant_zone(tenant_facts)
    now = datetime.now(tz)
    return f"{now.strftime('%Y-%m-%d %H:%M')} ({tz_name})"


_RETURN_SKILLS = frozenset({"shopify.start_return", "shopify.start_exchange"})


def _returns_policy_note(state: AgentState) -> str | None:
    """Resumen de la política de devoluciones: cualquier AOP puede contestar por el plazo, y
    el supervisor lo contrasta con esto. Que no está configurada solo se dice donde el AOP
    puede abrir una devolución."""
    active = ActivePolicy.from_state(state.get("returns_policy"))
    if active is None and not _RETURN_SKILLS & set(state.get("allowed_skills") or []):
        return None
    return policy_note(active)


def turn_now(state: AgentState) -> str:
    """La hora del turno, leída en la primera vuelta de `reason` y fija hasta el final: el
    system no cambia entre vueltas (con thinking preservado, un cambio invalida los thinking
    blocks de las vueltas anteriores)."""
    return state.get("turn_now") or _tenant_now_str(state.get("tenant_facts"))


def agent_system_blocks(state: AgentState) -> list[dict[str, Any]]:
    """El system de `reason`: prompt compilado (cacheado) + bloque volátil del turno.

    El supervisor lo lee como evidencia: si viera menos que el agente, rechazaría como
    inventado lo que el agente sacó de ahí (#261, #327)."""
    return build_system_blocks(
        state["system_prompt"],
        state.get("retrieved_chunks", []),
        current_date=turn_now(state),
        known_facts=state.get("known_facts"),
        supervisor_feedback=state.get("supervisor_feedback"),
        conversation_context=conversation_context_block(
            state.get("conversation_history") or [], state.get("end_customer")
        ),
        writing_surface=surface_of(state),
        identity_note=state.get("identity_note"),
        returns_policy_note=_returns_policy_note(state),
        response_language=state.get("response_language"),
    )


UNRUN_TOOL_RESULT = (
    "Esta herramienta no se ejecutó: se ejecuta una por vuelta. "
    "Si todavía la necesitas, vuelve a pedirla."
)


def _tool_result_block(result: dict[str, Any]) -> dict[str, Any]:
    if result["is_error"]:
        text = result.get("error") or "unknown_error"
    else:
        text = json.dumps(result["output"], ensure_ascii=False)
    return {
        "type": "tool_result",
        "tool_use_id": result["id"],
        "content": text,
        "is_error": result["is_error"],
    }


def _append_tool_result_blocks(
    messages: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    assistant_turns: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Appendea los ciclos tool_use/tool_result de iteraciones previas al historial.

    Anthropic espera, después del último mensaje user del cliente:
        [{role: assistant, content: [thinking..., texto..., tool_use...]},
         {role: user,      content: [un tool_result por tool_use]},
         ...]
    El turno del assistant vuelve tal como lo escribió el modelo (`assistant_turns`, por id
    de la tool ejecutada): con thinking preservado, cambiarlo invalida sus thinking blocks.
    Se ejecuta una tool por vuelta; un `tool_use` en paralelo que no corrió recibe un
    `tool_result` de error que lo dice. Sin turno guardado se reconstruye el `tool_use`.
    """
    turns = assistant_turns or {}
    for result in tool_results:
        stored = turns.get(result["id"])
        content: list[dict[str, Any]] = (
            stored["content"]
            if stored
            else [
                {
                    "type": "tool_use",
                    "id": result["id"],
                    "name": result["slug"].replace(".", "_"),
                    "input": result["input"],
                }
            ]
        )
        messages.append({"role": "assistant", "content": content})
        messages.append(
            {
                "role": "user",
                "content": [
                    _tool_result_block(result)
                    if block["id"] == result["id"]
                    else {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": UNRUN_TOOL_RESULT,
                        "is_error": True,
                    }
                    for block in content
                    if block.get("type") == "tool_use"
                ],
            }
        )
    return messages


def _agent_request(
    state: AgentState, model: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """System y mensajes de esta vuelta.

    El feedback del supervisor (o el del reintento por idioma) va, donde el modelo lo
    admite, como mensaje del operador justo después de lo que el agente tenía delante al
    decidir (`supervisor_feedback_at`, ciclos de tools hasta entonces) y ahí se queda en
    las vueltas siguientes: el system no cambia y el historial solo crece, así los
    thinking blocks replayados siguen valiendo. Donde no, va en el system como siempre."""
    feedback = state.get("supervisor_feedback")
    as_message = bool(feedback) and operator_messages_supported(model)
    system_blocks = agent_system_blocks(
        {**state, "supervisor_feedback": None} if as_message else state
    )
    history = build_message_history(state["conversation_history"])
    tool_results = state.get("tool_results", [])
    messages = _append_tool_result_blocks(list(history), tool_results, state.get("assistant_turns"))
    if as_message:
        anchor = state.get("supervisor_feedback_at")
        cycles = len(tool_results) if anchor is None else min(anchor, len(tool_results))
        messages.insert(
            len(history) + 2 * cycles, operator_note(supervisor_feedback_block(feedback or ""))
        )
    return system_blocks, messages


ReasonRole = Literal["default_agent_model", "simple_turn_model"]


def _reason_role(state: AgentState) -> ReasonRole:
    """Rol del registro que fija thinking y esfuerzo de este turno (ver `_select_reason_model`)."""
    if _visible_skills(state) or state.get("tool_results") or state.get("pending_tool_call"):
        return "default_agent_model"
    return "simple_turn_model"


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
    if _reason_role(state) == "default_agent_model":
        return state["model_used"]
    return get_models().simple_turn_model


def _visible_skills(state: AgentState) -> list[str]:
    """Skills del AOP que el LLM puede ver (ADR 0013 §5): las que el tenant tiene
    encendidas en `tenant_tool_permissions` y que la identidad del turno permite. El
    código no ofrece lo que el gate de `execute_skill` rechazaría."""
    return visible_skills(
        state.get("allowed_skills") or [],
        state.get("tool_permissions") or {},
        IdentityContext.from_state(state.get("identity")),
        commerce=bool(state.get("commerce_integration_ctx") or commerce_mode(state) != "live"),
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

        # Conversación de pedidos que no avanza: al equipo, sin gastar otra vuelta del LLM.
        if not state.get("tool_iterations") and not state.get("tool_results"):
            stalled = no_progress_reason(
                allowed_skills=state.get("allowed_skills") or [],
                history=state.get("conversation_history"),
                order_refs_given=bool(state.get("order_refs_given")),
                order_in_context=bool(state.get("order_in_context")),
            )
            if stalled is not None:
                return {
                    "decision": "escalate",
                    "escalation_reason": stalled,
                    "agent_response": _fixed_reply(state, "no_progress"),
                    "pending_tool_call": None,
                }

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

        state = {**state, "turn_now": turn_now(state)}  # type: ignore[typeddict-item]
        allowed_skills = _visible_skills(state)
        tools = _build_tools(allowed_skills)
        model = _select_reason_model(state)
        system_blocks, messages = _agent_request(state, model)

        # Iteraciones agotadas: último turno SOLO para decidir (respond/escalate) con
        # lo ya obtenido. Las tools siguen definidas (el historial trae tool_use de
        # skills) pero la petición pide el decide tool.
        tool_iterations: int = state.get("tool_iterations", 0)
        max_iterations: int = state.get("max_tool_iterations") or 5
        iterations_exhausted = tool_iterations >= max_iterations

        outcome = await call_claude_for_decision(
            client=deps.anthropic,
            model=model,
            role=_reason_role(state),
            system=system_blocks,
            messages=messages,
            tools=tools,
            decision=ToolDecision(DECIDE_TOOL_NAME, any_tool=True, closing=iterations_exhausted),
            max_retries=deps.settings.llm_max_retries,
            timeout_seconds=deps.settings.llm_timeout_seconds,
            cache=True,
            trace_label="reason",
            replay_prefixes={
                tool_id: turn.get("prefix", "")
                for tool_id, turn in (state.get("assistant_turns") or {}).items()
            },
        )

        # Acumular tokens/costo con lo que ya hubiera de iteraciones previas.
        usage = outcome.usage
        tokens_update: dict[str, Any] = {
            "tokens_in": state.get("tokens_in", 0) + usage.prompt_tokens,
            "tokens_cache_write": state.get("tokens_cache_write", 0) + usage.cache_write_tokens,
            "tokens_cache_read": state.get("tokens_cache_read", 0) + usage.cache_read_tokens,
            "tokens_out": state.get("tokens_out", 0) + usage.output_tokens,
            "cost_usd": state.get("cost_usd", 0.0) + compute_llm_cost(model, usage),
            "model_used": model,
            "turn_now": state["turn_now"],
            "llm_call": outcome.call.as_dict() if outcome.call else None,
        }
        if isinstance(outcome, NoDecision):
            return {"error": outcome.reason, **tokens_update}

        tool_block = outcome.block
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
                "agent_response": _fixed_reply(state, "iterations_exhausted"),
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
            "assistant_turns": {
                **(state.get("assistant_turns") or {}),
                tool_block.id: {"content": outcome.content, "prefix": outcome.prefix},
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
