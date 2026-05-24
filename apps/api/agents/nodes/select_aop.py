"""Nodo: select_aop — clasifica el intent del cliente y selecciona el AOP apropiado.

Flujo:
1. Si el AOP ya está seleccionado y locked, devuelve {} (sin reclasificar).
2. Carga el catálogo de AOPs activos del tenant desde DB (con cache).
3. Si el catálogo está vacío (tenant sin AOPs), devuelve {} — degradación elegante
   al sistema de prompts legacy.
4. Llama a Haiku con tool forzado para clasificar intent → top-2 candidatos.
5. Si confidence < intent_min_confidence, usa AOP 'default'.
6. Carga el AOP seleccionado, lo compila (sin KB — reason lo añadirá), actualiza state.
7. Persiste la ejecución en intent_classifier_runs para auditoría.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.aops.compiler import compile_aop, load_active_aops, load_aop
from apps.api.db.client import tenant_scope
from apps.api.db.models import TenantConfiguration
from apps.api.db.queries import insert_intent_classifier_run
from apps.api.integrations.anthropic_client import call_claude_with_tools
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ─── Tool definition del clasificador ───────────────────────────────────────

SELECT_AOP_TOOL: dict = {
    "name": "select_aop",
    "description": "Selecciona el procedimiento más apropiado para el mensaje del cliente.",
    "input_schema": {
        "type": "object",
        "properties": {
            "primary": {
                "type": "object",
                "description": "El procedimiento más probable.",
                "properties": {
                    "slug": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["slug", "confidence"],
            },
            "alternative": {
                "type": "object",
                "description": "Segundo candidato más probable. Omitir si no hay duda razonable.",
                "properties": {
                    "slug": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["slug", "confidence"],
            },
            "reasoning": {
                "type": "string",
                "description": "Por qué elegiste el primary en 1-2 frases.",
            },
            "ambiguity_detected": {
                "type": "boolean",
                "description": (
                    "True si el mensaje contiene múltiples intents claramente distintos."
                ),
            },
        },
        "required": ["primary", "reasoning", "ambiguity_detected"],
    },
}

INTENT_CLASSIFIER_PROMPT = """\
Eres un clasificador de intent para un agente de soporte al cliente.

Tu única tarea es analizar el mensaje del cliente (y el historial reciente si lo hay)
y seleccionar el procedimiento (AOP) más apropiado del catálogo disponible.

Reglas:
- Sé conservador: si no hay evidencia clara de cuál AOP aplica, usa el slug "default".
- Considera el historial para detectar si el cliente cambió de tema.
- Si el mensaje contiene múltiples intents distintos, márcalo con ambiguity_detected=true.
- NO inventes slugs que no estén en el catálogo.
"""


# ─── Pydantic models para parsear la respuesta ──────────────────────────────


class _Candidate(BaseModel):
    slug: str
    confidence: float = Field(ge=0.0, le=1.0)


class _ClassifierOutput(BaseModel):
    primary: _Candidate
    alternative: _Candidate | None = None
    reasoning: str
    ambiguity_detected: bool


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _should_reclassify(state: AgentState) -> bool:
    """True si hay que correr el clasificador en este turno.

    Reglas para Sprint 7:
    - Sin AOP previo (primer turno) → clasificar.
    - AOP locked hasta cierto turno → no clasificar.
    - AOP marcado como completado → clasificar.
    - Cualquier otro caso → no reclasificar (mantener AOP del turno anterior).
    """
    if not state.get("aop_slug"):
        return True

    if state.get("aop_completed_signal"):
        return True

    locked_until = state.get("aop_locked_until_turn")
    if locked_until:
        history = state.get("conversation_history") or []
        current_turn = sum(1 for m in history if m.get("role") == "customer")
        if current_turn < locked_until:
            return False
        return True  # lock expiró → reclasificar

    return False


def _format_history(messages: list[dict]) -> str:
    if not messages:
        return "(sin historial previo)"
    role_labels = {
        "customer": "Cliente",
        "agent_ai": "Agente",
        "agent_human": "Agente humano",
    }
    lines = []
    for m in messages[-3:]:
        role = role_labels.get(m.get("role", ""), "Sistema")
        content = (m.get("content") or "")[:200]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _turn_number(state: AgentState) -> int:
    history = state.get("conversation_history") or []
    return sum(1 for m in history if m.get("role") == "customer")


# ─── Factory ─────────────────────────────────────────────────────────────────


def make_select_aop_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    @guarded(name="select_aop")
    async def _node(state: AgentState) -> dict:
        if not _should_reclassify(state):
            return {}

        tenant_id = UUID(state["tenant_id"])
        conversation_id = UUID(state["conversation_id"])
        inbound = state.get("inbound_message_content", "")
        history = state.get("conversation_history") or []

        # ── 1. Cargar catálogo de AOPs activos ───────────────────────────
        async with tenant_scope(tenant_id) as conn:
            active_aops = await load_active_aops(conn, tenant_id)

        if not active_aops:
            logger.info(
                "select_aop.no_aops_configured tenant_id=%s — using legacy prompt",
                tenant_id,
            )
            return {}

        catalog = [
            {
                "slug": a.slug,
                "name": a.yaml_frontmatter.get("name", a.slug),
                "description": (a.yaml_frontmatter.get("triggers") or {}).get(
                    "description", ""
                ),
            }
            for a in active_aops
        ]

        # ── 2. Llamar a Haiku para clasificar intent ─────────────────────
        catalog_json = json.dumps(catalog, indent=2, ensure_ascii=False)
        user_message = (
            f"Catálogo de procedimientos disponibles:\n{catalog_json}\n\n"
            f"Mensaje del cliente:\n{inbound}\n\n"
            f"Historial reciente:\n{_format_history(history)}"
        )

        response = await call_claude_with_tools(
            client=deps.anthropic,
            model=deps.settings.intent_classifier_model,
            system=INTENT_CLASSIFIER_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            tools=[SELECT_AOP_TOOL],
            tool_choice={"type": "tool", "name": "select_aop"},
            max_tokens=512,
            max_retries=deps.settings.llm_max_retries,
            timeout_seconds=deps.settings.llm_timeout_seconds,
        )

        # ── 3. Parsear respuesta del clasificador ────────────────────────
        tool_block = next(
            (b for b in response.content if getattr(b, "type", None) == "tool_use"),
            None,
        )
        if tool_block is None:
            logger.warning(
                "select_aop.no_tool_block tenant_id=%s — falling back to default", tenant_id
            )
            parsed = _ClassifierOutput(
                primary=_Candidate(slug="default", confidence=0.0),
                reasoning="no_tool_block",
                ambiguity_detected=False,
            )
        else:
            parsed = _ClassifierOutput.model_validate(tool_block.input)

        primary_slug = parsed.primary.slug
        primary_confidence = parsed.primary.confidence
        alt = parsed.alternative

        # ── 4. Fallback a 'default' si confidence baja ───────────────────
        min_conf = deps.settings.intent_min_confidence
        if primary_confidence < min_conf or primary_slug not in {a.slug for a in active_aops}:
            if primary_confidence < min_conf:
                logger.info(
                    "select_aop.low_confidence tenant_id=%s slug=%s conf=%.2f — default",
                    tenant_id,
                    primary_slug,
                    primary_confidence,
                )
            else:
                logger.warning(
                    "select_aop.unknown_slug tenant_id=%s slug=%s — using default",
                    tenant_id,
                    primary_slug,
                )
            primary_slug = "default"

        # ── 5. Cargar AOP seleccionado y compilar ────────────────────────
        async with tenant_scope(tenant_id) as conn:
            selected_aop = await load_aop(conn, tenant_id, primary_slug)
            if selected_aop is None and primary_slug != "default":
                selected_aop = await load_aop(conn, tenant_id, "default")
            if selected_aop is None:
                logger.warning(
                    "select_aop.aop_not_found tenant_id=%s slug=%s — using legacy prompt",
                    tenant_id,
                    primary_slug,
                )
                return {}

            tenant_config = TenantConfiguration(**state["tenant_config"])
            compiled = compile_aop(selected_aop, tenant_config)

            # ── 6. Persistir ejecución del clasificador ──────────────────
            turn_number = _turn_number(state)
            was_reclassification = bool(state.get("aop_slug"))
            await insert_intent_classifier_run(
                conn,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                turn_number=turn_number,
                primary_slug=primary_slug,
                primary_confidence=primary_confidence,
                alternative_slug=alt.slug if alt else None,
                alternative_confidence=alt.confidence if alt else None,
                ambiguity_detected=parsed.ambiguity_detected,
                was_reclassification=was_reclassification,
            )

        out: dict = {
            "aop_slug": selected_aop.slug,
            "aop_version": selected_aop.current_version,
            "aop_workspace": selected_aop.workspace,
            "intent_confidence": primary_confidence,
            "system_prompt": compiled.system_prompt,
            "allowed_skills": compiled.allowed_skills,
            "max_tool_iterations": compiled.max_iterations,
            "aop_steps": [
                {"id": s.id, "name": s.name, "decision_point": s.decision_point}
                for s in compiled.steps
            ],
        }

        # Señal de multi-intent: persistir el slug alternativo para el próximo turno.
        if parsed.ambiguity_detected and alt and alt.confidence >= 0.60:
            out["pending_intent"] = alt.slug

        return out

    return _node
