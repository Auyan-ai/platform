"""Modelos Pydantic compartidos entre las skills de Shopify."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel


class FulfillmentInfo(BaseModel):
    status: str
    tracking_number: str | None
    tracking_url: str | None
    tracking_company: str | None


class OrderSummary(BaseModel):
    order_id: int
    order_number: str  # ej. "#1001"
    financial_status: str
    fulfillment_status: str | None
    total_price: str  # Shopify devuelve como string decimal
    currency: str
    created_at: str
    tracking_url: str | None


class ProductVariant(BaseModel):
    title: str
    price: str
    available: bool


class ProductSummary(BaseModel):
    product_id: int
    title: str
    product_type: str
    status: str
    variants: list[ProductVariant]
    description_snippet: str  # primeros 300 chars del body sin HTML


class CustomerInfo(BaseModel):
    customer_id: int
    email: str
    first_name: str
    last_name: str
    orders_count: int
    total_spent: str  # Shopify devuelve como string decimal


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


def map_order_summary(raw: dict[str, Any]) -> OrderSummary:
    return OrderSummary(
        order_id=raw["id"],
        order_number=raw.get("name", f"#{raw['id']}"),
        financial_status=raw.get("financial_status", ""),
        fulfillment_status=raw.get("fulfillment_status"),
        total_price=raw.get("total_price", "0.00"),
        currency=raw.get("currency", ""),
        created_at=raw.get("created_at", ""),
        tracking_url=first_tracking_url(raw),
    )


def map_product_summary(raw: dict[str, Any]) -> ProductSummary:
    variants = [
        ProductVariant(
            title=v.get("title", ""),
            price=v.get("price", "0.00"),
            available=(v.get("inventory_quantity", 0) or 0) > 0,
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
    )
