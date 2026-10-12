"""Skill L1: devuelve el estado detallado de un pedido por nombre/número, solo a su dueño."""

from __future__ import annotations

import logging

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.services.identity import check_order_ownership
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._models import (
    FulfillmentInfo,
    LineItemInfo,
    Money,
    ShippingAddressInfo,
    customer_money,
    map_line_item,
    shop_money_if_different,
)
from pydantic import Field

logger = logging.getLogger(__name__)


class GetOrderStatusInput(SkillInput):
    order_identifier: str  # ej. "#1234", "1234", o "1234" sin #


class OrderDetail(SkillOutput):
    found: bool
    order_id: int | None
    order_number: str | None
    financial_status: str | None
    fulfillment_status: str | None
    # Importes en la moneda en que pagó el cliente (presentment). La de la tienda solo
    # aparece en `total_in_shop_currency` cuando difiere (Shopify Markets).
    total: Money | None
    total_in_shop_currency: Money | None = None
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
    shipping_address: ShippingAddressInfo | None = None
    # Solo con found=False: qué decirle al cliente, igual exista o no el pedido.
    note: str | None = None


# Mismo texto si el pedido no existe y si no es de quien escribe: no revela cuál de
# los dos casos es (los números de pedido son correlativos y se pueden enumerar).
NOT_FOUND_NOTE = (
    "No hay ningún pedido con ese número asociado al email o teléfono desde el que "
    "escribe el cliente. No digas si ese pedido existe ni des ningún dato de él. Pídele "
    "que revise el número y que escriba desde el email o el teléfono con el que hizo la "
    "compra, u ofrécele pasar el caso a una persona del equipo."
)

_NOT_FOUND = OrderDetail(
    found=False,
    order_id=None,
    order_number=None,
    financial_status=None,
    fulfillment_status=None,
    total=None,
    created_at=None,
    fulfillments=[],
    note=NOT_FOUND_NOTE,
)


@SkillRegistry.register
class GetOrderStatus(Skill):
    slug = "shopify.get_order_status"
    description = (
        "Devuelve el estado detallado de un pedido de Shopify. "
        "Acepta el número de orden (#1234 o 1234). "
        "Incluye estado de pago, fulfillment, tracking, artículos y dirección de envío. "
        "Solo devuelve pedidos del email o teléfono desde el que escribe el cliente. "
        "Los importes vienen en la moneda en que pagó el cliente: úsala tal cual."
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
            return _NOT_FOUND
        ownership = check_order_ownership(
            raw,
            customer_email=ctx.customer_email,
            customer_phone=ctx.customer_phone,
            default_region=ctx.phone_region,
        )
        if not ownership.owner:
            logger.info(
                "order_status_not_owner",
                extra={"conversation_id": ctx.conversation_id, "reason": ownership.reason},
            )
            return _NOT_FOUND

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
        line_items = [map_line_item(li, raw) for li in raw.get("line_items", []) if "id" in li]
        raw_address = raw.get("shipping_address") or None
        shipping_address = (
            ShippingAddressInfo(**{k: raw_address.get(k) for k in ShippingAddressInfo.model_fields})
            if raw_address
            else None
        )
        return OrderDetail(
            found=True,
            order_id=raw["id"],
            order_number=raw.get("name") or raw.get("order_number"),
            financial_status=raw.get("financial_status"),
            fulfillment_status=raw.get("fulfillment_status"),
            total=customer_money(raw, "total_price"),
            total_in_shop_currency=shop_money_if_different(raw, "total_price"),
            created_at=raw.get("created_at"),
            fulfilled_at=fulfilled_at,
            delivered_at=delivered_at,
            fulfillments=fulfillments,
            line_items=line_items,
            shipping_address=shipping_address,
        )
