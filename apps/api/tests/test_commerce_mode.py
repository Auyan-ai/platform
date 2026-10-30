"""El modo de comercio del turno elige el adaptador (agents/commerce_mode.py)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from apps.api.agents.commerce_mode import commerce_mode
from apps.api.agents.nodes.execute_skill import build_skill_context
from apps.api.integrations.demo_catalog import DemoCatalogAdapter
from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.simulator.mocks import MockShopifyAdapter

TENANT = "11111111-1111-1111-1111-111111111111"
COMMERCE_CTX = {
    "tenant_id": TENANT,
    "credentials": {"domain": "tienda.myshopify.com", "access_token": "shpat_secret"},
    "config": {},
    "provider": "shopify",
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

    assert isinstance(ctx.commerce, MockShopifyAdapter)


def test_live_resolves_the_adapter_of_the_integration_provider() -> None:
    ctx = build_skill_context(_state(commerce_integration_ctx=COMMERCE_CTX))

    assert isinstance(ctx.commerce, ShopifyAdapter)
    assert ctx.integration_ctx is not None
    assert ctx.integration_ctx.provider == "shopify"
    assert ctx.integration_ctx.credentials["access_token"] == "shpat_secret"


def test_live_without_integration_has_no_adapter() -> None:
    ctx = build_skill_context(_state())

    assert ctx.commerce is None
    assert ctx.integration_ctx is None


def test_live_with_an_unregistered_provider_logs_an_error_and_runs_without_commerce(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = _state(commerce_integration_ctx={**COMMERCE_CTX, "provider": "prestashop"})

    with caplog.at_level(logging.ERROR, logger="apps.api.agents.commerce_mode"):
        ctx = build_skill_context(state)

    assert ctx.commerce is None
    assert "unknown_integration: commerce/prestashop" in caplog.text


def test_live_without_provider_logs_an_error_and_runs_without_commerce(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = _state(commerce_integration_ctx={**COMMERCE_CTX, "provider": None})

    with caplog.at_level(logging.ERROR, logger="apps.api.agents.commerce_mode"):
        ctx = build_skill_context(state)

    assert ctx.commerce is None
    assert "commerce_provider_missing" in caplog.text


def test_demo_catalog_gets_the_public_adapter_and_never_the_credentials() -> None:
    ctx = build_skill_context(
        _state(
            commerce_mode="demo_catalog",
            demo_catalog_domain="thinkingmu.com",
            commerce_integration_ctx=COMMERCE_CTX,
        )
    )

    assert isinstance(ctx.commerce, DemoCatalogAdapter)
    assert ctx.commerce.domain == "thinkingmu.com"
    assert ctx.integration_ctx is not None
    assert ctx.integration_ctx.credentials == {}


async def test_demo_catalog_never_builds_the_real_shopify_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.integrations.base import IntegrationContext
    from apps.api.skills.shopify.get_product_info import GetProductInfo, GetProductInfoInput

    def _boom(integration: IntegrationContext) -> None:
        raise AssertionError("adapter del tenant construido en una demo")

    monkeypatch.setattr("apps.api.agents.commerce_mode.commerce_adapter", _boom)

    class _Fake(DemoCatalogAdapter):
        async def search_products(self, ctx: Any, query: str, *, limit: int = 10) -> list[Any]:
            assert isinstance(ctx, IntegrationContext) and ctx.credentials == {}
            return []

    ctx = build_skill_context(
        _state(
            commerce_mode="demo_catalog",
            demo_catalog_domain="thinkingmu.com",
            commerce_integration_ctx=COMMERCE_CTX,
        )
    )
    from dataclasses import replace

    ctx = replace(ctx, commerce=_Fake("thinkingmu.com"))

    out = await GetProductInfo().execute(ctx, GetProductInfoInput(query="x"))

    assert out.total_found == 0  # type: ignore[attr-defined]


def test_demo_catalog_without_domain_fails_loudly() -> None:
    with pytest.raises(ValueError, match="demo_catalog_domain_missing"):
        build_skill_context(_state(commerce_mode="demo_catalog"))
