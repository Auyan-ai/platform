"""Skill L3: cancela un pedido en Shopify.

Requiere aprobación humana (human_approval_required=True en tenant_tool_permissions).
El supervisor usa Opus antes de crear la solicitud de aprobación.
Solo se puede cancelar si el pedido no ha sido enviado aún.
"""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyClient
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry


class CancelOrderInput(SkillInput):
    order_id: int
    reason: str = "customer"
    send_email: bool = True
    refund_payment: bool = False


class CancelOrderOutput(SkillOutput):
    success: bool
    order_id: int
    cancelled: bool
    financial_status: str | None = None
    fulfillment_status: str | None = None


@SkillRegistry.register
class CancelOrder(Skill):
    slug = "shopify.cancel_order"
    description = (
        "Cancela un pedido de Shopify. "
        "Usa esta skill SOLO cuando el cliente haya confirmado explícitamente que quiere cancelar "
        "y el pedido no haya sido enviado todavía. "
        "Requiere el ID numérico del pedido. "
        "NUNCA uses esta skill si el pedido está parcialmente enviado — escala en ese caso."
    )
    tier: SkillTier = "L3"
    input_schema = CancelOrderInput
    output_schema = CancelOrderOutput
    requires_idempotency = True
    default_threshold = 0.95

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, CancelOrderInput)
        if not ctx.shopify_domain or not ctx.shopify_token:
            raise ValueError("shopify_not_configured")
        shopify = ShopifyClient(ctx.shopify_domain, ctx.shopify_token)
        order = await shopify.cancel_order(
            inputs.order_id,
            reason=inputs.reason,
            email=inputs.send_email,
            refund=inputs.refund_payment,
        )
        return CancelOrderOutput(
            success=True,
            order_id=order["id"],
            cancelled=order.get("cancelled_at") is not None,
            financial_status=order.get("financial_status"),
            fulfillment_status=order.get("fulfillment_status"),
        )
