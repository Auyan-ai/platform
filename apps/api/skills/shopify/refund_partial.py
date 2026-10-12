"""Skill L3: emite un reembolso parcial sobre un pedido.

Requiere aprobación humana. La moneda y el tope (cobrado menos ya reembolsado) salen
del pedido en código: el LLM solo aporta el importe, y uno por encima de lo
reembolsable se rechaza antes de crear la aprobación y otra vez al ejecutar.

La tarjeta de aprobación dice por dónde vuelve el dinero (pasarela automática o
manual) y, tras ejecutar, el reembolso se relee del pedido: con pasarela manual
Shopify solo lo apunta y devuelve la tienda (`ActionOutcome`).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.api.integrations.shopify import RefundMode, ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._models import Money
from apps.api.skills.shopify._order_guard import ActionOutcome, refund_verdict
from pydantic import Field, computed_field


class RefundPartialInput(SkillInput):
    order_id: int
    amount: Decimal = Field(
        gt=0,
        description=(
            "Importe a reembolsar en la moneda en que pagó el cliente (la de los "
            "importes de get_order_status), p. ej. '12.50'. La moneda la pone el sistema."
        ),
    )
    note: str = ""


class RefundPartialOutput(SkillOutput):
    order_id: int
    refund_id: int | None = None
    amount: Money
    outcome: ActionOutcome
    detail: str | None = None
    refund_mode: RefundMode
    refund_gateway: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success(self) -> bool:
        return self.outcome.settled


@SkillRegistry.register
class RefundPartial(Skill):
    slug = "shopify.refund_partial"
    description = (
        "Emite un reembolso parcial sobre un pedido de Shopify. "
        "Usa esta skill SOLO cuando el cliente haya acordado el importe a reembolsar "
        "y haya confirmado el método de pago original. "
        "Requiere el ID del pedido y el importe (como string, ej: '12.50') en la moneda "
        "en que pagó el cliente; la moneda la toma el sistema del pedido. "
        "NUNCA inventes el importe — obtén la confirmación del cliente primero."
    )
    tier: SkillTier = "L3"
    input_schema = RefundPartialInput
    output_schema = RefundPartialOutput
    requires_idempotency = True
    default_threshold = 0.95
    identity_scope = "order"
    min_level = "guest"

    async def prepare_approval(
        self, ctx: SkillContext, raw_input: dict[str, Any]
    ) -> dict[str, Any]:
        """Rechaza un importe por encima de lo reembolsable y fija la moneda del pedido
        y por dónde vuelve el dinero, para que quien aprueba vea los datos reales."""
        inputs = RefundPartialInput.model_validate(raw_input)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        balance = await adapter.get_refundable_balance(ctx.integration_ctx, inputs.order_id)
        balance.require(inputs.amount)
        snapshot = await adapter.get_order_snapshot(ctx.integration_ctx, inputs.order_id)
        route = snapshot.refund_route
        return {
            **raw_input,
            "currency": balance.currency,
            "refund_mode": route.mode,
            "refund_gateway": route.gateway,
        }

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, RefundPartialInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        before = await adapter.get_order_snapshot(ctx.integration_ctx, inputs.order_id)
        refund = await adapter.refund_partial(
            ctx.integration_ctx, before.order_id, amount=inputs.amount, note=inputs.note
        )
        after = await adapter.get_order_snapshot(ctx.integration_ctx, before.order_id)
        route = before.refund_route
        verdict = refund_verdict(route, before, after)
        return RefundPartialOutput(
            order_id=inputs.order_id,
            refund_id=refund.refund_id,
            amount=Money(amount=str(refund.amount), currency=refund.currency),
            outcome=verdict.outcome,
            detail=verdict.detail,
            refund_mode=route.mode,
            refund_gateway=route.gateway,
        )
