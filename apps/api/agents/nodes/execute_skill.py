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
from apps.api.services.channel_routing import is_messaging_channel
from apps.api.services.identity import (
    Grant,
    IdentityContext,
    default_phone_region,
    evidence_from_state,
    identity_note,
)
from apps.api.services.identity_guest import (
    OrderLookupError,
    guest_facts,
    guest_policy,
    lookup_order,
)
from apps.api.services.pii import redact_inputs
from apps.api.services.skill_access import IdentityVerdict, identity_verdict
from apps.api.skills.base import Skill, SkillContext, SkillRefusal
from apps.api.skills.identity.check_order_contact import CheckOrderContactOutput
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

    # Solo cuenta el contacto que el origen del mensaje verifica (ADR 0013): lo escribió el
    # intake en `identity_evidence`. Un email de chat lo teclea el visitante.
    evidence = evidence_from_state(state)

    return SkillContext(
        tenant_id=state["tenant_id"],
        conversation_id=state["conversation_id"],
        integration_ctx=integration_ctx,
        commerce_mock=commerce_mock,
        customer_email=evidence.email,
        customer_phone=evidence.phone,
        identity=IdentityContext.from_state(state.get("identity")),
        claim_salt=state.get("claim_salt") or "",
        channel=state.get("channel"),
        phone_region=default_phone_region(state.get("tenant_config"), state.get("tenant_facts")),
        guest_policy=guest_policy(state.get("tenant_config")),
        tenant_facts=dict(state.get("tenant_facts") or {}),
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


def _normalize_order_ref(value: Any) -> str | None:
    """Normaliza una referencia de pedido a string comparable ('#1278' → '1278')."""
    if value is None:
        return None
    return str(value).strip().lstrip("#")


async def _refs_point_to_same_order(state: AgentState, ref_a: str, ref_b: str) -> bool:
    """Resuelve dos referencias de pedido al id interno vía el adapter de commerce
    (igual que las skills de mutación: visible 1278 ↔ interno 7133911154968).

    Si no hay integración commerce o la resolución falla, fail-safe → False:
    duplicar una aprobación es inocuo; tragarse una acción sobre OTRO pedido no.
    """
    ctx = build_skill_context(state)
    adapter: Any = ctx.commerce_mock
    if adapter is None:
        if ctx.integration_ctx is None:
            return False
        from apps.api.integrations.shopify import ShopifyAdapter

        adapter = ShopifyAdapter()

    async def _to_internal(ref: str) -> int:
        found = await adapter.get_order_by_name(ctx.integration_ctx, ref)
        if found and found.get("id"):
            return int(found["id"])
        return int(ref)

    try:
        return await _to_internal(ref_a) == await _to_internal(ref_b)
    except Exception:
        logger.warning("order_ref_resolution_failed refs=(%s, %s)", ref_a, ref_b)
        return False


async def _same_order_action(state: AgentState, existing_inputs: dict, new_inputs: dict) -> bool:
    """¿El nuevo tool call es la MISMA acción que un approval previo?

    Los campos que no son order_id deben coincidir exactamente (p.ej. la
    dirección nueva distingue un re-disparo espurio de un cambio distinto).
    El order_id se compara aparte: el mismo pedido puede llegar como número
    visible (1278) o como id interno (7133911154968) según el turno, así que
    si los refs difieren textualmente se resuelven ambos al id interno antes
    de decidir — ignorarlo se tragaba una acción L3 sobre OTRO pedido cuando
    el resto de inputs coincidía (auditoría sesión 67).
    """
    a = {k: v for k, v in (existing_inputs or {}).items() if k != "order_id"}
    b = {k: v for k, v in (new_inputs or {}).items() if k != "order_id"}
    if a != b:
        return False

    ref_a = _normalize_order_ref((existing_inputs or {}).get("order_id"))
    ref_b = _normalize_order_ref((new_inputs or {}).get("order_id"))
    if ref_a == ref_b:
        return True
    if ref_a is None or ref_b is None:
        return False
    return await _refs_point_to_same_order(state, ref_a, ref_b)


_IDENTITY_REQUIRED_ERROR = (
    "identity_required: por seguridad, un pedido solo se consulta o se modifica si el cliente "
    "escribe desde el email de la compra o da el número de pedido junto con el email o "
    "teléfono de esa compra. Pídele el dato que falte con amabilidad, o que escriba desde "
    "el email de la compra. No reintentes la acción ni reveles el email del pedido."
)
# Canales de mensajería (WhatsApp): no hay email; el teléfono no coincide o no llega.
_IDENTITY_REQUIRED_ERROR_MESSAGING = (
    "identity_required: por seguridad no puedo verificar que el pedido sea del cliente "
    "desde este número de teléfono. Pídele con amabilidad el número de pedido junto con el "
    "email o teléfono de la compra, u ofrécele pasar el caso a una persona del equipo. No "
    "reintentes la acción ni reveles los datos de contacto del pedido."
)
_VERIFIED_REQUIRED_ERROR = (
    "verified_required: esta acción solo se puede pedir desde el email o el teléfono con "
    "el que se hizo la compra. Explícaselo con amabilidad y ofrécele pasar el caso a una "
    "persona del equipo. No reintentes la acción ni reveles los datos del pedido."
)


async def _resolve_order(ctx: SkillContext, order_ref: str) -> dict[str, Any] | None:
    """El pedido de la referencia vía el adapter de commerce, o None (fail-closed)."""
    try:
        return await lookup_order(ctx, order_ref)
    except OrderLookupError:
        logger.warning("identity_gate_order_resolution_failed ref=%s", order_ref)
        return None


async def _identity_gate(
    state: AgentState, skill_cls: type[Skill], raw_input: dict[str, Any]
) -> tuple[IdentityVerdict, str] | None:
    """Gate único de identidad (ADR 0013 §5), en código y para toda skill.

    Resuelve el pedido del input y compara sus claims con los grants del turno. Fail-closed:
    sin referencia, pedido no encontrado o error resolviéndolo → `identity_required`, igual
    que cuando el pedido existe pero es de otro, para no revelar cuáles existen. Devuelve
    el veredicto y el error para el LLM, o None si puede ejecutar.
    """
    if skill_cls.identity_scope == "public":
        return None
    ctx = build_skill_context(state)
    claims = None
    order_id: int | None = None
    if skill_cls.identity_scope == "order":
        order_ref = _normalize_order_ref(raw_input.get(skill_cls.order_input_field))
        order = await _resolve_order(ctx, order_ref) if order_ref is not None else None
        if order is not None:
            claims = ctx.order_claims(order)
            order_id = int(order["id"]) if order.get("id") is not None else None
    verdict = identity_verdict(skill_cls, ctx.identity, claims=claims, order_id=order_id)
    if verdict is None:
        return None
    # Nunca el teléfono ni el email en claro: solo el veredicto.
    logger.warning(
        "identity_gate_blocked",
        extra={
            "tenant_id": state.get("tenant_id"),
            "conversation_id": state.get("conversation_id"),
            "slug": skill_cls.slug,
            "verdict": verdict,
        },
    )
    if verdict == "verified_required":
        return verdict, _VERIFIED_REQUIRED_ERROR
    if ctx.channel is not None and is_messaging_channel(ctx.channel):
        return verdict, _IDENTITY_REQUIRED_ERROR_MESSAGING
    return verdict, _IDENTITY_REQUIRED_ERROR


def _identity_update(state: AgentState, output: Any) -> dict[str, Any]:
    """Efecto de `identity.check_order_contact` en el estado del turno (ADR 0013 §4).

    Si coincide, el grant `guest` entra ya en `identity`, la línea de identidad se
    recalcula y el pedido proyectado pasa a `known_facts`. Si no, el turno termina con el
    texto fijo y sin volver al LLM.
    """
    if not isinstance(output, CheckOrderContactOutput):
        return {}
    if not output.verified:
        if output.reply is None:
            return {}
        return {
            "decision": "respond",
            "agent_response": output.reply,
            "awaiting_customer_reply": True,
        }
    identity = IdentityContext.from_state(state.get("identity"))
    identity = IdentityContext(
        (
            *identity.grants,
            Grant(
                "guest",
                "order_contact",
                order_id=output.granted_order_id,
                valid_until=output.valid_until,
            ),
        )
    )
    return {
        "identity": identity.to_state(),
        "identity_summary": identity.summary(),
        "identity_note": identity_note(identity),
        "known_facts": guest_facts(state.get("known_facts"), [output.order or {}]),
    }


def _l3_requires_human_approval(skill_cls: type[Skill], perm: dict[str, Any]) -> bool:
    """Piso de seguridad para skills L3 (destructivas / irreversibles).

    Una L3 exige aprobación humana SALVO que exista un opt-out explícito y reconocido
    (`l3_autonomy_acknowledged=True`). Es fail-safe a propósito: un
    `human_approval_required=False` de descuido —el default de fábrica del schema es
    FALSE, y los seeds pueden traerlo así— NO desactiva la red de una acción que mueve
    plata o no se puede deshacer. Solo un reconocimiento consciente del riesgo lo hace.

    Razón: el supervisor LLM corre antes de ejecutar, pero su prompt lo sesga a APROBAR
    (es una red contra errores materiales, no un control determinístico), así que no
    basta como única barrera de algo irreversible.
    """
    if skill_cls.tier != "L3":
        return False
    if perm.get("human_approval_required", True):
        return True
    return not perm.get("l3_autonomy_acknowledged", False)


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

        def _append_and_finish(entry: dict[str, Any]) -> dict[str, Any]:
            # Al llegar a `max_tool_iterations`, `reason` hace un último turno forzado a decidir.
            return {
                "tool_results": [*existing_results, entry],
                "pending_tool_call": None,
                "tool_iterations": iter_count + 1,
            }

        def _escalate_refusal(
            refusal: SkillRefusal, skill_cls: type[Skill], inputs: dict[str, Any]
        ) -> dict[str, Any]:
            # Regla en código (p. ej. pedido ya enviado): el cliente recibe el texto
            # fijo de la skill y el caso va al equipo; el LLM no vuelve a decidir.
            logger.info(
                "skill_refused",
                extra={
                    "tenant_id": state.get("tenant_id"),
                    "conversation_id": state.get("conversation_id"),
                    "slug": slug,
                    "code": refusal.code,
                },
            )
            if state.get("conversation_id") and state.get("tenant_id"):
                auditor.log(
                    tenant_id=state["tenant_id"],
                    conversation_id=state["conversation_id"],
                    aop_slug=state.get("aop_slug") or "unknown",
                    aop_version=state.get("aop_version") or 0,
                    skill_slug=slug,
                    skill_tier=skill_cls.tier,
                    inputs_raw=inputs,
                    status="rejected_by_permissions",
                    error_message=f"skill_refused: {refusal.code}",
                    langfuse_trace_id=state.get("langfuse_trace_id"),
                )
                tracker.emit(
                    tenant_id=state["tenant_id"],
                    conversation_id=state["conversation_id"],
                    phase="decision",
                    event_type="tool_result",
                    label=slug,
                    detail={"refused": refusal.code, "reason": refusal.team_reason},
                    status="error",
                )
            return {
                **_append_and_finish(
                    _error_entry(
                        tool_use_id=tool_use_id,
                        slug=slug,
                        raw_input=inputs,
                        error=f"skill_refused: {refusal.code}",
                    )
                ),
                "decision": "escalate",
                "agent_response": refusal.customer_message,
                "escalation_reason": refusal.team_reason,
            }

        # 1) Skill permitida por el AOP (lista vacía = ninguna, fail-safe).
        # Las skills `core` (identidad) las ofrece el código, no el AOP ni el tenant.
        is_core = SkillRegistry.is_core(slug)
        allowed = state.get("allowed_skills") or []
        if slug not in allowed and not is_core:
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
        #    L3 → crear pending_approval y escalar, salvo opt-out reconocido.
        tool_permissions: dict[str, Any] = state.get("tool_permissions") or {}
        perm = tool_permissions.get(slug)
        if is_core:
            perm = {"is_enabled": True}

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

        # Identidad en código: el pedido que toca la skill tiene que ser de quien escribe.
        blocked = await _identity_gate(state, skill_cls, raw_input)
        if blocked is not None:
            verdict, identity_error = blocked
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
                    error_message=verdict,
                    langfuse_trace_id=state.get("langfuse_trace_id"),
                )
            return _append_and_finish(
                _error_entry(
                    tool_use_id=tool_use_id,
                    slug=slug,
                    raw_input=raw_input,
                    error=identity_error,
                )
            )

        # Piso L3: exige aprobación humana salvo opt-out explícito y reconocido.
        if _l3_requires_human_approval(skill_cls, perm):
            if state.get("conversation_id") and state.get("tenant_id"):
                # La skill valida y completa en código lo que va a aprobar el humano
                # (p. ej. refund_partial: tope reembolsable y moneda del pedido).
                try:
                    raw_input = await skill_cls().prepare_approval(
                        build_skill_context(state), raw_input
                    )
                except SkillRefusal as refusal:
                    return _escalate_refusal(refusal, skill_cls, raw_input)
                except Exception as exc:
                    precheck_error = f"approval_precheck_failed: {type(exc).__name__}: {exc!s}"
                    logger.warning(
                        "l3_approval_precheck_failed",
                        extra={
                            "tenant_id": state.get("tenant_id"),
                            "conversation_id": state.get("conversation_id"),
                            "slug": slug,
                            "error_type": type(exc).__name__,
                        },
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
                        error_message=precheck_error,
                        langfuse_trace_id=state.get("langfuse_trace_id"),
                    )
                    return _append_and_finish(
                        _error_entry(
                            tool_use_id=tool_use_id,
                            slug=slug,
                            raw_input=raw_input,
                            error=precheck_error,
                        )
                    )
                approval_id = uuid4()
                tenant_id_uuid = UUID(state["tenant_id"])
                conv_id_uuid = UUID(state["conversation_id"])
                # is_repeat: ya existe una aprobación para esta MISMA acción —el
                # cliente reescribió mientras seguía en revisión (pending) o tras
                # aprobarse (approved)— así que la reusamos en vez de duplicarla.
                is_repeat = False
                # Estado del approval reusado ("pending" | "approved" | None): el
                # mensaje al cliente depende de él — "sigue en revisión" si está
                # pendiente, "ya quedó aplicado" si ya se aprobó/ejecutó.
                reused_status: str | None = None
                try:
                    # Obtener salt para redactar PII — usamos tenant_scope directamente.
                    from apps.api.db.queries import get_tenant_pii_salt

                    async with tenant_scope(tenant_id_uuid) as conn:
                        # Idempotencia del gate L3: si ya hay una aprobación reciente
                        # (pending o approved) para esta misma acción, la reusamos y
                        # no creamos un duplicado huérfano. order_id se compara
                        # resolviendo visible ↔ interno (mismo pedido, formas distintas).
                        existing = await get_recent_approval_for_skill(
                            conn, tenant_id_uuid, conv_id_uuid, slug
                        )
                        if existing is not None and await _same_order_action(
                            state, existing.inputs_raw, raw_input
                        ):
                            approval_id = existing.id
                            is_repeat = True
                            reused_status = existing.status
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
                    "pending_approval_reused_status": reused_status,
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
        except SkillRefusal as refusal:
            return _escalate_refusal(refusal, skill_cls, raw_input)
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
        return {**_append_and_finish(result_entry), **_identity_update(state, output)}

    return _node
