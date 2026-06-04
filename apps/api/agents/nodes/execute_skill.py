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
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import create_pending_approval, get_recent_approval_for_skill
from apps.api.integrations.base import IntegrationContext
from apps.api.services.pii import redact_inputs
from apps.api.skills.base import SkillContext
from apps.api.skills.registry import SkillRegistry
from pydantic import ValidationError

logger = logging.getLogger(__name__)


def build_skill_context(state: AgentState) -> SkillContext:
    """Construye un SkillContext a partir del state del grafo.

    La integración commerce (Shopify) se carga desde `commerce_integration_ctx`
    que load_tenant_context pre-computa — primero desde tenant_integrations DB,
    fallback a tenant_config.extra para tenants no migrados.
    """
    commerce_data: dict[str, Any] | None = state.get("commerce_integration_ctx")
    integration_ctx: IntegrationContext | None = None
    if commerce_data:
        from uuid import UUID as _UUID
        integration_ctx = IntegrationContext(
            tenant_id=_UUID(commerce_data["tenant_id"]),
            credentials=commerce_data["credentials"],
            config=commerce_data.get("config", {}),
        )

    # En modo simulación, inyectamos un mock de commerce con respuestas predefinidas.
    commerce_mock: Any = None
    if state.get("simulation_mode"):
        from apps.api.simulator.mocks import MockShopifyAdapter
        shopify_fixtures = (state.get("simulation_fixtures") or {}).get("shopify", {})
        commerce_mock = MockShopifyAdapter(shopify_fixtures)

    return SkillContext(
        tenant_id=state["tenant_id"],
        conversation_id=state["conversation_id"],
        integration_ctx=integration_ctx,
        commerce_mock=commerce_mock,
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


def _same_order_action(existing_inputs: dict, new_inputs: dict) -> bool:
    """¿El nuevo tool call es la MISMA acción que un approval previo?

    Compara los inputs ignorando 'order_id': el mismo pedido puede llegar como
    número visible (1278) o como id interno (7133911154968) según el turno, así
    que comparar order_id crudo daría falsos negativos. El resto de campos (p.ej.
    la dirección nueva) sí distingue un re-disparo espurio de un cambio distinto.
    """
    a = {k: v for k, v in (existing_inputs or {}).items() if k != "order_id"}
    b = {k: v for k, v in (new_inputs or {}).items() if k != "order_id"}
    return a == b


def make_execute_skill_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    tracker = deps.reasoning_tracker
    auditor = deps.audit_logger

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

        # 3) Gate de permisos desde tenant_tool_permissions.
        #    Si la skill no tiene row o is_enabled=False → rechazada.
        #    Si L3 + human_approval_required → crear pending_approval y escalar.
        tool_permissions: dict[str, Any] = state.get("tool_permissions") or {}
        perm = tool_permissions.get(slug)

        if perm is None or not perm.get("is_enabled", False):
            tier_error = f"skill_not_enabled_for_tenant: {slug}"
            if state.get("conversation_id") and state.get("tenant_id"):
                auditor.log(
                    tenant_id=state["tenant_id"],
                    conversation_id=state["conversation_id"],
                    aop_slug=state.get("aop_slug") or "unknown",
                    aop_version=state.get("aop_version") or 0,
                    skill_slug=slug,
                    skill_tier=skill_cls.tier,
                    inputs_raw=raw_input,
                    status="rejected_by_permissions",
                    error_message=tier_error,
                    langfuse_trace_id=state.get("langfuse_trace_id"),
                )
            return _append_and_finish(
                _error_entry(
                    tool_use_id=tool_use_id,
                    slug=slug,
                    raw_input=raw_input,
                    error=tier_error,
                )
            )

        # Skill L3 + human_approval_required → crear pending_approval y pausar.
        if skill_cls.tier == "L3" and perm.get("human_approval_required", False):
            if state.get("conversation_id") and state.get("tenant_id"):
                approval_id = uuid4()
                tenant_id_uuid = UUID(state["tenant_id"])
                conv_id_uuid = UUID(state["conversation_id"])
                # is_repeat: ya existe una aprobación para esta MISMA acción —el
                # cliente reescribió mientras seguía en revisión (pending) o tras
                # aprobarse (approved)— así que la reusamos en vez de duplicarla.
                is_repeat = False
                try:
                    # Obtener salt para redactar PII — usamos tenant_scope directamente.
                    from apps.api.db.queries import get_tenant_pii_salt
                    async with tenant_scope(tenant_id_uuid) as conn:
                        # Idempotencia del gate L3: si ya hay una aprobación reciente
                        # (pending o approved) para esta misma acción, la reusamos y
                        # no creamos un duplicado huérfano. Comparamos la acción
                        # ignorando order_id (visible vs interno = mismo pedido).
                        existing = await get_recent_approval_for_skill(
                            conn, tenant_id_uuid, conv_id_uuid, slug
                        )
                        if existing is not None and _same_order_action(
                            existing.inputs_raw, raw_input
                        ):
                            approval_id = existing.id
                            is_repeat = True
                        else:
                            salt = await get_tenant_pii_salt(conn, tenant_id_uuid)
                            inputs_redacted = redact_inputs(raw_input, salt)
                            await create_pending_approval(
                                conn,
                                approval_id=approval_id,
                                tenant_id=tenant_id_uuid,
                                conversation_id=conv_id_uuid,
                                skill_slug=slug,
                                skill_tier=skill_cls.tier,
                                inputs_raw=raw_input,
                                inputs_redacted=inputs_redacted,
                                aop_slug=state.get("aop_slug") or "unknown",
                                aop_version=state.get("aop_version") or 0,
                                langfuse_trace_id=state.get("langfuse_trace_id"),
                            )
                except Exception:
                    logger.exception("pending_approval_create_failed slug=%s", slug)
                    # Si falla la creación del pending_approval, escalamos igual.

                auditor.log(
                    tenant_id=state["tenant_id"],
                    conversation_id=state["conversation_id"],
                    aop_slug=state.get("aop_slug") or "unknown",
                    aop_version=state.get("aop_version") or 0,
                    skill_slug=slug,
                    skill_tier=skill_cls.tier,
                    inputs_raw=raw_input,
                    status="rejected_by_permissions",
                    error_message="awaiting_human_approval",
                    langfuse_trace_id=state.get("langfuse_trace_id"),
                )
                tracker.emit(
                    tenant_id=state["tenant_id"],
                    conversation_id=state["conversation_id"],
                    phase="decision",
                    event_type="tool_result",
                    label=slug,
                    detail={"approval_id": str(approval_id), "status": "awaiting_human_approval"},
                    status="pending",
                )

                # Devolver señal especial al state — route_after_execute_skill
                # detecta pending_approval_id y rutea a escalate.
                new_iter = iter_count + 1
                return {
                    "tool_results": [
                        *existing_results,
                        {
                            "id": tool_use_id,
                            "slug": slug,
                            "input": raw_input,
                            "output": None,
                            "is_error": False,
                            "error": None,
                            "awaiting_approval": True,
                        },
                    ],
                    "pending_tool_call": None,
                    "tool_iterations": new_iter,
                    "pending_approval_id": str(approval_id),
                    "pending_approval_skill_slug": slug,
                    "pending_approval_is_repeat": is_repeat,
                    "escalation_reason": f"awaiting_human_approval:{approval_id}",
                }
            # Sin tenant/conversation en state (no debería pasar en prod) → error.
            return _append_and_finish(
                _error_entry(
                    tool_use_id=tool_use_id,
                    slug=slug,
                    raw_input=raw_input,
                    error="l3_approval_required_but_missing_context",
                )
            )

        # 4) Validar input contra el schema de la skill.
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

        # 5) Ejecutar con tracking de latencia.
        ctx = build_skill_context(state)
        skill = skill_cls()
        t0 = time.monotonic()
        try:
            output = await skill.execute(ctx, validated_input)
        except Exception as exc:
            latency = int((time.monotonic() - t0) * 1000)
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
                auditor.log(
                    tenant_id=state["tenant_id"],
                    conversation_id=state["conversation_id"],
                    aop_slug=state.get("aop_slug") or "unknown",
                    aop_version=state.get("aop_version") or 0,
                    skill_slug=slug,
                    skill_tier=skill_cls.tier,
                    inputs_raw=raw_input,
                    status="failed",
                    error_message=error_msg,
                    latency_ms=latency,
                    langfuse_trace_id=state.get("langfuse_trace_id"),
                )
            return _append_and_finish(
                _error_entry(
                    tool_use_id=tool_use_id,
                    slug=slug,
                    raw_input=raw_input,
                    error=error_msg,
                )
            )

        # 6) Éxito.
        latency = int((time.monotonic() - t0) * 1000)
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
            auditor.log(
                tenant_id=state["tenant_id"],
                conversation_id=state["conversation_id"],
                aop_slug=state.get("aop_slug") or "unknown",
                aop_version=state.get("aop_version") or 0,
                skill_slug=slug,
                skill_tier=skill_cls.tier,
                inputs_raw=raw_input,
                status="success",
                outputs=result_entry["output"],
                latency_ms=latency,
                langfuse_trace_id=state.get("langfuse_trace_id"),
            )
        return _append_and_finish(result_entry)

    return _node
