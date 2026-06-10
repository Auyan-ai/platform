"""Nodo: select_aop — clasifica el intent del cliente y selecciona el AOP apropiado.

Flujo:
1. Carga el catálogo de AOPs activos del tenant desde DB (con cache) + el AOP del
   turno anterior desde intent_classifier_runs (continuidad entre turnos).
2. Si el catálogo está vacío (tenant sin AOPs), devuelve {} — degradación elegante
   al sistema de prompts legacy.
3. Llama a Haiku con tool forzado para clasificar intent → top-2 candidatos,
   informándole del AOP previo para que juzgue continuidad vs. pivote.
4. Routing continuity-aware con histéresis (ver _resolve_aop_slug):
   - mismo AOP que el previo → continúa.
   - saliendo de 'default' → basta intent_min_confidence.
   - cambio a otro AOP → exige intent_switch_threshold (anti-flapping).
   - primer turno → fallback a 'default' si confidence baja.
5. Carga el AOP seleccionado, lo compila (sin KB — reason lo añadirá), actualiza state.
6. Persiste la ejecución en intent_classifier_runs para auditoría.

El grafo no usa checkpointer: el state se arma desde cero cada turno, así que el AOP
previo se recupera de DB, no del state. Por eso el clasificador corre cada turno, pero
informado del contexto previo (no ciego).
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
from apps.api.db.queries import (
    get_last_intent_for_conversation,
    insert_intent_classifier_run,
)
from apps.api.integrations.anthropic_client import call_claude_with_tools
from pydantic import BaseModel, Field, ValidationError

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
- Si se indica un "Procedimiento del turno anterior", trátalo como el contexto activo:
  mantenlo salvo que el mensaje muestre un cambio de tema claro. Si el cliente continúa o
  profundiza el mismo tema, devuelve ESE mismo slug con confianza alta. Solo cambia de
  procedimiento (y dale confianza alta) cuando el pivote sea inequívoco; ante mensajes
  cortos o ambiguos, prefiere mantener el procedimiento previo con confianza moderada.
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
    # Con default: Haiku a veces los omite aunque el tool schema los marque
    # required, y la metadata faltante no invalida una clasificación con
    # primary válido (incidente staging 2026-06-10).
    reasoning: str = ""
    ambiguity_detected: bool = False


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _resolve_aop_slug(
    *,
    primary_slug: str,
    primary_confidence: float,
    previous_slug: str | None,
    valid_slugs: set[str],
    min_confidence: float,
    switch_threshold: float,
) -> str:
    """Decide el AOP final aplicando continuidad + histéresis anti-flapping.

    - Primer turno (sin previo válido): fallback a 'default' si confidence < min o slug inválido.
    - Continuidad: si el clasificador devuelve el mismo AOP previo, se mantiene.
    - Salir de 'default': basta min_confidence (default no es un procedimiento con hilo
      que proteger, así que aclarar el intent no debe penalizarse).
    - Cambiar entre AOPs reales: exige switch_threshold (≥ min). Por debajo, gana la
      continuidad y se mantiene el AOP previo → evita flapping mid-procedimiento en
      mensajes cortos/ambiguos ("el azul", "12345").
    """
    slug_is_valid = primary_slug in valid_slugs

    # Primer turno o el AOP previo ya no está activo → lógica de fallback original.
    if previous_slug is None or previous_slug not in valid_slugs:
        if primary_confidence < min_confidence or not slug_is_valid:
            return "default"
        return primary_slug

    # Mismo AOP que el previo → continuidad, se mantiene aunque la confianza sea baja.
    if primary_slug == previous_slug:
        return previous_slug

    # Saliendo de 'default': basta la confianza mínima normal.
    if previous_slug == "default" and slug_is_valid and primary_confidence >= min_confidence:
        return primary_slug

    # Cambio entre AOPs reales: solo si el pivote es confiable.
    if slug_is_valid and primary_confidence >= switch_threshold:
        return primary_slug

    # Anti-flapping: confianza insuficiente para cambiar → mantener el previo.
    return previous_slug


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
        tenant_id = UUID(state["tenant_id"])

        # Modo simulación con AOP forzado: carga el AOP directamente, sin llamar al
        # intent classifier (Haiku). Permite que los scenarios del simulator controlen
        # qué AOP activa el grafo, aislando el test del clasificador de intent.
        forced_aop = state.get("forced_aop_slug")
        if forced_aop and state.get("simulation_mode"):
            async with tenant_scope(tenant_id) as conn:
                selected_aop = await load_aop(conn, tenant_id, forced_aop)
                if selected_aop is None:
                    logger.warning(
                        "select_aop.forced_aop_not_found tenant_id=%s slug=%s",
                        tenant_id,
                        forced_aop,
                    )
                    return {}
                tenant_config = TenantConfiguration(**state["tenant_config"])
                compiled = compile_aop(
                    selected_aop,
                    tenant_config,
                    tenant_playbook=state.get("tenant_playbook"),
                    tenant_facts=state.get("tenant_facts"),
                )
            return {
                "aop_slug": selected_aop.slug,
                "aop_version": selected_aop.current_version,
                "aop_workspace": selected_aop.workspace,
                "intent_confidence": 1.0,
                "system_prompt": compiled.system_prompt,
                "allowed_skills": compiled.allowed_skills,
                "max_tool_iterations": compiled.max_iterations,
                "aop_confidence_threshold": compiled.confidence_threshold,
                "aop_require_supervision": compiled.require_supervision,
                "aop_steps": [
                    {"id": s.id, "name": s.name, "decision_point": s.decision_point}
                    for s in compiled.steps
                ],
            }
        conversation_id = UUID(state["conversation_id"])
        inbound = state.get("inbound_message_content", "")
        history = state.get("conversation_history") or []

        # ── 1. Cargar catálogo de AOPs activos + AOP del turno anterior ──
        async with tenant_scope(tenant_id) as conn:
            active_aops = await load_active_aops(conn, tenant_id)
            previous_slug = await get_last_intent_for_conversation(
                conn, tenant_id, conversation_id
            )

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
            f"Procedimiento del turno anterior: {previous_slug or '(ninguno)'}\n\n"
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
            try:
                parsed = _ClassifierOutput.model_validate(tool_block.input)
            except ValidationError:
                # Output malformado de verdad (sin primary, confidence fuera de
                # rango). Degradar a default igual que no_tool_block — nunca
                # propagar: el ValidationError tumbaba el turno entero por
                # agent_error y escalaba sin necesidad.
                logger.warning(
                    "select_aop.invalid_classifier_output tenant_id=%s — "
                    "falling back to default",
                    tenant_id,
                )
                parsed = _ClassifierOutput(
                    primary=_Candidate(slug="default", confidence=0.0),
                    reasoning="invalid_classifier_output",
                )

        classified_slug = parsed.primary.slug
        primary_confidence = parsed.primary.confidence
        alt = parsed.alternative

        # ── 4. Routing continuity-aware con histéresis anti-flapping ─────
        primary_slug = _resolve_aop_slug(
            primary_slug=classified_slug,
            primary_confidence=primary_confidence,
            previous_slug=previous_slug,
            valid_slugs={a.slug for a in active_aops},
            min_confidence=deps.settings.intent_min_confidence,
            switch_threshold=deps.settings.intent_switch_threshold,
        )
        if primary_slug != classified_slug:
            logger.info(
                "select_aop.routing tenant_id=%s classified=%s conf=%.2f previous=%s "
                "→ chosen=%s",
                tenant_id,
                classified_slug,
                primary_confidence,
                previous_slug,
                primary_slug,
            )

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
            compiled = compile_aop(
                selected_aop,
                tenant_config,
                tenant_playbook=state.get("tenant_playbook"),
                tenant_facts=state.get("tenant_facts"),
            )

            # ── 6. Persistir ejecución del clasificador ──────────────────
            # was_reclassification: hubo un AOP en un turno previo de esta conversación
            # (no es el primer turno). El state no persiste, así que se infiere de DB.
            turn_number = _turn_number(state)
            was_reclassification = previous_slug is not None
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
            "aop_confidence_threshold": compiled.confidence_threshold,
            "aop_require_supervision": compiled.require_supervision,
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
