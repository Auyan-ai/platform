"""Lecturas y escrituras de devoluciones en la Admin API 2026-04 (ADR 0014).

Las respuestas imitan las leídas de Marea el 2026-10-18 (pedidos #1431 y #1042).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from apps.api.integrations.shopify import ShopifyActionError, ShopifyClient, return_input
from apps.api.services.returns import (
    PlanExchangeLine,
    PlanLine,
    ReturnPlan,
    Settlement,
    SettlementLine,
)
from apps.api.services.returns_policy import Money

BASE = "https://marea.myshopify.com/admin/api/2026-04"
GQL = f"{BASE}/graphql.json"


def _client() -> ShopifyClient:
    return ShopifyClient("marea.myshopify.com", "tok")


def _returnable_order() -> dict[str, Any]:
    return {
        "data": {
            "order": {
                "id": "gid://shopify/Order/7133801513240",
                "name": "#1042",
                "processedAt": "2026-05-29T15:03:00Z",
                "cancelledAt": None,
                "taxesIncluded": True,
                "presentmentCurrencyCode": "EUR",
            },
            "returnableFulfillments": {
                "nodes": [
                    {
                        "fulfillment": {
                            "createdAt": "2026-05-30T22:35:43Z",
                            "deliveredAt": None,
                        },
                        "returnableFulfillmentLineItems": {
                            "nodes": [
                                {
                                    "quantity": 2,
                                    "fulfillmentLineItem": {
                                        "id": "gid://shopify/FulfillmentLineItem/14699305337112",
                                        "lineItem": {
                                            "id": "gid://shopify/LineItem/16984114200856",
                                            "name": "Blusa Estampada Floral - Marino / XS",
                                            "title": "Blusa Estampada Floral",
                                            "product": None,
                                        },
                                    },
                                },
                                {
                                    "quantity": 1,
                                    "fulfillmentLineItem": {
                                        "id": "gid://shopify/FulfillmentLineItem/15106785509656",
                                        "lineItem": {
                                            "id": "gid://shopify/LineItem/17463441195288",
                                            "name": "Bolso Bandolera - Marino",
                                            "title": "Bolso Bandolera",
                                            "product": {
                                                "id": "gid://shopify/Product/10287987851544",
                                                "tags": ["básicos", "rebajas"],
                                            },
                                        },
                                    },
                                },
                            ]
                        },
                    }
                ]
            },
        }
    }


@respx.mock
async def test_returnable_order_parses_lines_dates_and_tags() -> None:
    route = respx.post(GQL).respond(200, json=_returnable_order())

    order = await _client().get_returnable_order(7133801513240)

    assert json.loads(route.calls[0].request.content)["variables"] == {
        "orderId": "gid://shopify/Order/7133801513240"
    }
    assert (order.order_id, order.name, order.currency, order.taxes_included) == (
        7133801513240,
        "#1042",
        "EUR",
        True,
    )
    blouse, bag = order.lines
    assert blouse.line_item_id == 16984114200856
    assert blouse.title == "Blusa Estampada Floral - Marino / XS"
    assert blouse.returnable_quantity == 2
    assert (blouse.product_id, blouse.product_tags) == (None, None)
    assert blouse.shipped_at == datetime(2026, 5, 30, 22, 35, 43, tzinfo=UTC)
    assert blouse.delivered_at is None
    assert bag.product_id == 10287987851544
    assert bag.product_tags == frozenset({"básicos", "rebajas"})


@respx.mock
async def test_missing_order_raises() -> None:
    respx.post(GQL).respond(
        200, json={"data": {"order": None, "returnableFulfillments": {"nodes": []}}}
    )

    with pytest.raises(ShopifyActionError, match="order_not_found"):
        await _client().get_returnable_order(1)


@respx.mock
async def test_exchange_variants_skip_unknown_ids() -> None:
    route = respx.post(GQL).respond(
        200,
        json={
            "data": {
                "nodes": [
                    {
                        "id": "gid://shopify/ProductVariant/52117802090776",
                        "displayName": "Bolso Bandolera - Caqui",
                        "availableForSale": True,
                        "product": {"id": "gid://shopify/Product/10287987851544"},
                    },
                    None,
                ]
            }
        },
    )

    variants = await _client().get_exchange_variants([52117802090776, 1])

    assert json.loads(route.calls[0].request.content)["variables"]["ids"] == [
        "gid://shopify/ProductVariant/52117802090776",
        "gid://shopify/ProductVariant/1",
    ]
    assert [(v.variant_id, v.product_id, v.title, v.available) for v in variants] == [
        (52117802090776, 10287987851544, "Bolso Bandolera - Caqui", True)
    ]


@respx.mock
async def test_return_calculation_keeps_presentment_amounts() -> None:
    route = respx.post(GQL).respond(
        200,
        json={
            "data": {
                "returnCalculate": {
                    "returnLineItems": [
                        {
                            "quantity": 1,
                            "fulfillmentLineItem": {
                                "id": "gid://shopify/FulfillmentLineItem/14699305337112"
                            },
                            "subtotalSet": {
                                "presentmentMoney": {"amount": "-52.15", "currencyCode": "EUR"}
                            },
                            "totalTaxSet": {
                                "presentmentMoney": {"amount": "-9.05", "currencyCode": "EUR"}
                            },
                        }
                    ],
                    "exchangeLineItems": [],
                }
            }
        },
    )

    calc = await _client().calculate_return(
        7133801513240,
        lines=[("gid://shopify/FulfillmentLineItem/14699305337112", 1)],
        exchange=[],
    )

    sent = json.loads(route.calls[0].request.content)["variables"]["input"]
    assert sent == {
        "orderId": "gid://shopify/Order/7133801513240",
        "returnLineItems": [
            {
                "fulfillmentLineItemId": "gid://shopify/FulfillmentLineItem/14699305337112",
                "quantity": 1,
            }
        ],
        "exchangeLineItems": [],
    }
    assert calc.currency == "EUR"
    assert calc.returned[0].subtotal == Decimal("-52.15")
    assert calc.returned[0].tax == Decimal("-9.05")


def _plan(**overrides: Any) -> ReturnPlan:
    base: dict[str, Any] = {
        "policy_version": 3,
        "requested_at": datetime(2026, 10, 18, 10, 0, tzinfo=UTC),
        "order_id": 7409804542232,
        "order_name": "#1431",
        "reason_code": "wrong_colour",
        "reason_label": "Color distinto",
        "fault": "customer",
        "shopify_reason": "color",
        "lines": (
            PlanLine(
                line_item_id=17463441195288,
                fulfillment_line_item_id="gid://shopify/FulfillmentLineItem/15106785509656",
                title="Bolso Bandolera - Marino",
                quantity=1,
            ),
        ),
        "exchange_lines": (
            PlanExchangeLine(
                variant_id=52117802090776, title="Bolso Bandolera - Caqui", quantity=1
            ),
        ),
        "evidence": (),
        "shipping_method": "store_label",
        "return_address": None,
        "refund_days": 14,
        "ship_replacement": None,
        "requires_approval": True,
        "settlement": Settlement(
            currency="USD",
            returned=(SettlementLine(title="Bolso", quantity=1, amount=Decimal("76.95")),),
            exchanged=(SettlementLine(title="Bolso", quantity=1, amount=Decimal("76.95")),),
            shipping_payer="customer",
            fee=Decimal("4.95"),
            fee_pending=None,
            restocking_percent=Decimal("0"),
            restocking_fee=Decimal("0"),
            price_rule="none",
            refund_as="original_payment",
        ),
    }
    base.update(overrides)
    return ReturnPlan(**base)


def test_return_input_carries_exchange_fee_and_request_time() -> None:
    assert return_input(_plan(), "gid://shopify/ReturnReasonDefinition/9") == {
        "orderId": "gid://shopify/Order/7409804542232",
        "requestedAt": "2026-10-18T10:00:00+00:00",
        "returnLineItems": [
            {
                "fulfillmentLineItemId": "gid://shopify/FulfillmentLineItem/15106785509656",
                "quantity": 1,
                "returnReasonDefinitionId": "gid://shopify/ReturnReasonDefinition/9",
                "returnReasonNote": "Color distinto [wrong_colour]",
            }
        ],
        "exchangeLineItems": [
            {"variantId": "gid://shopify/ProductVariant/52117802090776", "quantity": 1}
        ],
        "returnShippingFee": {"amount": {"amount": "4.95", "currencyCode": "USD"}},
    }


def test_return_input_omits_fee_left_to_the_team() -> None:
    plan = _plan(
        exchange_lines=(),
        settlement=Settlement(
            currency="USD",
            returned=(SettlementLine(title="Bolso", quantity=1, amount=Decimal("76.95")),),
            exchanged=(),
            shipping_payer="customer",
            fee=Decimal("0"),
            fee_pending=Money(amount=Decimal("4.95"), currency="EUR"),
            restocking_percent=Decimal("0"),
            restocking_fee=Decimal("0"),
            price_rule="none",
            refund_as="original_payment",
        ),
    )

    payload = return_input(plan, "gid://shopify/ReturnReasonDefinition/9")

    assert "returnShippingFee" not in payload
    assert "exchangeLineItems" not in payload


@respx.mock
async def test_create_return_uses_the_store_reason_or_falls_back_to_other() -> None:
    created = {
        "data": {
            "returnCreate": {
                "return": {"id": "gid://shopify/Return/5001", "name": "#1431-R2", "status": "OPEN"},
                "userErrors": [],
            }
        }
    }
    route = respx.post(GQL).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": {
                        "returnReasonDefinitions": {
                            "nodes": [
                                {
                                    "id": "gid://shopify/ReturnReasonDefinition/5",
                                    "handle": "other-reason",
                                }
                            ]
                        }
                    }
                },
            ),
            httpx.Response(200, json=created),
        ]
    )

    out = await _client().create_return(_plan())

    assert json.loads(route.calls[0].request.content)["variables"] == {
        "handles": ["color", "other-reason"]
    }
    mutation = json.loads(route.calls[1].request.content)["variables"]["input"]
    assert mutation["returnLineItems"][0]["returnReasonDefinitionId"] == (
        "gid://shopify/ReturnReasonDefinition/5"
    )
    assert (out.return_id, out.name, out.status, out.reason_handle) == (
        5001,
        "#1431-R2",
        "open",
        "other-reason",
    )


@respx.mock
async def test_create_return_user_errors_raise() -> None:
    respx.post(GQL).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": {
                        "returnReasonDefinitions": {
                            "nodes": [
                                {"id": "gid://shopify/ReturnReasonDefinition/1", "handle": "color"}
                            ]
                        }
                    }
                },
            ),
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
        await _client().create_return(_plan())


@respx.mock
async def test_append_order_note_keeps_the_existing_note() -> None:
    respx.get(f"{BASE}/orders/7409804542232.json").respond(
        200, json={"order": {"id": 7409804542232, "note": "Cliente VIP"}}
    )
    put = respx.put(f"{BASE}/orders/7409804542232.json").respond(
        200, json={"order": {"id": 7409804542232}}
    )

    await _client().append_order_note(7409804542232, "Auyan · devolución")

    assert json.loads(put.calls[0].request.content)["order"]["note"] == (
        "Cliente VIP\n\nAuyan · devolución"
    )


def test_return_input_sends_the_restocking_percentage() -> None:
    plan = _plan()
    plan = plan.model_copy(
        update={
            "settlement": plan.settlement.model_copy(update={"restocking_percent": Decimal("10")})
        }
    )

    line = return_input(plan, "gid://shopify/ReturnReasonDefinition/9")["returnLineItems"][0]

    assert line["restockingFee"] == {"percentage": 10.0}
