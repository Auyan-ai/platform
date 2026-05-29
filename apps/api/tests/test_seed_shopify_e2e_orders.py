"""Tests unitarios del seed de órdenes Shopify 0.11A."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apps.api.scripts import seed_shopify_e2e_orders as script


def test_has_tag_parses_comma_separated_tags() -> None:
    assert script._has_tag({"tags": "foo, auyan-e2e, bar"}, "auyan-e2e") is True
    assert script._has_tag({"tags": "foo,bar"}, "auyan-e2e") is False


def test_scenario_id_reads_note_attributes() -> None:
    order = {
        "note_attributes": [
            {"name": "other", "value": "x"},
            {"name": script.SCENARIO_ATTR, "value": "CE-TRACKING"},
        ]
    }

    assert script._scenario_id(order) == "CE-TRACKING"


def test_build_order_payload_is_tagged_and_email_safe() -> None:
    seed = script.SEED_ORDERS[0]

    payload = script._build_order_payload(seed, tag="auyan-e2e", location_id=123)

    assert payload["email"] == "laura.gomez+auyan-e2e@example.com"
    assert payload["financial_status"] == "paid"
    assert payload["fulfillment_status"] == "fulfilled"
    assert payload["fulfillments"] == [{"location_id": 123}]
    assert payload["tags"] == "auyan-e2e, CE-TRACKING"
    assert payload["note_attributes"] == [
        {"name": script.SCENARIO_ATTR, "value": "CE-TRACKING"},
        {"name": "auyan_e2e", "value": "true"},
    ]
    assert payload["line_items"][0]["title"] == "Collar Luna Plata"
    assert payload["billing_address"]["first_name"] == "Laura"
    assert payload["shipping_address"]["last_name"] == "Gomez"


def test_unfulfilled_payload_has_no_fulfillments() -> None:
    seed = script.SEED_ORDERS[1]

    payload = script._build_order_payload(seed, tag="auyan-e2e", location_id=123)

    assert "fulfillment_status" not in payload
    assert "fulfillments" not in payload


def test_summary_returns_tracking_numbers() -> None:
    order = {
        "id": 1,
        "name": "#1001",
        "email": "x@example.com",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "note_attributes": [{"name": script.SCENARIO_ATTR, "value": "CE-TRACKING"}],
        "fulfillments": [{"tracking_number": "1Z999"}],
    }

    assert script._summary(order) == {
        "id": 1,
        "name": "#1001",
        "email": "x@example.com",
        "scenario_id": "CE-TRACKING",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "tracking_numbers": ["1Z999"],
    }


def test_needs_tracking_repair() -> None:
    seed = script.SEED_ORDERS[0]

    assert script._needs_tracking_repair({"fulfillments": []}, seed) is True
    assert (
        script._needs_tracking_repair(
            {"fulfillments": [{"tracking_number": seed.tracking_number}]},
            seed,
        )
        is False
    )


@pytest.mark.asyncio
async def test_primary_location_id_returns_none_on_forbidden() -> None:
    response = MagicMock()
    response.status_code = 403
    response.raise_for_status = MagicMock()

    http_client = AsyncMock()
    http_client.get = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=http_client)
    context.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.api.scripts.seed_shopify_e2e_orders.httpx.AsyncClient", return_value=context):
        result = await script.ShopifySeedClient("x.myshopify.com", "tok").primary_location_id()

    assert result is None
    response.raise_for_status.assert_not_called()
