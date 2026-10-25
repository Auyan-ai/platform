"""Modelos Pydantic compartidos entre las skills de Shopify."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel


class Money(BaseModel):
    """Importe con su código ISO 4217. Ningún importe sale de una skill sin moneda:
    si la skill no la dice, el LLM la infiere (s78: dijo "100,95 €" por 100.95 USD)."""

    amount: str  # string decimal tal cual lo da Shopify ("100.95")
    currency: str  # ISO 4217 ("USD", "GBP")


class FulfillmentInfo(BaseModel):
    status: str
    tracking_number: str | None
    tracking_url: str | None
    tracking_company: str | None
    # Estado del envío reportado por el transportista ("delivered", "in_transit"…),
    # cuando la integración del carrier lo informa. Permite medir el plazo de
    # devolución desde la ENTREGA y no desde la creación del pedido.
    shipment_status: str | None = None


class ShippingAddressInfo(BaseModel):
    """Dirección de envío de un pedido. Solo campos de dirección: sin nombre ni
    teléfono (el agente no los necesita para confirmar a dónde va el pedido)."""

    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    zip: str | None = None
    province: str | None = None
    country: str | None = None


class LineItemInfo(BaseModel):
    """Artículo de un pedido. El `line_item_id` es el que requiere start_return."""

    line_item_id: int
    title: str
    quantity: int
    price: Money | None = None  # precio unitario en la moneda en que pagó el cliente


class OrderSummary(BaseModel):
    order_id: int
    order_number: str  # ej. "#1001"
    financial_status: str
    fulfillment_status: str | None
    total: Money | None  # lo que pagó el cliente, en su moneda (presentment)
    # Solo cuando la tienda cobra en otra moneda (Shopify Markets): referencia interna.
    total_in_shop_currency: Money | None = None
    created_at: str
    tracking_url: str | None


class ProductVariant(BaseModel):
    variant_id: int  # el que pide start_exchange
    title: str
    price: Money  # en la moneda de la tienda
    available: bool


class ProductSummary(BaseModel):
    product_id: int
    title: str
    product_type: str
    status: str
    variants: list[ProductVariant]
    description_snippet: str  # primeros 300 chars del body sin HTML
    tags: list[str] = []  # etiquetas de la tienda (material, colección…)


class PolicyInfo(BaseModel):
    title: str
    body: str  # HTML eliminado, truncado a 2000 chars
    url: str


# ----------------------------------------------------------------
# Helpers de mapeo
# ----------------------------------------------------------------


def first_tracking_url(order: dict[str, Any]) -> str | None:
    """Extrae la primera URL de tracking de los fulfillments de un pedido."""
    for fulfillment in order.get("fulfillments", []):
        urls: list[str] = fulfillment.get("tracking_urls") or []
        if urls:
            return urls[0]
        url: str | None = fulfillment.get("tracking_url")
        if url:
            return url
    return None


def strip_html(text: str) -> str:
    """Elimina tags HTML básicos de un string."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _money_from_set(price_set: dict[str, Any] | None, side: str) -> Money | None:
    money = (price_set or {}).get(side) or {}
    if money.get("amount") is None or not money.get("currency_code"):
        return None
    return Money(amount=str(money["amount"]), currency=money["currency_code"])


def customer_money(
    raw: dict[str, Any], field: str, *, order: dict[str, Any] | None = None
) -> Money | None:
    """Importe `field` de un pedido (o de un line item de `order`) en la moneda en que
    pagó el cliente: `{field}_set.presentment_money`.

    Sin el `_set` (fixtures antiguas) se cae al importe plano, que Shopify da en la
    moneda de la tienda: se etiqueta con ESA moneda, nunca con la del cliente.
    """
    presentment = _money_from_set(raw.get(f"{field}_set"), "presentment_money")
    if presentment is not None:
        return presentment
    amount = raw.get(field)
    shop_currency = (order or raw).get("currency")
    if amount is None or not shop_currency:
        return None
    return Money(amount=str(amount), currency=shop_currency)


def shop_money_if_different(raw: dict[str, Any], field: str) -> Money | None:
    """El mismo importe en la moneda de la tienda, solo si difiere de la del cliente."""
    shop = _money_from_set(raw.get(f"{field}_set"), "shop_money")
    presentment = _money_from_set(raw.get(f"{field}_set"), "presentment_money")
    if shop is None or presentment is None or shop.currency == presentment.currency:
        return None
    return shop


def map_line_item(raw_item: dict[str, Any], order: dict[str, Any]) -> LineItemInfo:
    return LineItemInfo(
        line_item_id=raw_item["id"],
        title=raw_item.get("title", ""),
        quantity=raw_item.get("quantity", 1),
        price=customer_money(raw_item, "price", order=order),
    )


def map_order_summary(raw: dict[str, Any]) -> OrderSummary:
    return OrderSummary(
        order_id=raw["id"],
        order_number=raw.get("name", f"#{raw['id']}"),
        financial_status=raw.get("financial_status", ""),
        fulfillment_status=raw.get("fulfillment_status"),
        total=customer_money(raw, "total_price"),
        total_in_shop_currency=shop_money_if_different(raw, "total_price"),
        created_at=raw.get("created_at", ""),
        tracking_url=first_tracking_url(raw),
    )


def _tag_list(raw: Any) -> list[str]:
    """Etiquetas como lista: la Admin REST las da en un string separado por comas."""
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    return [str(t) for t in raw or []]


def map_product_summary(raw: dict[str, Any], shop_currency: str) -> ProductSummary:
    variants = [
        ProductVariant(
            variant_id=v["id"],
            title=v.get("title", ""),
            price=Money(amount=str(v.get("price", "0.00")), currency=shop_currency),
            available=(
                bool(v["available"])
                if "available" in v
                else (v.get("inventory_quantity", 0) or 0) > 0
            ),
        )
        for v in raw.get("variants", [])
    ]
    return ProductSummary(
        product_id=raw["id"],
        title=raw.get("title", ""),
        product_type=raw.get("product_type", ""),
        status=raw.get("status", ""),
        variants=variants,
        description_snippet=strip_html(raw.get("body_html") or "")[:300],
        tags=_tag_list(raw.get("tags")),
    )
