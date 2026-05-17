"""Skill L1: busca pedidos de Shopify por email del cliente."""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyClient
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._models import OrderSummary, map_order_summary


class GetOrderByEmailInput(SkillInput):
    email: str


class GetOrderByEmailOutput(SkillOutput):
    orders: list[OrderSummary]
    total_found: int


@SkillRegistry.register
class GetOrderByEmail(Skill):
    slug = "shopify.get_order_by_email"
    description = (
        "Busca pedidos de Shopify por email del cliente. "
        "Devuelve hasta 10 pedidos más recientes con estado, precio y tracking."
    )
    tier: SkillTier = "L1"
    input_schema = GetOrderByEmailInput
    output_schema = GetOrderByEmailOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, GetOrderByEmailInput)
        if not ctx.shopify_domain or not ctx.shopify_token:
            raise ValueError("shopify_not_configured")
        shopify = ShopifyClient(ctx.shopify_domain, ctx.shopify_token)
        raw_orders = await shopify.get_orders_by_email(inputs.email)
        orders = [map_order_summary(o) for o in raw_orders]
        return GetOrderByEmailOutput(orders=orders, total_found=len(orders))
