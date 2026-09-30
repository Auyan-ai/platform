"""refund_partial (transacción padre) y start_return (GraphQL returnCreate).

Bugs previos (vistos preparando A4): el reembolso se mandaba con `parent_id: None` +
gateway "manual" (Shopify lo rechaza en un pedido cobrado) y la devolución llamaba a
un recurso REST `orders/{id}/returns.json` que no existe.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from apps.api.integrations.shopify import ShopifyActionError, ShopifyClient

BASE = "https://marea.myshopify.com/admin/api/2026-04"


def _client() -> ShopifyClient:
    return ShopifyClient("marea.myshopify.com", "tok")


@respx.mock
async def test_refund_hangs_from_the_successful_sale_transaction() -> None:
    respx.get(f"{BASE}/orders/1001/transactions.json").respond(
        200,
        json={
            "transactions": [
                {"id": 1, "kind": "authorization", "status": "success", "gateway": "bogus"},
                {"id": 2, "kind": "sale", "status": "failure", "gateway": "bogus"},
                {"id": 3, "kind": "sale", "status": "success", "gateway": "bogus"},
            ]
        },
    )
    refund = respx.post(f"{BASE}/orders/1001/refunds.json").respond(
        201, json={"refund": {"id": 77}}
    )

    out = await _client().refund_partial(1001, amount="12.50", currency="EUR", note="n")

    assert out == {"id": 77}
    body = json.loads(refund.calls.last.request.content)["refund"]
    assert body["transactions"] == [
        {"parent_id": 3, "amount": "12.50", "kind": "refund", "gateway": "bogus"}
    ]
    assert body["currency"] == "EUR"


@respx.mock
async def test_refund_without_payment_raises_and_does_not_post() -> None:
    respx.get(f"{BASE}/orders/1001/transactions.json").respond(200, json={"transactions": []})
    refund = respx.post(f"{BASE}/orders/1001/refunds.json")

    with pytest.raises(ShopifyActionError, match="order_has_no_refundable_payment"):
        await _client().refund_partial(1001, amount="1.00", currency="EUR")
    assert not refund.called


def _returnable(line_item: int, qty: int) -> dict:
    return {
        "data": {
            "returnableFulfillments": {
                "nodes": [
                    {
                        "returnableFulfillmentLineItems": {
                            "nodes": [
                                {
                                    "quantity": qty,
                                    "fulfillmentLineItem": {
                                        "id": "gid://shopify/FulfillmentLineItem/900",
                                        "lineItem": {"id": f"gid://shopify/LineItem/{line_item}"},
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        }
    }


@respx.mock
async def test_start_return_uses_graphql_return_create() -> None:
    created = {
        "data": {
            "returnCreate": {
                "return": {"id": "gid://shopify/Return/5001", "name": "#1429-R1", "status": "OPEN"},
                "userErrors": [],
            }
        }
    }
    route = respx.post(f"{BASE}/graphql.json").mock(
        side_effect=[
            httpx.Response(200, json=_returnable(17457464312088, 1)),
            httpx.Response(200, json=created),
        ]
    )

    out = await _client().start_return(
        7404799197464, line_item_id=17457464312088, quantity=1, reason="defective"
    )

    assert out == {"id": 5001, "status": "open", "name": "#1429-R1"}
    first = json.loads(route.calls[0].request.content)
    assert first["variables"] == {"orderId": "gid://shopify/Order/7404799197464"}
    mutation = json.loads(route.calls[1].request.content)["variables"]["input"]
    assert mutation["orderId"] == "gid://shopify/Order/7404799197464"
    item = mutation["returnLineItems"][0]
    assert item["fulfillmentLineItemId"] == "gid://shopify/FulfillmentLineItem/900"
    assert (item["quantity"], item["returnReasonNote"]) == (1, "defective")
    # `returnReason` (enum) está deprecado en 2026-04: no se manda.
    assert "returnReason" not in item


@respx.mock
async def test_unfulfilled_item_is_not_returnable() -> None:
    respx.post(f"{BASE}/graphql.json").respond(
        200, json={"data": {"returnableFulfillments": {"nodes": []}}}
    )
    with pytest.raises(ShopifyActionError, match="line_item_not_returnable"):
        await _client().start_return(1, line_item_id=5, quantity=1)


@respx.mock
async def test_quantity_above_returnable_is_rejected() -> None:
    respx.post(f"{BASE}/graphql.json").respond(200, json=_returnable(5, 1))
    with pytest.raises(ShopifyActionError, match="return_quantity_exceeds_returnable"):
        await _client().start_return(1, line_item_id=5, quantity=2)


@respx.mock
async def test_user_errors_and_graphql_errors_raise() -> None:
    respx.post(f"{BASE}/graphql.json").mock(
        side_effect=[
            httpx.Response(200, json=_returnable(5, 1)),
            httpx.Response(
                200,
                json={
                    "data": {
                        "returnCreate": {
                            "return": None,
                            "userErrors": [{"field": ["x"], "message": "nope"}],
                        }
                    }
                },
            ),
        ]
    )
    with pytest.raises(ShopifyActionError, match="return_create_failed"):
        await _client().start_return(1, line_item_id=5, quantity=1)

    respx.post(f"{BASE}/graphql.json").respond(
        200, json={"errors": [{"message": "Access denied for returnableFulfillments"}]}
    )
    with pytest.raises(ShopifyActionError, match="graphql_errors"):
        await _client().start_return(1, line_item_id=5, quantity=1)
