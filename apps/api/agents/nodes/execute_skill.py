"""Nodo: execute_skill — ejecuta una skill solicitada por `reason`.

Lee `pending_tool_call` del state, resuelve la clase Skill del registry,
valida input contra el schema Pydantic y ejecuta. El resultado (éxito o
error operacional) se appendea a `tool_results` para que `reason` lo vea
en la siguiente iteración del loop ReAct.

Errores "operacionales" — skill no permitida por el AOP, slug inexistente,
input mal formado, skill que lanza — NO rompen el grafo. Se registran como
entry con `is_error=True` y el LLM decide qué hacer (reintentar con otros
inputs, escalar, etc.).

Errores realmente inesperados sí se atrapan por `@guarded` y rutean a
`handle_error`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.skills.base import SkillContext
from apps.api.skills.registry import SkillRegistry
from pydantic import ValidationError

logger = logging.getLogger(__name__)


def build_skill_context(state: AgentState) -> SkillContext:
    """Construye un SkillContext a partir del state del grafo.

    Las credenciales de integración (Shopify, etc.) se leen de
    `tenant_config.extra`. Si no existen, el SkillContext queda con
    `None` y las skills correspondientes lanzarán `shopify_not_configured`
    al ejecutar — que cae al catch de abajo y se reporta como tool_result.
    """
    tenant_config: dict[str, Any] = state.get("tenant_config", {})
    extra: dict[str, Any] = tenant_config.get("extra") or {}
    return SkillContext(
        tenant_id=state["tenant_id"],
        conversation_id=state["conversation_id"],
        shopify_domain=extra.get("shopify_domain"),
        shopify_token=extra.get("shopify_token"),
    )


def _error_entry(
    *,
    tool_use_id: str,
    slug: str,
    raw_input: dict[str, Any],
    error: str,
) -> dict[str, Any]:
    return {
        "id": tool_use_id,
        "slug": slug,
        "input": raw_input,
        "output": None,
        "is_error": True,
        "error": error,
    }


def make_execute_skill_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    tracker = deps.reasoning_tracker

    @guarded(name="execute_skill")
    async def _node(state: AgentState) -> dict[str, Any]:
        pending = state.get("pending_tool_call")
        if not pending:
            return {"error": "execute_skill_no_pending_call"}

        tool_use_id: str = pending["id"]
        slug: str = pending["slug"]
        raw_input: dict[str, Any] = pending.get("input", {})

        existing_results: list[dict[str, Any]] = list(state.get("tool_results", []))
        iter_count: int = state.get("tool_iterations", 0)
        max_iter: int = state.get("max_tool_iterations") or 5

        def _append_and_finish(entry: dict[str, Any]) -> dict[str, Any]:
            new_iter = iter_count + 1
            result: dict[str, Any] = {
                "tool_results": [*existing_results, entry],
                "pending_tool_call": None,
                "tool_iterations": new_iter,
            }
            # Si el routing va a hit el límite, dejamos lista la escalation_reason
            # para que el nodo `escalate` tenga contexto.
            if new_iter >= max_iter:
                result["escalation_reason"] = (
                    f"max_tool_iterations_exceeded ({new_iter}/{max_iter})"
                )
            return result

        # 1) Skill permitida por el AOP (lista vacía = ninguna, fail-safe).
        allowed = state.get("allowed_skills") or []
        if slug not in allowed:
            return _append_and_finish(
                _error_entry(
                    tool_use_id=tool_use_id,
                    slug=slug,
                    raw_input=raw_input,
                    error=f"skill_not_allowed: {slug}",
                )
            )

        # 2) Resolver clase del registry.
        try:
            skill_cls = SkillRegistry.get(slug)
        except ValueError:
            return _append_and_finish(
                _error_entry(
                    tool_use_id=tool_use_id,
                    slug=slug,
                    raw_input=raw_input,
                    error=f"unknown_skill: {slug}",
                )
            )

        # 3) Validar input contra el schema de la skill.
        try:
            validated_input = skill_cls.input_schema.model_validate(raw_input)
        except ValidationError as exc:
            return _append_and_finish(
                _error_entry(
                    tool_use_id=tool_use_id,
                    slug=slug,
                    raw_input=raw_input,
                    error=f"invalid_input: {exc.errors()}",
                )
            )

        # 4) Ejecutar.
        ctx = build_skill_context(state)
        skill = skill_cls()
        try:
            output = await skill.execute(ctx, validated_input)
        except Exception as exc:
            logger.warning(
                "skill_execution_failed",
                extra={
                    "tenant_id": state.get("tenant_id"),
                    "conversation_id": state.get("conversation_id"),
                    "slug": slug,
                    "error_type": type(exc).__name__,
                },
            )
            error_msg = f"skill_failed: {type(exc).__name__}: {exc!s}"
            if state.get("conversation_id") and state.get("tenant_id"):
                tracker.emit(
                    tenant_id=state["tenant_id"],
                    conversation_id=state["conversation_id"],
                    phase="decision",
                    event_type="tool_result",
                    label=slug,
                    detail={"error": error_msg},
                    status="error",
                )
            return _append_and_finish(
                _error_entry(
                    tool_use_id=tool_use_id,
                    slug=slug,
                    raw_input=raw_input,
                    error=error_msg,
                )
            )

        # 5) Éxito.
        result_entry = {
            "id": tool_use_id,
            "slug": slug,
            "input": raw_input,
            "output": output.model_dump(mode="json"),
            "is_error": False,
            "error": None,
        }
        if state.get("conversation_id") and state.get("tenant_id"):
            tracker.emit(
                tenant_id=state["tenant_id"],
                conversation_id=state["conversation_id"],
                phase="decision",
                event_type="tool_result",
                label=slug,
                detail={"output": result_entry["output"]},
                status="done",
            )
        return _append_and_finish(result_entry)

    return _node
