"""Skill L1: devuelve el estado detallado de un pedido por nombre/número."""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._models import FulfillmentInfo, LineItemInfo, ShippingAddressInfo
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
    # Fecha de envío (created_at del primer fulfillment) y de entrega (cuando el
    # carrier reporta shipment_status="delivered"). El plazo de devolución se mide
    # desde la entrega; si no hay, desde el envío; y solo en último recurso desde
    # created_at del pedido.
    fulfilled_at: str | None = None
    delivered_at: str | None = None
    fulfillments: list[FulfillmentInfo]
    # Artículos del pedido — el agente necesita line_item_id para start_return.
    line_items: list[LineItemInfo] = Field(default_factory=list)
    # Dirección de envío: solo si quien escribe es el dueño del pedido (su email
    # coincide con el del pedido). Si no, se retiene y `shipping_address_withheld`
    # lo indica para que el agente lo explique sin revelarla.
    shipping_address: ShippingAddressInfo | None = None
    shipping_address_withheld: bool = False


def _same_email(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.strip().casefold() == b.strip().casefold())


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

        raw_fulfillments = raw.get("fulfillments", [])
        fulfillments = [
            FulfillmentInfo(
                status=f.get("status", ""),
                tracking_number=f.get("tracking_number"),
                tracking_url=(f.get("tracking_urls") or [None])[0] or f.get("tracking_url"),
                tracking_company=f.get("tracking_company"),
                shipment_status=f.get("shipment_status"),
            )
            for f in raw_fulfillments
        ]
        # Fecha de envío: created_at del primer fulfillment. Fecha de entrega:
        # updated_at del fulfillment que el carrier marca como "delivered".
        fulfilled_at = raw_fulfillments[0].get("created_at") if raw_fulfillments else None
        delivered_at = next(
            (
                f.get("updated_at")
                for f in raw_fulfillments
                if f.get("shipment_status") == "delivered"
            ),
            None,
        )
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
        raw_address = raw.get("shipping_address") or None
        order_email = raw.get("email") or (raw.get("customer") or {}).get("email")
        is_owner = _same_email(ctx.customer_email, order_email)
        shipping_address = (
            ShippingAddressInfo(**{k: raw_address.get(k) for k in ShippingAddressInfo.model_fields})
            if raw_address and is_owner
            else None
        )
        return OrderDetail(
            found=True,
            order_id=raw["id"],
            order_number=raw.get("name") or raw.get("order_number"),
            financial_status=raw.get("financial_status"),
            fulfillment_status=raw.get("fulfillment_status"),
            total_price=raw.get("total_price"),
            currency=raw.get("currency"),
            created_at=raw.get("created_at"),
            fulfilled_at=fulfilled_at,
            delivered_at=delivered_at,
            fulfillments=fulfillments,
            line_items=line_items,
            shipping_address=shipping_address,
            shipping_address_withheld=bool(raw_address) and not is_owner,
        )
