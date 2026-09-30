"""refund_partial (transacción padre) y start_return (GraphQL returnCreate).

Bugs previos (vistos preparando A4): el reembolso se mandaba con `parent_id: None` +
gateway "manual" (Shopify lo rechaza en un pedido cobrado) y la devolución llamaba a
un recurso REST `orders/{id}/returns.json` que no existe.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

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
async def test_refund_omits_empty_gateway() -> None:
    respx.get(f"{BASE}/orders/1001/transactions.json").respond(
        200, json={"transactions": [{"id": 9, "kind": "sale", "status": "success", "gateway": ""}]}
    )
    refund = respx.post(f"{BASE}/orders/1001/refunds.json").respond(201, json={"refund": {"id": 1}})
    await _client().refund_partial(1001, amount="5.00", currency="USD")
    tx = json.loads(refund.calls.last.request.content)["refund"]["transactions"][0]
    assert tx == {"parent_id": 9, "amount": "5.00", "kind": "refund"}


@respx.mock
async def test_refund_without_payment_raises_and_does_not_post() -> None:
    respx.get(f"{BASE}/orders/1001/transactions.json").respond(200, json={"transactions": []})
    refund = respx.post(f"{BASE}/orders/1001/refunds.json")

    with pytest.raises(ShopifyActionError, match="order_has_no_refundable_payment"):
        await _client().refund_partial(1001, amount="1.00", currency="EUR")
    assert not refund.called


def _reasons(*handles: str) -> dict:
    ids = {"too-small": 7, "damaged-or-defective": 6, "other-reason": 5}
    nodes = [
        {"id": f"gid://shopify/ReturnReasonDefinition/{ids[h]}", "handle": h}
        for h in handles
        if h in ids
    ]
    return {"data": {"returnReasonDefinitions": {"nodes": nodes}}}


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
            httpx.Response(200, json=_reasons("damaged-or-defective", "other-reason")),
            httpx.Response(200, json=created),
        ]
    )

    out = await _client().start_return(
        7404799197464, line_item_id=17457464312088, quantity=1, reason="defective"
    )

    assert out == {"id": 5001, "status": "open", "name": "#1429-R1"}
    first = json.loads(route.calls[0].request.content)
    assert first["variables"] == {"orderId": "gid://shopify/Order/7404799197464"}
    reasons_query = json.loads(route.calls[1].request.content)["variables"]
    assert reasons_query == {"handles": ["damaged-or-defective", "other-reason"]}
    mutation = json.loads(route.calls[2].request.content)["variables"]["input"]
    assert mutation["orderId"] == "gid://shopify/Order/7404799197464"
    item = mutation["returnLineItems"][0]
    assert item["fulfillmentLineItemId"] == "gid://shopify/FulfillmentLineItem/900"
    assert item["quantity"] == 1
    # Shopify exige motivo (visto en A4): definición de su librería + nota libre.
    assert item["returnReasonDefinitionId"] == "gid://shopify/ReturnReasonDefinition/6"
    assert item["returnReasonNote"] == "defective"
    assert "returnReason" not in item  # enum deprecado


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
            httpx.Response(200, json=_reasons("other-reason")),
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


@respx.mock
async def test_unknown_reason_falls_back_to_other() -> None:
    created = {
        "data": {
            "returnCreate": {
                "return": {"id": "gid://shopify/Return/1", "name": "R", "status": "OPEN"},
                "userErrors": [],
            }
        }
    }
    route = respx.post(f"{BASE}/graphql.json").mock(
        side_effect=[
            httpx.Response(200, json=_returnable(5, 1)),
            httpx.Response(200, json=_reasons("other-reason")),
            httpx.Response(200, json=created),
        ]
    )
    await _client().start_return(1, line_item_id=5, quantity=1, reason="no me convence")
    item = json.loads(route.calls[2].request.content)["variables"]["input"]["returnLineItems"][0]
    assert item["returnReasonDefinitionId"] == "gid://shopify/ReturnReasonDefinition/5"


@pytest.mark.parametrize(
    ("reason", "handle"),
    [
        ("size_too_small", "too-small"),
        ("me queda pequeña", "too-small"),
        ("SIZE_TOO_LARGE", "too-big"),
        ("llegó roto", "damaged-or-defective"),
        ("wrong_item", "received-the-wrong-item"),
        ("changed my mind", "changed-my-mind"),
        ("other", "other-reason"),
    ],
)
def test_return_reason_handle(reason: str, handle: str) -> None:
    from apps.api.integrations.shopify import return_reason_handle

    assert return_reason_handle(reason) == handle


# ─── cancel_order (GraphQL orderCancel) ──────────────────────────────────────
# Antes: REST cancel.json con "refund": true → Shopify lo ignoraba y cancelaba sin
# devolver el pago (visto en A4, pedido #1432 quedó `paid`).


def _cancel_ok() -> dict:
    return {
        "data": {
            "orderCancel": {
                "job": {"id": "gid://shopify/Job/1", "done": False},
                "orderCancelUserErrors": [],
            }
        }
    }


@respx.mock
async def test_cancel_with_refund_uses_original_payment_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.api.integrations.shopify.asyncio.sleep", AsyncMock())
    mutation = respx.post(f"{BASE}/graphql.json").respond(200, json=_cancel_ok())
    respx.get(f"{BASE}/orders/1432.json").mock(
        side_effect=[
            httpx.Response(200, json={"order": {"id": 1432, "cancelled_at": None}}),
            httpx.Response(
                200,
                json={
                    "order": {
                        "id": 1432,
                        "cancelled_at": "2026-09-30T10:00:00Z",
                        "financial_status": "refunded",
                    }
                },
            ),
        ]
    )

    order = await _client().cancel_order(1432, reason="customer", email=True, refund=True)

    assert order["financial_status"] == "refunded"
    variables = json.loads(mutation.calls.last.request.content)["variables"]
    assert variables == {
        "orderId": "gid://shopify/Order/1432",
        "reason": "CUSTOMER",
        "restock": True,
        "notifyCustomer": True,
        "refundMethod": {"originalPaymentMethodsRefund": True},
    }


@respx.mock
async def test_cancel_without_refund_and_unknown_reason() -> None:
    mutation = respx.post(f"{BASE}/graphql.json").respond(200, json=_cancel_ok())
    respx.get(f"{BASE}/orders/9.json").respond(
        200, json={"order": {"id": 9, "cancelled_at": "2026-09-30T10:00:00Z"}}
    )

    await _client().cancel_order(9, reason="ya no lo quiero", email=False, refund=False)

    variables = json.loads(mutation.calls.last.request.content)["variables"]
    assert variables["reason"] == "OTHER"
    assert variables["refundMethod"] is None
    assert variables["notifyCustomer"] is False


@respx.mock
async def test_cancel_user_errors_raise_without_polling() -> None:
    respx.post(f"{BASE}/graphql.json").respond(
        200,
        json={
            "data": {
                "orderCancel": {
                    "job": None,
                    "orderCancelUserErrors": [
                        {"field": ["orderId"], "message": "Order already cancelled", "code": "X"}
                    ],
                }
            }
        },
    )
    poll = respx.get(f"{BASE}/orders/9.json")
    with pytest.raises(ShopifyActionError, match="order_cancel_failed"):
        await _client().cancel_order(9, refund=True)
    assert not poll.called


@respx.mock
async def test_cancel_still_processing_reports_not_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el job no termina a tiempo no se afirma la cancelación."""
    monkeypatch.setattr("apps.api.integrations.shopify.asyncio.sleep", AsyncMock())
    respx.post(f"{BASE}/graphql.json").respond(200, json=_cancel_ok())
    respx.get(f"{BASE}/orders/9.json").respond(200, json={"order": {"id": 9, "cancelled_at": None}})
    order = await _client().cancel_order(9, refund=True)
    assert order["cancelled_at"] is None
