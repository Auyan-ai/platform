"""Pedidos de prueba con la forma del `order` de `_ORDER_SNAPSHOT_QUERY` de Shopify."""

from __future__ import annotations

from typing import Any

from apps.api.integrations.shopify import OrderSnapshot, order_snapshot_from_graphql


def tx(
    tx_id: int,
    kind: str,
    status: str = "SUCCESS",
    *,
    gateway: str | None = "shopify_payments",
    manual: bool = False,
    error_code: str | None = None,
) -> dict[str, Any]:
    return {
        "id": f"gid://shopify/OrderTransaction/{tx_id}",
        "kind": kind,
        "status": status,
        "gateway": gateway,
        "manualPaymentGateway": manual,
        "errorCode": error_code,
    }


CARD_SALE = tx(1, "SALE")
MANUAL_SALE = tx(1, "SALE", gateway=None, manual=True)


def order_node(
    *,
    order_id: int = 1001,
    cancelled: bool = False,
    fulfillment_status: str = "UNFULFILLED",
    fulfillments: list[dict[str, Any]] | None = None,
    transactions: list[dict[str, Any]] | None = None,
    address: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"gid://shopify/Order/{order_id}",
        "name": "#1500",
        "cancelledAt": "2026-10-12T10:00:00Z" if cancelled else None,
        "displayFulfillmentStatus": fulfillment_status,
        "shippingAddress": address,
        "fulfillments": fulfillments or [],
        "transactions": transactions or [],
    }


def snapshot(**kwargs: Any) -> OrderSnapshot:
    return order_snapshot_from_graphql(order_node(**kwargs))
