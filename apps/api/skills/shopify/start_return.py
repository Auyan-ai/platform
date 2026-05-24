"""Skill L3: inicia el proceso de devolución de un artículo.

Requiere aprobación humana. Solo aplica para pedidos entregados.
"""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry


class StartReturnInput(SkillInput):
    order_id: int
    line_item_id: int
    quantity: int
    reason: str = "other"


class StartReturnOutput(SkillOutput):
    success: bool
    order_id: int
    return_id: int | None = None
    status: str | None = None


@SkillRegistry.register
class StartReturn(Skill):
    slug = "shopify.start_return"
    description = (
        "Inicia el proceso de devolución de un artículo de un pedido de Shopify. "
        "Usa esta skill SOLO cuando el pedido esté entregado y el cliente haya confirmado "
        "qué artículo quiere devolver y la cantidad. "
        "Requiere el ID del pedido, el ID del line item y la cantidad a devolver. "
        "Si el pedido no está entregado, escala — no inicies una devolución prematura."
    )
    tier: SkillTier = "L3"
    input_schema = StartReturnInput
    output_schema = StartReturnOutput
    requires_idempotency = True
    default_threshold = 0.95

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, StartReturnInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ShopifyAdapter()
        ret = await adapter.start_return(
            ctx.integration_ctx,
            inputs.order_id,
            line_item_id=inputs.line_item_id,
            quantity=inputs.quantity,
            reason=inputs.reason,
        )
        return StartReturnOutput(
            success=True,
            order_id=inputs.order_id,
            return_id=ret.get("id"),
            status=ret.get("status"),
        )
