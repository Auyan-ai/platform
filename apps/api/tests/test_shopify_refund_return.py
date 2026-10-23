"""refund_partial (transacción padre) y start_return (GraphQL returnCreate).

Bugs previos (vistos preparando A4): el reembolso se mandaba con `parent_id: None` +
gateway "manual" (Shopify lo rechaza en un pedido cobrado) y la devolución llamaba a
un recurso REST `orders/{id}/returns.json` que no existe.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from apps.api.integrations.base import MutationNotApplied
from apps.api.integrations.shopify import (
    IssuedRefund,
    RefundableBalance,
    ShopifyActionError,
    ShopifyClient,
    refundable_balance,
)

BASE = "https://marea.myshopify.com/admin/api/2026-04"


def _client() -> ShopifyClient:
    return ShopifyClient("marea.myshopify.com", "tok")


def _sale(tx_id: int, amount: str, currency: str = "GBP", **extra: str) -> dict:
    return {
        "id": tx_id,
        "kind": "sale",
        "status": "success",
        "amount": amount,
        "currency": currency,
        "gateway": "bogus",
        **extra,
    }


KEY = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_CREATED = {
    "data": {"refundCreate": {"refund": {"id": "gid://shopify/Refund/77", "legacyResourceId": "77"},
                              "userErrors": []}}
}


@respx.mock
async def test_refund_hangs_from_the_sale_and_carries_the_idempotency_key() -> None:
    respx.get(f"{BASE}/orders/1001/transactions.json").respond(
        200,
        json={
            "transactions": [
                {"id": 1, "kind": "authorization", "status": "success", "gateway": "bogus"},
                {"id": 2, "kind": "sale", "status": "failure", "gateway": "bogus"},
                _sale(3, "45.00"),
            ]
        },
    )
    graphql = respx.post(f"{BASE}/graphql.json").respond(200, json=_CREATED)

    out = await _client().refund_partial(
        1001, amount=Decimal("12.50"), note="n", idempotency_key=KEY
    )

    assert out == IssuedRefund(refund_id=77, amount=Decimal("12.50"), currency="GBP")
    body = json.loads(graphql.calls.last.request.content)
    assert "refundCreate(input: $input) @idempotent(key: $idempotencyKey)" in body["query"]
    assert body["variables"] == {
        "idempotencyKey": KEY,
        "input": {
            "orderId": "gid://shopify/Order/1001",
            "currency": "GBP",
            "note": f"n [auyan:{KEY}]",
            "transactions": [
                {
                    "orderId": "gid://shopify/Order/1001",
                    "parentId": "gid://shopify/OrderTransaction/3",
                    "amount": "12.50",
                    "gateway": "bogus",
                    "kind": "REFUND",
                }
            ],
        },
    }


@respx.mock
async def test_refund_retries_a_lost_response_with_the_same_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.api.integrations.shopify._IDEMPOTENT_RETRY_SECONDS", 0)
    respx.get(f"{BASE}/orders/1001/transactions.json").respond(
        200, json={"transactions": [_sale(3, "45.00")]}
    )
    graphql = respx.post(f"{BASE}/graphql.json").mock(
        side_effect=[httpx.ReadTimeout("lost"), httpx.Response(502), httpx.Response(200, json=_CREATED)]
    )

    out = await _client().refund_partial(1001, amount=Decimal("5"), idempotency_key=KEY)

    assert out.refund_id == 77
    keys = [json.loads(c.request.content)["variables"]["idempotencyKey"] for c in graphql.calls]
    assert keys == [KEY, KEY, KEY]


@respx.mock
async def test_refund_user_errors_raise_without_retrying() -> None:
    respx.get(f"{BASE}/orders/1001/transactions.json").respond(
        200, json={"transactions": [_sale(3, "45.00")]}
    )
    graphql = respx.post(f"{BASE}/graphql.json").respond(
        200,
        json={"data": {"refundCreate": {"refund": None,
                                        "userErrors": [{"field": None, "message": "nope"}]}}},
    )

    with pytest.raises(MutationNotApplied, match="refund_create_failed"):
        await _client().refund_partial(1001, amount=Decimal("5"), idempotency_key=KEY)
    assert graphql.call_count == 1


@respx.mock
async def test_find_refund_matches_the_marker_in_the_note() -> None:
    def _refund(legacy: str, note: str | None) -> dict:
        return {
            "legacyResourceId": legacy,
            "note": note,
            "totalRefundedSet": {"presentmentMoney": {"amount": "5.0", "currencyCode": "EUR"}},
            "transactions": {"nodes": [
                {"id": "gid://shopify/OrderTransaction/9", "kind": "REFUND", "status": "SUCCESS",
                 "gateway": "shopify_payments", "manualPaymentGateway": False, "errorCode": None}
            ]},
        }

    respx.post(f"{BASE}/graphql.json").respond(
        200,
        json={"data": {"order": {"refunds": [
            _refund("70", "a mano"),
            _refund("71", None),
            _refund("72", f"talla [auyan:{KEY}]"),
        ]}}},
    )

    found = await _client().find_refund(1001, KEY)

    assert found is not None
    assert (found.refund_id, found.amount, found.currency) == (72, Decimal("5.0"), "EUR")
    assert [(t.kind, t.status) for t in found.transactions] == [("refund", "success")]


@respx.mock
async def test_find_refund_returns_none_without_the_marker() -> None:
    respx.post(f"{BASE}/graphql.json").respond(200, json={"data": {"order": {"refunds": []}}})
    assert await _client().find_refund(1001, KEY) is None


@respx.mock
async def test_refund_without_payment_raises_and_does_not_post() -> None:
    respx.get(f"{BASE}/orders/1001/transactions.json").respond(200, json={"transactions": []})
    refund = respx.post(f"{BASE}/graphql.json")

    with pytest.raises(MutationNotApplied, match="order_has_no_refundable_payment"):
        await _client().refund_partial(1001, amount=Decimal("1.00"), idempotency_key=KEY)
    assert not refund.called


@respx.mock
async def test_refund_above_what_is_left_is_rejected_and_not_posted() -> None:
    respx.get(f"{BASE}/orders/1001/transactions.json").respond(
        200,
        json={
            "transactions": [
                _sale(3, "45.00"),
                {"id": 4, "kind": "refund", "status": "success", "amount": "30.00",
                 "currency": "GBP", "parent_id": 3},
            ]
        },
    )
    refund = respx.post(f"{BASE}/graphql.json")

    with pytest.raises(
        MutationNotApplied,
        match="refund_amount_exceeds_refundable: .*20.00 GBP .*solo quedan 15.00 GBP",
    ):
        await _client().refund_partial(1001, amount=Decimal("20.00"), idempotency_key=KEY)
    assert not refund.called


def test_refundable_balance_is_captured_minus_refunded_in_presentment_currency() -> None:
    balance = refundable_balance(
        [
            {"id": 1, "kind": "authorization", "status": "success", "amount": "99.00",
             "currency": "GBP"},
            {"id": 2, "kind": "capture", "status": "success", "amount": "45.00",
             "currency": "GBP"},
            {"id": 3, "kind": "refund", "status": "failure", "amount": "45.00",
             "currency": "GBP"},
            {"id": 4, "kind": "refund", "status": "success", "amount": "10.00",
             "currency": "GBP"},
        ]
    )
    assert balance == RefundableBalance(
        captured=Decimal("45.00"), refunded=Decimal("10.00"), currency="GBP"
    )
    assert balance.remaining == Decimal("35.00")


def test_refundable_balance_rejects_mixed_currencies() -> None:
    with pytest.raises(ShopifyActionError, match="order_transactions_currency_ambiguous"):
        refundable_balance([_sale(1, "10.00", "GBP"), _sale(2, "10.00", "EUR")])


def test_refund_amount_must_be_positive() -> None:
    balance = RefundableBalance(captured=Decimal("10"), refunded=Decimal("0"), currency="GBP")
    with pytest.raises(ShopifyActionError, match="refund_amount_not_positive"):
        balance.require(Decimal("0"))


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

    order = await _client().cancel_order(
        1432, reason="customer", email=True, refund=True, restock=True
    )

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

    await _client().cancel_order(
        9, reason="ya no lo quiero", email=False, refund=False, restock=False
    )

    variables = json.loads(mutation.calls.last.request.content)["variables"]
    assert variables["reason"] == "OTHER"
    assert variables["restock"] is False
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
    with pytest.raises(MutationNotApplied, match="order_cancel_failed"):
        await _client().cancel_order(9, refund=True, restock=True)
    assert not poll.called


@respx.mock
async def test_cancel_still_processing_reports_not_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el job no termina a tiempo no se afirma la cancelación."""
    monkeypatch.setattr("apps.api.integrations.shopify.asyncio.sleep", AsyncMock())
    respx.post(f"{BASE}/graphql.json").respond(200, json=_cancel_ok())
    respx.get(f"{BASE}/orders/9.json").respond(200, json={"order": {"id": 9, "cancelled_at": None}})
    order = await _client().cancel_order(9, refund=True, restock=True)
    assert order["cancelled_at"] is None


_ADDRESS = {"address1": "Calle Nueva 42", "city": "Madrid", "province": "M", "country": None,
            "zip_code": "28001"}


@respx.mock
async def test_address_rejected_by_shopify_is_not_applied() -> None:
    respx.put(f"{BASE}/orders/9.json").respond(422, json={"errors": {"zip": ["invalid"]}})
    with pytest.raises(MutationNotApplied):
        await _client().update_shipping_address(9, **_ADDRESS)


@respx.mock
async def test_address_server_error_is_not_marked_not_applied() -> None:
    respx.put(f"{BASE}/orders/9.json").respond(503)
    with pytest.raises(httpx.HTTPStatusError) as raised:
        await _client().update_shipping_address(9, **_ADDRESS)
    assert not isinstance(raised.value, MutationNotApplied)
