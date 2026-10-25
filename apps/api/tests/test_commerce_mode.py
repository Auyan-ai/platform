"""El modo de comercio del turno elige el adaptador (agents/commerce_mode.py)."""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.agents.commerce_mode import commerce_mode
from apps.api.agents.nodes.execute_skill import build_skill_context
from apps.api.integrations.demo_catalog import DemoCatalogAdapter
from apps.api.simulator.mocks import MockShopifyAdapter

TENANT = "11111111-1111-1111-1111-111111111111"
COMMERCE_CTX = {
    "tenant_id": TENANT,
    "credentials": {"domain": "tienda.myshopify.com", "access_token": "shpat_secret"},
    "config": {},
}


def _state(**overrides: Any) -> Any:
    return {
        "tenant_id": TENANT,
        "conversation_id": "22222222-2222-2222-2222-222222222222",
        **overrides,
    }


def test_default_mode_derives_from_simulation_mode() -> None:
    assert commerce_mode(_state()) == "live"
    assert commerce_mode(_state(simulation_mode=False)) == "live"
    assert commerce_mode(_state(simulation_mode=True)) == "mock"


def test_invalid_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid_commerce_mode"):
        commerce_mode(_state(commerce_mode="sandbox"))


def test_simulator_still_gets_the_mock() -> None:
    ctx = build_skill_context(_state(simulation_mode=True, simulation_fixtures={"shopify": {}}))

    assert isinstance(ctx.commerce_mock, MockShopifyAdapter)


def test_live_injects_no_adapter_and_keeps_the_tenant_credentials() -> None:
    ctx = build_skill_context(_state(commerce_integration_ctx=COMMERCE_CTX))

    assert ctx.commerce_mock is None
    assert ctx.integration_ctx is not None
    assert ctx.integration_ctx.credentials["access_token"] == "shpat_secret"


def test_demo_catalog_gets_the_public_adapter_and_never_the_credentials() -> None:
    ctx = build_skill_context(
        _state(
            commerce_mode="demo_catalog",
            demo_catalog_domain="thinkingmu.com",
            commerce_integration_ctx=COMMERCE_CTX,
        )
    )

    assert isinstance(ctx.commerce_mock, DemoCatalogAdapter)
    assert ctx.commerce_mock.domain == "thinkingmu.com"
    assert ctx.integration_ctx is not None
    assert ctx.integration_ctx.credentials == {}


def test_demo_catalog_adapter_follows_the_demo_platform() -> None:
    from apps.api.integrations.demo_catalog_woocommerce import WooCommerceDemoCatalogAdapter

    ctx = build_skill_context(
        _state(
            commerce_mode="demo_catalog",
            demo_catalog_domain="tienda.example",
            demo_catalog_platform="woocommerce",
        )
    )

    assert isinstance(ctx.commerce_mock, WooCommerceDemoCatalogAdapter)
    assert ctx.integration_ctx is not None and ctx.integration_ctx.credentials == {}


async def test_demo_catalog_never_builds_the_real_shopify_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.skills.shopify.get_product_info as skill_module
    from apps.api.integrations.base import IntegrationContext
    from apps.api.skills.shopify.get_product_info import GetProductInfo, GetProductInfoInput

    class _Boom:
        def __init__(self) -> None:
            raise AssertionError("ShopifyAdapter construido en una demo")

    monkeypatch.setattr(skill_module, "ShopifyAdapter", _Boom)

    class _Fake(DemoCatalogAdapter):
        async def search_products(self, ctx: Any, query: str, *, limit: int = 10) -> list[Any]:
            assert isinstance(ctx, IntegrationContext) and ctx.credentials == {}
            return []

    ctx = build_skill_context(
        _state(commerce_mode="demo_catalog", demo_catalog_domain="thinkingmu.com")
    )
    from dataclasses import replace

    ctx = replace(ctx, commerce_mock=_Fake("thinkingmu.com"))

    out = await GetProductInfo().execute(ctx, GetProductInfoInput(query="x"))

    assert out.total_found == 0  # type: ignore[attr-defined]


def test_demo_catalog_without_domain_fails_loudly() -> None:
    with pytest.raises(ValueError, match="demo_catalog_domain_missing"):
        build_skill_context(_state(commerce_mode="demo_catalog"))
