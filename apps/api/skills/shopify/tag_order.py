"""Skill L2: añade tags a un pedido de Shopify (merge no-destructivo)."""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyAdapter
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
    identity_scope = "order"
    min_level = "guest"

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, TagOrderInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        order = await adapter.tag_order(ctx.integration_ctx, inputs.order_id, inputs.tags)
        current_tags = [t.strip() for t in order.get("tags", "").split(",") if t.strip()]
        return TagOrderOutput(
            success=True,
            order_id=order["id"],
            current_tags=current_tags,
        )
