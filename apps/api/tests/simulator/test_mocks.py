"""Tests para MockShopifyAdapter."""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.integrations.shopify import IssuedRefund, ShopifyActionError
from apps.api.simulator.mocks import MockShopifyAdapter, MockShopifyError

_GBP_BALANCE = {"get_refundable_balance": {"captured": "45.00", "refunded": "5.00", "currency": "GBP"}}


async def test_returns_fixture_when_present() -> None:
    mock = MockShopifyAdapter({"get_order_by_name": {"found": True, "order_number": "#1234"}})
    result = await mock.get_order_by_name(None, "#1234")
    assert result == {"found": True, "order_number": "#1234"}


async def test_lookup_default_is_none_when_no_fixture() -> None:
    mock = MockShopifyAdapter({})
    assert await mock.get_order_by_name(None, "#1") is None


async def test_list_default_is_empty_when_no_fixture() -> None:
    mock = MockShopifyAdapter({})
    assert await mock.search_orders_by_email(None, "a@b.com") == []
    assert await mock.search_orders_by_phone(None, "+34600111222") == []
    assert await mock.get_policies(None) == []


async def test_write_default_is_success_dict() -> None:
    mock = MockShopifyAdapter({})
    result = await mock.tag_order(None, 1, ["vip"])
    assert result["ok"] is True
    assert result["simulated"] is True


async def test_error_fixture_raises() -> None:
    mock = MockShopifyAdapter({"get_order_by_name": {"_error": "NOT_FOUND"}})
    with pytest.raises(MockShopifyError, match="NOT_FOUND"):
        await mock.get_order_by_name(None, "#9999")


async def test_search_orders_returns_fixture_list() -> None:
    mock = MockShopifyAdapter({"search_orders_by_email": [{"id": 1}, {"id": 2}]})
    result = await mock.search_orders_by_email(None, "a@b.com")
    assert len(result) == 2


async def test_shop_currency_is_never_assumed() -> None:
    assert await MockShopifyAdapter({}).get_shop_currency(None) is None
    assert await MockShopifyAdapter({"get_shop_currency": "USD"}).get_shop_currency(None) == "USD"


async def test_refund_without_balance_fixture_has_no_refundable_payment() -> None:
    with pytest.raises(MockShopifyError, match="order_has_no_refundable_payment"):
        await MockShopifyAdapter({}).refund_partial(None, 1, amount=Decimal("1.00"))


async def test_refund_uses_the_order_currency_from_the_balance() -> None:
    mock = MockShopifyAdapter({**_GBP_BALANCE, "refund_partial": {"id": 9}})
    refund = await mock.refund_partial(None, 1, amount=Decimal("40.00"))
    assert refund == IssuedRefund(refund_id=9, amount=Decimal("40.00"), currency="GBP")


async def test_refund_above_refundable_is_rejected_like_the_real_adapter() -> None:
    with pytest.raises(ShopifyActionError, match="refund_amount_exceeds_refundable"):
        await MockShopifyAdapter(_GBP_BALANCE).refund_partial(None, 1, amount=Decimal("40.01"))


_TWO_LISTED = {
    "search_orders_by_email": [
        {"id": 1001, "name": "#1234", "fulfillment_status": "fulfilled"},
        {"id": 1002, "name": "#1235", "fulfillment_status": "unfulfilled"},
    ]
}


async def test_listed_order_is_found_by_name_like_shopify() -> None:
    mock = MockShopifyAdapter(_TWO_LISTED)
    assert await mock.get_order_by_name(None, "#1235") == {
        "id": 1002,
        "name": "#1235",
        "fulfillment_status": "unfulfilled",
    }
    assert (await mock.get_order_by_name(None, "1234"))["id"] == 1001


async def test_listed_order_is_found_by_id_and_unknown_refs_are_not() -> None:
    mock = MockShopifyAdapter(_TWO_LISTED)
    assert (await mock.get_order(None, "1002"))["name"] == "#1235"
    assert await mock.get_order(None, "#1235") is None
    assert await mock.get_order_by_name(None, "#9999") is None


async def test_explicit_single_order_fixture_wins_over_the_lists() -> None:
    single = {"id": 7, "name": "#1234", "fulfillments": [{"tracking_number": "1Z"}]}
    mock = MockShopifyAdapter({**_TWO_LISTED, "get_order_by_name": single})
    assert await mock.get_order_by_name(None, "#1234") == single


async def test_return_methods_parse_fixtures_like_the_real_adapter() -> None:
    from apps.api.simulator.scenarios.returns import _ORDER_IN_WINDOW

    mock = MockShopifyAdapter(_ORDER_IN_WINDOW)

    order = await mock.get_returnable_order(None, 1234)
    calc = await mock.calculate_return(None, order.order_id, lines=[], exchange=[])

    assert (order.name, order.lines[0].line_item_id, order.lines[0].title) == (
        "#1234",
        5001,
        "Camiseta azul L",
    )
    assert calc.returned[0].subtotal == Decimal("-29.99")
    assert await mock.get_exchange_variants(None, [1]) == ()


async def test_returnable_order_without_fixture_is_an_error() -> None:
    with pytest.raises(MockShopifyError, match="order_not_found"):
        await MockShopifyAdapter({}).get_returnable_order(None, 1)
