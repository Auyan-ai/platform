"""Skill L2: añade tags a un pedido de Shopify (merge no-destructivo)."""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyClient
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry


class TagOrderInput(SkillInput):
    order_id: int
    tags: list[str]


class TagOrderOutput(SkillOutput):
    success: bool
    order_id: int
    current_tags: list[str]


@SkillRegistry.register
class TagOrder(Skill):
    slug = "shopify.tag_order"
    description = (
        "Añade tags a un pedido de Shopify sin eliminar los existentes. "
        "Útil para marcar pedidos que requieren atención especial. "
        "Ejemplos de tags: 'return-requested', 'damaged', 'refund-needed', "
        "'customer-complaint', 'priority'. "
        "Requiere el ID numérico del pedido y una lista de tags a añadir."
    )
    tier: SkillTier = "L2"
    input_schema = TagOrderInput
    output_schema = TagOrderOutput
    requires_idempotency = False
    default_threshold = 0.85

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, TagOrderInput)
        if not ctx.shopify_domain or not ctx.shopify_token:
            raise ValueError("shopify_not_configured")
        shopify = ShopifyClient(ctx.shopify_domain, ctx.shopify_token)
        order = await shopify.tag_order(inputs.order_id, inputs.tags)
        current_tags = [t.strip() for t in order.get("tags", "").split(",") if t.strip()]
        return TagOrderOutput(
            success=True,
            order_id=order["id"],
            current_tags=current_tags,
        )
