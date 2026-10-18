"""Skills L3 de devolución (`start_return`) y su base común con `start_exchange` (ADR 0014).

`prepare` aplica la política del tenant al pedido releído de Shopify y deja en los inputs
el plan con su liquidación: es lo que ve y aprueba el humano. `execute` vuelve a leer el
pedido y crea en Shopify exactamente ese plan. El LLM solo elige pedido, artículos, motivo
y, en un cambio, la variante.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.services.fixed_texts import fixed_text
from apps.api.services.returns import (
    Eligible,
    Evidence,
    Refused,
    Rejected,
    RequestedExchange,
    RequestedItem,
    ReturnPlan,
    build_plan,
    evaluate_return,
)
from apps.api.skills.base import (
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


class StartReturnInput(SkillInput):
    order_id: int = Field(description="Número del pedido (#1431 → 1431) o su id interno.")
    items: list[RequestedItem] = Field(
        min_length=1,
        description="Artículos a devolver: `line_item_id` de get_order_status y cantidad.",
    )
    reason_code: str = Field(
        description="Código del motivo, de la lista de la política de la tienda."
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
        return SkillRefusal(
            refused.code,
            customer_message=fixed_text(
                f"refusal.returns.{refused.code}",
                ctx.language,
                tenant_default=ctx.default_language,
                **refused.params,
            ),
            team_reason=refused.team_reason,
        )

    async def prepare(self, ctx: SkillContext, raw_input: dict[str, Any]) -> dict[str, Any]:
        inputs = self.input_schema.model_validate(
            {k: v for k, v in raw_input.items() if k != "plan"}
        )
        assert isinstance(inputs, StartReturnInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        exchange = self._exchange(inputs)
        order = await adapter.get_returnable_order(ctx.integration_ctx, inputs.order_id)
        variants = (
            await adapter.get_exchange_variants(
                ctx.integration_ctx, [e.variant_id for e in exchange]
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
        )
        if isinstance(decision, Refused):
            raise self._refusal(ctx, decision)
        if isinstance(decision, Rejected):
            raise SkillRejection(decision.code, decision.detail)
        assert isinstance(decision, Eligible)
        calculation = await adapter.calculate_return(
            ctx.integration_ctx,
            order.order_id,
            lines=[(ln.fulfillment_line_item_id, ln.quantity) for ln in decision.lines],
            exchange=[(ln.variant_id, ln.quantity) for ln in decision.exchange_lines],
        )
        plan = build_plan(decision, calculation, requested_at=now)
        return {
            **inputs.model_dump(mode="json", exclude={"plan"}),
            "plan": plan.model_dump(mode="json"),
            "settlement_note": plan.team_note(),
        }

    @classmethod
    def requires_approval(cls, prepared: dict[str, Any]) -> bool:
        return bool((prepared.get("plan") or {}).get("requires_approval", True))

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, StartReturnInput)
        if inputs.plan is None:
            raise ValueError("return_plan_missing")
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        plan = inputs.plan
        adapter = ctx.commerce_mock or ShopifyAdapter()
        # La aprobación puede llevar horas: se crea lo aprobado si Shopify aún lo permite.
        order = await adapter.get_returnable_order(ctx.integration_ctx, plan.order_id)
        problem = _no_longer_possible(plan, order)
        if problem is None and plan.exchange_lines:
            variants = await adapter.get_exchange_variants(
                ctx.integration_ctx, [ln.variant_id for ln in plan.exchange_lines]
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
                    f"cual: {problem}. Revisad el pedido en Shopify."
                ),
            )
        created = await adapter.create_return(ctx.integration_ctx, plan)
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


def _no_longer_possible(plan: ReturnPlan, order: Any) -> str | None:
    if order.cancelled:
        return "el pedido está cancelado"
    for line in plan.lines:
        current = order.line(line.line_item_id)
        if current is None or current.returnable_quantity < line.quantity:
            return f"'{line.title}' ya no tiene {line.quantity} unidad(es) devolvible(s)"
        if current.fulfillment_line_item_id != line.fulfillment_line_item_id:
            return f"'{line.title}' cambió de envío en Shopify"
    return None


@SkillRegistry.register
class StartReturn(_ReturnSkill):
    slug = "shopify.start_return"
    description = (
        "Abre la devolución de uno o varios artículos de un pedido de Shopify, sin cambio. "
        "Úsala cuando el cliente haya confirmado qué artículos devuelve, cuántos y el "
        "motivo. `reason_code` es uno de los códigos de la política de la tienda que tienes "
        "en el turno. El sistema comprueba plazo, motivo, pruebas y envío, y calcula el "
        "reembolso; si algo falla te devuelve el error o pasa el caso al equipo."
    )
    input_schema = StartReturnInput
