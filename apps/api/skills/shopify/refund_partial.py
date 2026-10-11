"""Skill L3: emite un reembolso parcial sobre un pedido.

Requiere aprobación humana. La moneda y el tope (cobrado menos ya reembolsado) salen
del pedido en código: el LLM solo aporta el importe, y uno por encima de lo
reembolsable se rechaza antes de crear la aprobación y otra vez al ejecutar.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._models import Money
from pydantic import Field


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
    success: bool
    order_id: int
    refund_id: int | None = None
    amount: Money


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

    async def prepare_approval(
        self, ctx: SkillContext, raw_input: dict[str, Any]
    ) -> dict[str, Any]:
        """Rechaza un importe por encima de lo reembolsable y fija la moneda del pedido,
        para que quien aprueba vea importe y moneda reales."""
        inputs = RefundPartialInput.model_validate(raw_input)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        balance = await adapter.get_refundable_balance(ctx.integration_ctx, inputs.order_id)
        balance.require(inputs.amount)
        return {**raw_input, "currency": balance.currency}

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, RefundPartialInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        refund = await adapter.refund_partial(
            ctx.integration_ctx, inputs.order_id, amount=inputs.amount, note=inputs.note
        )
        return RefundPartialOutput(
            success=True,
            order_id=inputs.order_id,
            refund_id=refund.refund_id,
            amount=Money(amount=str(refund.amount), currency=refund.currency),
        )
