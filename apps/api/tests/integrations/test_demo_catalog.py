"""DemoCatalogAdapter contra respuestas grabadas de thinkingmu.com (Storefront API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.demo_catalog import (
    BOT_USER_AGENT,
    DemoCatalogAdapter,
    DemoCatalogError,
    DemoCatalogUnavailable,
    normalize_domain,
)
from apps.api.skills.base import SkillContext
from apps.api.skills.shopify.get_product_info import GetProductInfo, GetProductInfoInput

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "thinkingmu_storefront.json").read_text()
)
TENANT = "11111111-1111-1111-1111-111111111111"


def _recorded_handler(seen: list[httpx.Request]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        query = json.loads(request.content)["query"]
        key = "shop_currency" if "paymentSettings" in query else "search_tere"
        return httpx.Response(200, json=FIXTURE[key])

    return handler


def _adapter(handler: Any, **kwargs: Any) -> DemoCatalogAdapter:
    return DemoCatalogAdapter("thinkingmu.com", transport=httpx.MockTransport(handler), **kwargs)


async def test_search_returns_rest_shape_with_per_variant_availability_and_tags() -> None:
    seen: list[httpx.Request] = []
    adapter = _adapter(_recorded_handler(seen))

    products = await adapter.search_products(None, "Tere")

    top = products[0]
    assert top["title"] == "Top naranja Esqué Tere"
    assert top["id"] == 15075579658566
    assert top["tags"].count("Poliéster Reciclado") == 1
    assert [(v["title"], v["available"]) for v in top["variants"]] == [
        ("XS", True),
        ("S", False),
        ("M", False),
        ("L", True),
        ("XL", False),
    ]
    assert top["variants"][0]["price"] == "64.9"
    assert await adapter.get_shop_currency(None) == "EUR"


async def test_requests_identify_as_auyanbot_on_the_public_storefront_endpoint() -> None:
    seen: list[httpx.Request] = []
    adapter = _adapter(_recorded_handler(seen))

    await adapter.search_products(None, "Tere")

    assert str(seen[0].url) == "https://thinkingmu.com/api/2025-07/graphql.json"
    assert seen[0].headers["User-Agent"] == BOT_USER_AGENT == "AuyanBot/0.1 (+https://auyan.ai/bot)"
    assert "X-Shopify-Storefront-Access-Token" not in seen[0].headers
    assert "Authorization" not in seen[0].headers


async def test_get_product_info_reports_sold_out_variant_as_unavailable() -> None:
    adapter = _adapter(_recorded_handler([]))
    ctx = SkillContext(
        tenant_id=TENANT,
        conversation_id="c",
        integration_ctx=IntegrationContext(UUID(TENANT), {}, {}),
        commerce_mock=adapter,
    )

    out = await GetProductInfo().execute(ctx, GetProductInfoInput(query="Tere"))

    top = out.products[0]  # type: ignore[attr-defined]
    availability = {v.title: v.available for v in top.variants}
    assert availability == {"XS": True, "S": False, "M": False, "L": True, "XL": False}
    assert top.variants[0].price.model_dump() == {"amount": "64.9", "currency": "EUR"}
    assert "Poliéster Reciclado" in top.tags


async def test_429_with_retry_after_retries_then_succeeds() -> None:
    calls = 0
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=FIXTURE["search_tere"])

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    adapter = _adapter(handler, sleep=fake_sleep)

    products = await adapter.search_products(None, "Tere")

    assert calls == 2
    assert slept == [2.0]
    assert products[0]["title"] == "Top naranja Esqué Tere"


async def test_429_gives_up_after_bounded_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "1"})

    async def no_sleep(seconds: float) -> None:
        return None

    with pytest.raises(DemoCatalogError, match="rate_limited"):
        await _adapter(handler, sleep=no_sleep).search_products(None, "Tere")
    assert calls == 3


async def test_429_with_retry_after_beyond_the_cap_is_not_waited_for() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "600"})

    with pytest.raises(DemoCatalogError, match="rate_limited"):
        await _adapter(handler).search_products(None, "Tere")


@pytest.mark.parametrize(
    "method",
    [
        "get_order_by_name",
        "get_order",
        "search_orders_by_email",
        "cancel_order",
        "update_shipping_address",
        "refund_partial",
        "create_return",
        "get_policies",
    ],
)
async def test_order_and_write_methods_raise_typed_unavailable(method: str) -> None:
    adapter = _adapter(lambda request: httpx.Response(500))

    with pytest.raises(DemoCatalogUnavailable, match=method):
        await getattr(adapter, method)(None, "1234")


async def test_order_lookup_through_skill_layer_becomes_commerce_unavailable() -> None:
    from apps.api.services.identity_guest import OrderLookupError, lookup_order

    ctx = SkillContext(
        tenant_id=TENANT,
        conversation_id="c",
        integration_ctx=IntegrationContext(UUID(TENANT), {}, {}),
        commerce_mock=_adapter(lambda request: httpx.Response(500)),
    )

    with pytest.raises(OrderLookupError, match="DemoCatalogUnavailable"):
        await lookup_order(ctx, "1234")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Thinkingmu.com/", "thinkingmu.com"),
        ("thinkingmu.com/products/x", "thinkingmu.com"),
    ],
)
def test_normalize_domain(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("bad", ["", "evil.com@x", "a b.com", "localhost:8080"])
def test_normalize_domain_rejects_non_hostnames(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid_store_domain"):
        normalize_domain(bad)
