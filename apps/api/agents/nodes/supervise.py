"""Nodo: supervise — supervisor pattern (Sprint 8).

Activa cuando:
  1. El AOP tiene `require_supervision: true` en su frontmatter, o
  2. La decisión propuesta por `reason` involucra una tool L2/L3.

El supervisor recibe el contexto completo (AOP, guardrails, historial, reasoning
propuesto) y emite un veredicto usando una tool forzada:
  - approve → continúa al destino (respond | escalate)
  - reject + tactical → el agente puede arreglar reintentando (una sola vez)
  - reject + structural → el AOP no aplica / falta capability → escala directo

Modelos:
  - L1/AOP sin tier específico: claude-sonnet-4-6
  - L2:                         claude-sonnet-4-6
  - L3:                         claude-opus-4-7

El supervisor es stateless respecto al grafo: solo lee el state y emite
`supervisor_verdict`, `supervisor_reason`, `supervisor_reject_kind`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.integrations.anthropic_client import call_claude_with_tools
from apps.api.integrations.pricing import compute_llm_cost
from apps.api.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

# Modelos según tier
_SUPERVISOR_MODEL_L1_L2 = "claude-sonnet-4-6"
_SUPERVISOR_MODEL_L3    = "claude-opus-4-7"

SUPERVISOR_VERDICT_TOOL: dict[str, Any] = {
    "name": "supervisor_verdict",
    "description": "Aprobar o rechazar la decisión propuesta por el agente principal.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["approve", "reject"],
                "description": "Aprueba o rechaza la acción propuesta.",
            },
            "reject_kind": {
                "type": "string",
                "enum": ["tactical", "structural", "n/a"],
                "description": (
                    "tactical = el agente puede corregir reintentando "
                    "(ej: 'olvidó verificar fulfillment antes de cancelar'). "
                    "structural = el AOP no aplica o falta capability; reintentar no ayuda. "
                    "n/a = se usa cuando verdict=approve."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Explicación de 1-2 frases. Si reject, qué debe corregir.",
            },
            "guardrails_violated": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Guardrails específicos que se violaron. Vacío si ninguno.",
            },
        },
        "required": ["verdict", "reject_kind", "reason"],
    },
}

_SUPERVISOR_SYSTEM = """\
Eres el supervisor de un agente conversacional de soporte al cliente.
Tu trabajo es evaluar si la decisión propuesta por el agente principal es correcta \
antes de que se ejecute.

No sugieras alternativas largas ni hagas preguntas al usuario. Tu rol es exclusivamente \
evaluar y emitir un veredicto usando la tool supervisor_verdict.

Evalúa estrictamente estos puntos:
1. ¿La decisión respeta TODOS los guardrails del AOP?
2. ¿Los inputs de las tools son correctos y derivan del contexto real (no inventados)?
3. ¿La respuesta propuesta al cliente está respaldada por evidencia concreta?
4. ¿Hay algún escalation_trigger que el agente ignoró?

Sé preciso y conciso. Si apruebas, di brevemente por qué es correcto. \
Si rechazas, explica exactamente qué debe corregir.\
"""


def _select_supervisor_model(state: AgentState) -> str:
    """Elige el modelo supervisor según el tier de la skill pendiente."""
    pending = state.get("pending_tool_call")
    if pending:
        slug = pending.get("slug", "")
        try:
            skill_cls = SkillRegistry.get(slug)
            if skill_cls.tier == "L3":
                return _SUPERVISOR_MODEL_L3
        except ValueError:
            pass
    return _SUPERVISOR_MODEL_L1_L2


def _build_supervisor_prompt(state: AgentState) -> str:
    """Construye el prompt de supervisión con todo el contexto necesario."""
    parts: list[str] = []

    # AOP activo
    aop_slug = state.get("aop_slug", "unknown")
    parts.append(f"## AOP activo: {aop_slug}")

    # Los guardrails están compilados en system_prompt; los extraemos de ahí si podemos
    system_prompt = state.get("system_prompt", "")
    if "Reglas NO negociables" in system_prompt:
        guardrail_section = system_prompt.split("Reglas NO negociables")[-1].split("---")[0]
        parts.append(f"## Guardrails del AOP\n{guardrail_section.strip()}")

    # Tool pendiente (si hay)
    pending = state.get("pending_tool_call")
    if pending:
        parts.append(
            f"## Tool que el agente quiere ejecutar\n"
            f"- Skill: `{pending.get('slug')}`\n"
            f"- Inputs: {json.dumps(pending.get('input', {}), ensure_ascii=False, indent=2)}"
        )

    # Decisión propuesta (si ya hay)
    decision = state.get("decision")
    agent_response = state.get("agent_response")
    escalation_reason = state.get("escalation_reason")
    if decision:
        parts.append(
            f"## Decisión propuesta por el agente\n"
            f"- Decisión: {decision}\n"
            + (f"- Respuesta al cliente: {agent_response}\n" if agent_response else "")
            + (f"- Razón de escalación: {escalation_reason}\n" if escalation_reason else "")
        )

    # Tool results anteriores (contexto de iteraciones previas)
    tool_results = state.get("tool_results") or []
    if tool_results:
        results_summary = []
        for tr in tool_results[-3:]:  # últimos 3 para no inflar el prompt
            results_summary.append(
                f"- {tr['slug']}: {'ERROR: ' + str(tr.get('error')) if tr['is_error'] else 'OK'}"
            )
        parts.append("## Tool results anteriores\n" + "\n".join(results_summary))

    # Datos ya verificados en la conversación: el agente puede usarlos sin re-consultar.
    known_facts = state.get("known_facts")
    if known_facts:
        parts.append(
            "## Datos ya verificados en esta conversación\n"
            "El agente YA tiene estos datos (de turnos anteriores); usarlos sin volver "
            "a consultar la herramienta es correcto, NO lo penalices por no reconsultar:\n"
            f"{known_facts}"
        )

    # Historial reciente del cliente (últimos 3 mensajes)
    history = state.get("conversation_history") or []
    recent = history[-3:] if len(history) > 3 else history
    if recent:
        hist_text = "\n".join(
            f"[{m.get('role', '?')}]: {str(m.get('content', ''))[:300]}"
            for m in recent
        )
        parts.append(f"## Historial reciente\n{hist_text}")

    return "\n\n---\n\n".join(parts)


def needs_supervision(state: AgentState) -> bool:
    """Determina si la decisión actual necesita supervisión.

    Activadores:
    1. El AOP compilado tiene require_supervision=true.
    2. La tool pendiente es L2 o L3.
    No supervisar L1 ni decisiones puras de respond/escalate sin tools.
    """
    # No supervisar si ya se reintentó (para evitar loop infinito)
    if state.get("supervisor_retried"):
        return False

    # Supervisión pedida por el AOP compilado (require_supervision=true), propagada por
    # select_aop. Activa el supervisor también en respuestas/flujos sin tool L2/L3.
    if state.get("aop_require_supervision"):
        return True

    # Revisar require_supervision en el config del AOP (via tenant_config.extra o system_prompt)
    tenant_config = state.get("tenant_config") or {}
    extra = tenant_config.get("extra") or {}
    if extra.get("require_supervision"):
        return True

    # Revisar tier de la tool pendiente
    pending = state.get("pending_tool_call")
    if pending:
        slug = pending.get("slug", "")
        try:
            skill_cls = SkillRegistry.get(slug)
            if skill_cls.tier in ("L2", "L3"):
                return True
        except ValueError:
            pass

    return False


def make_supervise_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    tracker = deps.reasoning_tracker

    @guarded(name="supervise")
    async def _node(state: AgentState) -> dict[str, Any]:
        model = _select_supervisor_model(state)
        supervisor_prompt = _build_supervisor_prompt(state)

        # Emitir evento de inicio de supervisión
        conv_id = state.get("conversation_id")
        tenant_id = state.get("tenant_id")
        if conv_id and tenant_id:
            tracker.emit(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                phase="supervisor",
                event_type="check",
                label=f"Supervisor ({model.split('-')[1]})",
                detail={"model": model},
                status="pending",
            )

        response = await call_claude_with_tools(
            client=deps.anthropic,
            model=model,
            system=_SUPERVISOR_SYSTEM,
            messages=[{"role": "user", "content": supervisor_prompt}],
            tools=[SUPERVISOR_VERDICT_TOOL],
            tool_choice={"type": "tool", "name": "supervisor_verdict"},
            max_tokens=512,
            max_retries=deps.settings.llm_max_retries,
            timeout_seconds=deps.settings.llm_timeout_seconds,
        )

        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block is None:
            return {"error": "supervisor_did_not_use_tool"}

        inp = tool_block.input
        verdict = inp.get("verdict", "reject")
        reject_kind = inp.get("reject_kind", "structural")
        reason = inp.get("reason", "")
        guardrails_violated = inp.get("guardrails_violated", [])

        # Acumular tokens del supervisor
        prev_sup_in: int = state.get("supervisor_tokens_in", 0)
        prev_sup_out: int = state.get("supervisor_tokens_out", 0)
        this_in = response.usage.input_tokens
        this_out = response.usage.output_tokens

        # También acumular al costo total de la conversación
        sup_cost = compute_llm_cost(model, this_in, this_out)
        prev_cost: float = state.get("cost_usd", 0.0)

        # Emitir resultado de supervisión
        if conv_id and tenant_id:
            tracker.emit(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                phase="supervisor",
                event_type="check",
                label=f"Supervisor: {verdict}",
                detail={
                    "verdict": verdict,
                    "reject_kind": reject_kind,
                    "reason": reason,
                    "guardrails_violated": guardrails_violated,
                },
                status="done" if verdict == "approve" else "error",
            )

        result: dict[str, Any] = {
            "supervisor_verdict": verdict,
            "supervisor_reason": reason,
            "supervisor_reject_kind": reject_kind if verdict == "reject" else "n/a",
            "supervisor_model_used": model,
            "supervisor_tokens_in": prev_sup_in + this_in,
            "supervisor_tokens_out": prev_sup_out + this_out,
            "cost_usd": prev_cost + sup_cost,
        }

        if verdict == "reject":
            # Si fue tactical y no se ha reintentado → el grafo va a reason con feedback
            if reject_kind == "tactical" and not state.get("supervisor_retried"):
                result["supervisor_retried"] = True
                # Inyectar feedback del supervisor en el state para que reason lo vea
                result["system_prompt"] = (
                    state.get("system_prompt", "")
                    + f"\n\n## Feedback del supervisor (corrección requerida)\n{reason}"
                )
            else:
                # structural o segundo rechazo → escalar
                result["escalation_reason"] = (
                    f"supervisor_rejected ({reject_kind}): {reason}"
                )

        return result

    return _node
