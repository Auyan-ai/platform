"""Skill L1: busca información de productos en Shopify."""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._models import ProductSummary, map_product_summary


class GetProductInfoInput(SkillInput):
    query: str  # nombre o keyword del producto


class GetProductInfoOutput(SkillOutput):
    products: list[ProductSummary]
    total_found: int


@SkillRegistry.register
class GetProductInfo(Skill):
    slug = "shopify.get_product_info"
    description = (
        "Busca productos activos en Shopify por nombre o keyword. "
        "Devuelve título, tipo, variantes (precio, disponibilidad) y descripción. "
        "Cada precio trae su moneda (la de la tienda): úsala tal cual, sin convertir."
    )
    tier: SkillTier = "L1"
    input_schema = GetProductInfoInput
    output_schema = GetProductInfoOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, GetProductInfoInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        raw_products = await adapter.search_products(ctx.integration_ctx, inputs.query)
        if not raw_products:
            return GetProductInfoOutput(products=[], total_found=0)
        shop_currency = await adapter.get_shop_currency(ctx.integration_ctx)
        if not shop_currency:
            raise ValueError("shop_currency_unavailable")
        products = [map_product_summary(p, shop_currency) for p in raw_products]
        return GetProductInfoOutput(products=products, total_found=len(products))
