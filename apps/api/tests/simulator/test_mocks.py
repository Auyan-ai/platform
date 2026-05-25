"""Tests para MockShopifyAdapter."""

from __future__ import annotations

import pytest
from apps.api.simulator.mocks import MockShopifyAdapter, MockShopifyError


async def test_returns_fixture_when_present() -> None:
    mock = MockShopifyAdapter({"get_order_by_name": {"found": True, "order_number": "#1234"}})
    result = await mock.get_order_by_name(None, "#1234")
    assert result == {"found": True, "order_number": "#1234"}


async def test_lookup_default_is_none_when_no_fixture() -> None:
    mock = MockShopifyAdapter({})
    assert await mock.get_order_by_name(None, "#1") is None
    assert await mock.get_customer_by_email(None, "a@b.com") is None


async def test_list_default_is_empty_when_no_fixture() -> None:
    mock = MockShopifyAdapter({})
    assert await mock.search_orders_by_email(None, "a@b.com") == []
    assert await mock.get_policies(None) == []


async def test_write_default_is_success_dict() -> None:
    mock = MockShopifyAdapter({})
    result = await mock.start_return(None, 1, line_item_id=2, quantity=1)
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
