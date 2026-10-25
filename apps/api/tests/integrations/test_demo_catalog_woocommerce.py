"""WooCommerceDemoCatalogAdapter contra respuestas grabadas de un WooCommerce real
(WordPress Playground, Store API pública), servido como `tienda-prueba-auyan.test`."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.demo_catalog import (
    BOT_USER_AGENT,
    DemoCatalogAdapter,
    DemoCatalogBase,
    DemoCatalogError,
    DemoCatalogUnavailable,
)
from apps.api.integrations.demo_catalog_registry import demo_catalog_for
from apps.api.integrations.demo_catalog_woocommerce import (
    WooCommerceDemoCatalogAdapter,
    price_from_minor_units,
)
from apps.api.skills.base import SkillContext
from apps.api.skills.shopify.get_product_info import GetProductInfo, GetProductInfoInput
from apps.api.tests.site_ingestion_replay import Replay, SleepLog

DOMAIN = "tienda-prueba-auyan.test"
TENANT = "11111111-1111-1111-1111-111111111111"
ORIGIN = f"https://{DOMAIN}"


def _adapter(replay: Replay, sleep: SleepLog | None = None) -> WooCommerceDemoCatalogAdapter:
    return WooCommerceDemoCatalogAdapter(
        DOMAIN, transport=replay.transport(), sleep=sleep or SleepLog()
    )


SUDADERA = {
    "id": 12,
    "title": "Sudadera Orgánica",
    "handle": "sudadera-organica",
    "product_type": "",
    "status": "active",
    "body_html": "",
    "tags": [],
    "online_store_url": f"{ORIGIN}/product/sudadera-organica/",
    "variants": [
        {"id": 15, "title": "L", "price": "45.00", "available": True},
        {"id": 14, "title": "M", "price": "45.00", "available": False},
        {"id": 13, "title": "S", "price": "45.00", "available": True},
    ],
}


async def test_variable_product_has_rest_shape_with_major_unit_price_and_per_size_stock() -> None:
    replay = Replay(("woocommerce",))

    products = await _adapter(replay).search_products(None, "sudadera")

    assert products == [SUDADERA]
    assert replay.urls() == [
        f"{ORIGIN}/wp-json/wc/store/v1/products?search=sudadera&per_page=10",
        f"{ORIGIN}/wp-json/wc/store/v1/products?parent=12&type=variation&per_page=100",
    ]


async def test_simple_products_get_one_default_variant_and_stock_flag() -> None:
    replay = Replay(("woocommerce",))
    adapter = _adapter(replay)

    camiseta = await adapter.search_products(None, "camiseta")
    pantalon = await adapter.search_products(None, "pantalón")

    assert camiseta[0]["title"] == "Camiseta Lino Azul"
    assert camiseta[0]["body_html"] == "<p>Descripción de Camiseta Lino Azul, algodón orgánico.</p>"
    assert camiseta[0]["variants"] == [
        {"id": 10, "title": "Default Title", "price": "29.90", "available": True}
    ]
    assert pantalon[0]["variants"] == [
        {"id": 11, "title": "Default Title", "price": "59.00", "available": False}
    ]
    assert not any("parent=" in u for u in replay.urls())


async def test_no_match_is_an_empty_list() -> None:
    assert await _adapter(Replay(("woocommerce",))).search_products(None, "zzzxxx") == []


async def test_detail_by_id_and_by_variation_id_returns_the_parent() -> None:
    adapter = _adapter(Replay(("woocommerce",)))

    assert await adapter.get_product(None, 12) == SUDADERA
    assert await adapter.get_product(None, 13) == SUDADERA
    assert await adapter.get_product(None, 999999) is None


async def test_currency_comes_free_after_a_search_and_costs_one_request_alone() -> None:
    replay = Replay(("woocommerce",))
    adapter = _adapter(replay)
    await adapter.search_products(None, "camiseta")
    before = len(replay.requests)
    assert await adapter.get_shop_currency(None) == "EUR"
    assert len(replay.requests) == before

    alone = Replay(("woocommerce",))
    assert await _adapter(alone).get_shop_currency(None) == "EUR"
    assert alone.urls() == [f"{ORIGIN}/wp-json/wc/store/v1/products?per_page=1"]


@pytest.mark.parametrize(
    ("price", "minor", "expected"),
    [
        ("4500", 2, "45.00"),
        ("2990", 2, "29.90"),
        ("4500", 0, "4500"),
        ("12345", 3, "12.345"),
        ("5", 2, "0.05"),
        ("", 2, "0.00"),
    ],
)
def test_prices_arrive_in_minor_units(price: str, minor: int, expected: str) -> None:
    assert price_from_minor_units({"price": price, "currency_minor_unit": minor}) == expected


async def test_legacy_store_api_route_is_the_fallback() -> None:
    replay = Replay(("woocommerce",))
    replay.overrides.append(
        lambda r: httpx.Response(404, json={"code": "rest_no_route"})
        if "/wc/store/v1" in str(r.url)
        else None
    )
    adapter = _adapter(replay)

    assert await adapter.search_products(None, "sudadera") == [
        {**SUDADERA, "variants": SUDADERA["variants"]}
    ]
    assert replay.urls()[-2:] == [
        f"{ORIGIN}/wp-json/wc/store/products?search=sudadera&per_page=10",
        f"{ORIGIN}/wp-json/wc/store/products?parent=12&type=variation&per_page=100",
    ]
    assert adapter._route == (True, "/wc/store")


async def test_rest_route_form_when_wp_json_is_blocked() -> None:
    replay = Replay(("woocommerce",))
    replay.overrides.append(
        lambda r: httpx.Response(403, text="blocked") if "/wp-json" in str(r.url) else None
    )

    products = await _adapter(replay).search_products(None, "sudadera")

    assert products == [SUDADERA]
    assert replay.urls()[-2:] == [
        f"{ORIGIN}/?rest_route=/wc/store/v1/products&search=sudadera&per_page=10",
        f"{ORIGIN}/?rest_route=/wc/store/v1/products&parent=12&type=variation&per_page=100",
    ]


async def test_requests_identify_as_auyanbot_without_credentials() -> None:
    replay = Replay(("woocommerce",))

    await _adapter(replay).search_products(None, "camiseta")

    request = replay.requests[0]
    assert request.headers["User-Agent"] == BOT_USER_AGENT
    assert "Authorization" not in request.headers


async def test_429_waits_retry_after_then_succeeds_and_a_long_wait_gives_up() -> None:
    replay = Replay(("woocommerce",))
    calls = {"n": 0}

    def once(request: httpx.Request) -> httpx.Response | None:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "2"}) if calls["n"] == 1 else None

    replay.overrides.append(once)
    sleep = SleepLog()
    assert (await _adapter(replay, sleep).search_products(None, "camiseta"))[0]["id"] == 10
    assert sleep.calls == [2.0]

    flooded = Replay(("woocommerce",))
    flooded.overrides.append(lambda r: httpx.Response(429, headers={"Retry-After": "60"}))
    with pytest.raises(DemoCatalogError, match="rate_limited: retry_after=60.0s"):
        await _adapter(flooded).search_products(None, "camiseta")


async def test_server_error_and_missing_store_api_fail_loudly() -> None:
    boom = Replay(("woocommerce",))
    boom.overrides.append(lambda r: httpx.Response(503))
    with pytest.raises(DemoCatalogError, match="storefront_http_503"):
        await _adapter(boom).search_products(None, "x")

    nothing = Replay(("woocommerce",))
    nothing.overrides.append(lambda r: httpx.Response(404))
    with pytest.raises(DemoCatalogError, match="woocommerce_store_api_unavailable"):
        await _adapter(nothing).search_products(None, "x")


async def test_get_product_info_cannot_tell_it_apart_from_shopify() -> None:
    ctx = SkillContext(
        tenant_id=TENANT,
        conversation_id="c",
        integration_ctx=IntegrationContext(
            tenant_id=TENANT, credentials={}, config={"store_domain": DOMAIN}
        ),
        commerce_mock=_adapter(Replay(("woocommerce",))),
    )

    out: Any = await GetProductInfo().execute(ctx, GetProductInfoInput(query="sudadera"))

    product = out.products[0]
    assert product.title == "Sudadera Orgánica"
    assert [(v.title, v.price.amount, v.price.currency, v.available) for v in product.variants] == [
        ("L", "45.00", "EUR", True),
        ("M", "45.00", "EUR", False),
        ("S", "45.00", "EUR", True),
    ]


async def test_non_catalog_operations_are_unavailable() -> None:
    with pytest.raises(DemoCatalogUnavailable):
        await _adapter(Replay(("woocommerce",))).get_order_by_name(None, "#1001")


def test_catalog_is_chosen_by_the_demo_platform() -> None:
    assert type(demo_catalog_for(DOMAIN, "woocommerce")) is WooCommerceDemoCatalogAdapter
    assert type(demo_catalog_for(DOMAIN, "shopify")) is DemoCatalogAdapter
    assert type(demo_catalog_for(DOMAIN, None)) is DemoCatalogAdapter
    assert type(demo_catalog_for(DOMAIN, "wordpress")) is DemoCatalogBase
    assert type(demo_catalog_for(DOMAIN, "other")) is DemoCatalogBase


async def test_platform_without_a_public_catalog_rejects_search() -> None:
    with pytest.raises(DemoCatalogUnavailable):
        await demo_catalog_for(DOMAIN, "wordpress").search_products(None, "x")


async def test_real_legacy_store_without_v1_and_without_slug() -> None:
    """productos-espanoles.com (WooCommerce antiguo): `/wc/store/v1` da 404, `/wc/store`
    responde y el producto no trae `slug`."""
    replay = Replay(("productos_espanoles",))
    adapter = WooCommerceDemoCatalogAdapter(
        "productos-espanoles.com", transport=replay.transport(), sleep=SleepLog()
    )

    products = await adapter.search_products(None, "aceite", limit=3)

    assert products == [
        {
            "id": 5698,
            "title": "Aceite Oliva",
            "handle": "aceite-oliva",
            "product_type": "Aceites",
            "status": "active",
            "body_html": products[0]["body_html"],
            "tags": [],
            "online_store_url": "https://www.productos-espanoles.com/producto/aceite-oliva/",
            "variants": [
                {"id": 5698, "title": "Default Title", "price": "0.00", "available": True}
            ],
        }
    ]
    assert "Lorem ipsum" in products[0]["body_html"]
    assert await adapter.get_shop_currency(None) == "USD"
    assert replay.urls() == [
        "https://productos-espanoles.com/wp-json/wc/store/v1/products?search=aceite&per_page=3",
        "https://productos-espanoles.com/wp-json/wc/store/products?search=aceite&per_page=3",
    ]
