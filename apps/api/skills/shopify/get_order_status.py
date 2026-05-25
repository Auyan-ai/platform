"""Skill L1: devuelve el estado detallado de un pedido por nombre/número."""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._models import FulfillmentInfo, LineItemInfo
from pydantic import Field


class GetOrderStatusInput(SkillInput):
    order_identifier: str  # ej. "#1234", "1234", o "1234" sin #


class OrderDetail(SkillOutput):
    found: bool
    order_id: int | None
    order_number: str | None
    financial_status: str | None
    fulfillment_status: str | None
    total_price: str | None
    currency: str | None
    created_at: str | None
    fulfillments: list[FulfillmentInfo]
    # Artículos del pedido — el agente necesita line_item_id para start_return.
    line_items: list[LineItemInfo] = Field(default_factory=list)


@SkillRegistry.register
class GetOrderStatus(Skill):
    slug = "shopify.get_order_status"
    description = (
        "Devuelve el estado detallado de un pedido de Shopify. "
        "Acepta el número de orden (#1234 o 1234). "
        "Incluye estado de pago, fulfillment y tracking."
    )
    tier: SkillTier = "L1"
    input_schema = GetOrderStatusInput
    output_schema = OrderDetail
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, GetOrderStatusInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        raw = await adapter.get_order_by_name(ctx.integration_ctx, inputs.order_identifier)

        if raw is None:
            return OrderDetail(
                found=False,
                order_id=None,
                order_number=None,
                financial_status=None,
                fulfillment_status=None,
                total_price=None,
                currency=None,
                created_at=None,
                fulfillments=[],
            )

        fulfillments = [
            FulfillmentInfo(
                status=f.get("status", ""),
                tracking_number=f.get("tracking_number"),
                tracking_url=(f.get("tracking_urls") or [None])[0]
                or f.get("tracking_url"),
                tracking_company=f.get("tracking_company"),
            )
            for f in raw.get("fulfillments", [])
        ]
        line_items = [
            LineItemInfo(
                line_item_id=li["id"],
                title=li.get("title", ""),
                quantity=li.get("quantity", 1),
                price=li.get("price"),
            )
            for li in raw.get("line_items", [])
            if "id" in li
        ]
        return OrderDetail(
            found=True,
            order_id=raw["id"],
            order_number=raw.get("name") or raw.get("order_number"),
            financial_status=raw.get("financial_status"),
            fulfillment_status=raw.get("fulfillment_status"),
            total_price=raw.get("total_price"),
            currency=raw.get("currency"),
            created_at=raw.get("created_at"),
            fulfillments=fulfillments,
            line_items=line_items,
        )
