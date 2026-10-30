"""Skills L3 de devolución (`start_return`) y su base común con `start_exchange` (ADR 0014).

`prepare` aplica la política del tenant al pedido releído de Shopify y deja en los inputs
el plan con su liquidación: es lo que ve y aprueba el humano. `execute` vuelve a leer el
pedido y crea en Shopify exactamente ese plan. El LLM solo elige pedido, artículos, motivo
y, en un cambio, la variante.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from datetime import UTC, date, datetime
from typing import Any, ClassVar, TypeVar

from apps.api.integrations.base import MutationNotApplied
from apps.api.integrations.commerce import CommerceCapability, CreatedReturn
from apps.api.services.fixed_texts import fixed_text
from apps.api.services.returns import (
    Eligible,
    Evidence,
    RefundPreference,
    Refused,
    Rejected,
    RequestedExchange,
    RequestedItem,
    ReturnPlan,
    build_plan,
    evaluate_return,
)
from apps.api.services.tenant_time import tenant_zone
from apps.api.skills.base import (
    ReconcileUnknown,
    Skill,
    SkillContext,
    SkillInput,
    SkillOutput,
    SkillRefusal,
    SkillRejection,
    SkillTier,
)
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._order_guard import ActionOutcome
from pydantic import Field, computed_field, field_validator
from pydantic.json_schema import SkipJsonSchema

logger = logging.getLogger(__name__)
T = TypeVar("T")


class StartReturnInput(SkillInput):
    order_id: int = Field(description="Número del pedido (#1431 → 1431) o su id interno.")
    items: list[RequestedItem] = Field(
        min_length=1,
        description="Artículos a devolver: `line_item_id` de get_order_status y cantidad.",
    )
    reason_code: str = Field(
        description="Código del motivo, de la lista de la política de la tienda."
    )
    refund_preference: RefundPreference | None = Field(
        default=None,
        description=(
            "Solo si la política deja elegir: `original_payment` (método de pago original) "
            "o `store_credit` (crédito de la tienda), según diga el cliente."
        ),
    )
    # Lo escribe el código en `prepare`; el que mande el LLM se descarta.
    plan: SkipJsonSchema[ReturnPlan | None] = None

    @field_validator("items")
    @classmethod
    def _one_row_per_item(cls, items: list[RequestedItem]) -> list[RequestedItem]:
        ids = [i.line_item_id for i in items]
        if len(ids) != len(set(ids)):
            raise ValueError("cada artículo va una sola vez, con su cantidad total")
        return items


class StartReturnOutput(SkillOutput):
    order_id: int
    return_id: int | None
    return_name: str | None
    status: str | None
    outcome: ActionOutcome
    plan: ReturnPlan
    shopify_reason: str | None = None
    note_written: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success(self) -> bool:
        return self.outcome.settled


class _ReturnSkill(Skill):
    tier: ClassVar[SkillTier] = "L3"
    output_schema = StartReturnOutput
    requires_idempotency = True
    default_threshold = 0.95
    identity_scope = "order"
    min_level = "guest"
    reply_from_outcome = True

    def _exchange(self, inputs: StartReturnInput) -> tuple[RequestedExchange, ...]:
        return ()

    def _refusal(self, ctx: SkillContext, refused: Refused) -> SkillRefusal:
        params = dict(refused.params)
        if "deadline" in params:
            params["deadline"] = _localized_date(
                date.fromisoformat(params["deadline"]), ctx.language
            )
        return SkillRefusal(
            refused.code,
            customer_message=fixed_text(
                f"refusal.returns.{refused.code}",
                ctx.language,
                tenant_default=ctx.default_language,
                **params,
            ),
            team_reason=refused.team_reason,
        )

    async def prepare(self, ctx: SkillContext, raw_input: dict[str, Any]) -> dict[str, Any]:
        inputs = self.input_schema.model_validate(
            {k: v for k, v in raw_input.items() if k != "plan"}
        )
        assert isinstance(inputs, StartReturnInput)
        adapter = ctx.require_commerce()
        exchange = self._exchange(inputs)
        order = await _shopify(
            ctx,
            "leer el pedido",
            adapter.get_returnable_order(ctx.integration_ctx, inputs.order_id),
        )
        variants = (
            await _shopify(
                ctx,
                "leer las variantes de cambio",
                adapter.get_exchange_variants(
                    ctx.integration_ctx, [e.variant_id for e in exchange]
                ),
            )
            if exchange and ctx.returns_policy and ctx.returns_policy.policy.exchanges.enabled
            else ()
        )
        now = datetime.now(UTC)
        decision = evaluate_return(
            ctx.returns_policy,
            order,
            reason_code=inputs.reason_code,
            items=tuple(inputs.items),
            exchange=exchange,
            variants=variants,
            evidence=Evidence(photos=ctx.customer_photos, readable=ctx.attachments_readable),
            now=now,
            refund_preference=inputs.refund_preference,
            tz=tenant_zone(ctx.tenant_facts)[1],
        )
        if isinstance(decision, Refused):
            raise self._refusal(ctx, decision)
        if isinstance(decision, Rejected):
            raise SkillRejection(decision.code, decision.detail)
        assert isinstance(decision, Eligible)
        calculation = await _shopify(
            ctx,
            "calcular la devolución",
            adapter.calculate_return(
                ctx.integration_ctx,
                order.order_id,
                lines=[(ln.fulfillment_line_item_id, ln.quantity) for ln in decision.lines],
                exchange=[(ln.variant_id, ln.quantity) for ln in decision.exchange_lines],
            ),
        )
        try:
            plan = build_plan(decision, calculation, requested_at=now)
        except KeyError as exc:
            raise _shopify_refusal(ctx, "cuadrar el cálculo de la tienda con el pedido", exc) from exc
        if isinstance(plan, Refused):
            raise self._refusal(ctx, plan)
        if isinstance(plan, Rejected):
            raise SkillRejection(plan.code, plan.detail)
        return {
            **inputs.model_dump(mode="json", exclude={"plan"}),
            "plan": plan.model_dump(mode="json"),
            "settlement_note": plan.team_note(),
        }

    @classmethod
    def approval_key(cls, inputs: dict[str, Any]) -> dict[str, Any]:
        # Solo lo que pidió el cliente: el plan lleva la hora de la petición y la nota,
        # que cambian en cada intento de la misma devolución. La forma del reembolso es la
        # que resolvió la política (`refund_as`), no la preferencia cruda del LLM, que la
        # política puede ignorar; sin plan (antes de `prepare`), la preferencia.
        def rows(key: str, id_field: str) -> list[tuple[Any, Any]]:
            return sorted((r.get(id_field), r.get("quantity")) for r in inputs.get(key) or [])

        plan = inputs.get("plan")
        return {
            "items": rows("items", "line_item_id"),
            "exchange_items": rows("exchange_items", "variant_id"),
            "reason_code": inputs.get("reason_code"),
            "refund": plan["settlement"]["refund_as"] if plan else inputs.get("refund_preference"),
        }

    @classmethod
    def requires_approval(cls, prepared: dict[str, Any]) -> bool:
        return bool((prepared.get("plan") or {}).get("requires_approval", True))

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        """Crea en Shopify el plan aprobado, una sola vez.

        Antes de enviar `returnCreate` busca la devolución con la marca del plan: si un
        intento anterior ya la creó, la devuelve sin crear otra (y sin que el
        `no_longer_possible` que causaría la propia devolución lo tape). Lo que falla
        antes de enviar es `MutationNotApplied`; un error tras enviarla se propaga tal
        cual, porque no se sabe si Shopify la creó, y lo resuelve `reconcile`.
        """
        assert isinstance(inputs, StartReturnInput)
        if inputs.plan is None:
            raise ValueError("return_plan_missing")
        adapter = ctx.require_commerce()
        plan = inputs.plan
        existing = await _before_sending(
            "buscar la devolución del plan", adapter.find_return(ctx.integration_ctx, plan)
        )
        if existing is not None:
            return await self._output(ctx, adapter, plan, existing)
        # La aprobación puede llevar horas: se crea lo aprobado si Shopify aún lo permite.
        order = await _before_sending(
            "leer el pedido", adapter.get_returnable_order(ctx.integration_ctx, plan.order_id)
        )
        problem = _no_longer_possible(plan, order)
        if problem is None and plan.exchange_lines:
            variants = await _before_sending(
                "leer las variantes de cambio",
                adapter.get_exchange_variants(
                    ctx.integration_ctx, [ln.variant_id for ln in plan.exchange_lines]
                ),
            )
            available = {v.variant_id for v in variants if v.available}
            gone = [ln.title for ln in plan.exchange_lines if ln.variant_id not in available]
            if gone:
                problem = f"ya no hay disponibilidad de {', '.join(gone)}"
        if problem is not None:
            raise SkillRefusal(
                "no_longer_possible",
                customer_message=fixed_text(
                    "refusal.returns.no_longer_possible",
                    ctx.language,
                    tenant_default=ctx.default_language,
                ),
                team_reason=(
                    f"La devolución aprobada de {plan.order_name} ya no se puede crear tal "
                    f"cual: {problem}. Revisad el pedido en {ctx.platform_name}."
                ),
            )
        created = await adapter.create_return(ctx.integration_ctx, plan)
        return await self._output(ctx, adapter, plan, created)

    async def reconcile(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput | None:
        """La devolución del plan si Shopify la tiene (por su marca), None si consta que
        no. Si Shopify no deja leer todas las devoluciones del pedido, `ReconcileUnknown`.

        Solo escribe, si falta, la nota de la liquidación, que no se duplica."""
        assert isinstance(inputs, StartReturnInput)
        adapter = ctx.commerce
        if inputs.plan is None or adapter is None:
            raise ReconcileUnknown("return_plan_missing")
        try:
            found = await adapter.find_return(ctx.integration_ctx, inputs.plan)
        except Exception as exc:
            raise ReconcileUnknown(f"{type(exc).__name__}: {exc}") from exc
        if found is None:
            return None
        return await self._output(ctx, adapter, inputs.plan, found)

    async def _output(
        self, ctx: SkillContext, adapter: Any, plan: ReturnPlan, created: CreatedReturn
    ) -> StartReturnOutput:
        note_written = True
        try:
            await adapter.append_order_note(ctx.integration_ctx, plan.order_id, plan.team_note())
        except Exception:
            note_written = False
            logger.error(
                "return_settlement_note_failed",
                extra={"tenant_id": ctx.tenant_id, "order_id": plan.order_id},
                exc_info=True,
            )
        opened = created.status in ("open", "requested")
        return StartReturnOutput(
            order_id=plan.order_id,
            return_id=created.return_id,
            return_name=created.name,
            status=created.status,
            outcome=ActionOutcome.CONFIRMED if opened else ActionOutcome.NOT_CONFIRMED,
            plan=plan,
            shopify_reason=created.reason_handle,
            note_written=note_written,
        )


_MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _localized_date(day: date, language: str) -> str:
    if language == "en":
        return f"{day.day} {_MONTHS_EN[day.month - 1]} {day.year}"
    return f"{day:%d/%m/%Y}"


def _shopify_refusal(ctx: SkillContext, step: str, exc: BaseException) -> SkillRefusal:
    logger.error(
        "return_shopify_failed",
        extra={"tenant_id": ctx.tenant_id, "step": step, "error_type": type(exc).__name__},
        exc_info=exc,
    )
    return SkillRefusal(
        "shopify_error",
        customer_message=fixed_text(
            "refusal.returns.shopify_error", ctx.language, tenant_default=ctx.default_language
        ),
        team_reason=(
            f"{ctx.platform_name} falló al {step} ({type(exc).__name__}: {exc}). No se abrió "
            f"nada desde Auyan: revisad el pedido en {ctx.platform_name} antes de reintentarlo."
        ),
    )


async def _shopify(ctx: SkillContext, step: str, call: Awaitable[T]) -> T:
    """Una lectura de Shopify en `prepare`: un fallo no llega al LLM como texto crudo,
    pasa el caso al equipo con texto fijo y la razón."""
    try:
        return await call
    except (SkillRefusal, SkillRejection):
        raise
    except Exception as exc:
        raise _shopify_refusal(ctx, step, exc) from exc


async def _before_sending(step: str, call: Awaitable[T]) -> T:
    """Una lectura de `execute` antes de enviar `returnCreate`: si falla, consta que la
    devolución no se creó en esta ejecución."""
    try:
        return await call
    except Exception as exc:
        raise MutationNotApplied(f"{step}: {type(exc).__name__}: {exc}") from exc


def _no_longer_possible(plan: ReturnPlan, order: Any) -> str | None:
    if order.cancelled:
        return "el pedido está cancelado"
    for line in plan.lines:
        current = order.line(line.line_item_id)
        if current is None or current.returnable_quantity < line.quantity:
            return f"'{line.title}' ya no tiene {line.quantity} unidad(es) devolvible(s)"
        if current.fulfillment_line_item_id != line.fulfillment_line_item_id:
            return f"'{line.title}' cambió de envío en la tienda"
    return None


@SkillRegistry.register
class StartReturn(_ReturnSkill):
    slug = "shopify.start_return"
    required_capability = CommerceCapability.RETURNS
    description = (
        "Abre la devolución de uno o varios artículos de un pedido de la tienda, sin cambio. "
        "Úsala cuando el cliente haya confirmado qué artículos devuelve, cuántos y el "
        "motivo. `reason_code` es uno de los códigos de la política de la tienda que tienes "
        "en el turno. El sistema comprueba plazo, motivo, pruebas y envío, y calcula el "
        "reembolso; si algo falla te devuelve el error o pasa el caso al equipo."
    )
    input_schema = StartReturnInput
