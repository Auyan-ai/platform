"""Skill L3: emite un reembolso parcial sobre un pedido.

Requiere aprobación humana. El importe no puede superar el total del pedido.
"""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry


class RefundPartialInput(SkillInput):
    order_id: int
    amount: str
    currency: str
    note: str = ""


class RefundPartialOutput(SkillOutput):
    success: bool
    order_id: int
    refund_id: int | None = None
    amount: str
    currency: str


@SkillRegistry.register
class RefundPartial(Skill):
    slug = "shopify.refund_partial"
    description = (
        "Emite un reembolso parcial sobre un pedido de Shopify. "
        "Usa esta skill SOLO cuando el cliente haya acordado el importe a reembolsar "
        "y haya confirmado el método de pago original. "
        "Requiere el ID del pedido, el importe (como string, ej: '12.50') y la divisa. "
        "NUNCA inventes el importe — obtén la confirmación del cliente primero."
    )
    tier: SkillTier = "L3"
    input_schema = RefundPartialInput
    output_schema = RefundPartialOutput
    requires_idempotency = True
    default_threshold = 0.95

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, RefundPartialInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        refund = await adapter.refund_partial(
            ctx.integration_ctx,
            inputs.order_id,
            amount=inputs.amount,
            currency=inputs.currency,
            note=inputs.note,
        )
        return RefundPartialOutput(
            success=True,
            order_id=inputs.order_id,
            refund_id=refund.get("id"),
            amount=inputs.amount,
            currency=inputs.currency,
        )
