"""Tests unitarios del script de configuración staging 0.11A."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from apps.api.scripts import configure_staging_integrations as script


def test_redact_credentials_masks_sensitive_values() -> None:
    redacted = script.redact_credentials(
        {
            "domain": "lunaria-test.myshopify.com",
            "token": "shpat_1234567890",
            "api_access_token": "cw_token_abcdef",
            "webhook_secret_token": "secret_xyz",
            "empty": "",
        }
    )

    assert redacted == {
        "domain": "lunaria-test.myshopify.com",
        "token": "***7890",
        "api_access_token": "***cdef",
        "webhook_secret_token": "***_xyz",
        "empty": "",
    }


def test_normalize_shopify_domain_accepts_host_or_url() -> None:
    assert script._normalize_shopify_domain("https://x.myshopify.com/") == "x.myshopify.com"
    assert script._normalize_shopify_domain("http://x.myshopify.com") == "x.myshopify.com"
    assert script._normalize_shopify_domain("x.myshopify.com") == "x.myshopify.com"


def test_normalize_shopify_domain_rejects_paths() -> None:
    with pytest.raises(SystemExit, match="sólo el host"):
        script._normalize_shopify_domain("https://x.myshopify.com/admin")


@pytest.mark.asyncio
async def test_build_shopify_plan_requires_e2e_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPIFY_TEST_DOMAIN", "https://lunaria-test.myshopify.com/")
    monkeypatch.setenv("SHOPIFY_TEST_ACCESS_TOKEN", "shpat_test")
    monkeypatch.setattr(
        script,
        "_validate_shopify",
        _async_return({"name": "Lunaria Test", "email": "ops@lunaria.test"}),
    )
    monkeypatch.setattr(script, "_fetch_shopify_e2e_orders", _async_return([]))

    with pytest.raises(SystemExit, match="No encontré órdenes Shopify"):
        await script.build_shopify_plan(
            e2e_order_tag="auyan-e2e",
            allow_missing_e2e_orders=False,
        )


@pytest.mark.asyncio
async def test_build_shopify_plan_includes_e2e_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHOPIFY_TEST_DOMAIN", "lunaria-test.myshopify.com")
    monkeypatch.setenv("SHOPIFY_TEST_ACCESS_TOKEN", "shpat_test")
    monkeypatch.setattr(
        script,
        "_validate_shopify",
        _async_return({"name": "Lunaria Test", "email": "ops@lunaria.test"}),
    )
    monkeypatch.setattr(
        script,
        "_fetch_shopify_e2e_orders",
        _async_return([{"name": "#1001"}, {"name": "#1002"}]),
    )

    plan = await script.build_shopify_plan(
        e2e_order_tag="auyan-e2e",
        allow_missing_e2e_orders=False,
    )

    assert plan.kind == "commerce"
    assert plan.provider == "shopify"
    assert plan.credentials == {
        "domain": "lunaria-test.myshopify.com",
        "token": "shpat_test",
    }
    assert plan.config["e2e_order_count"] == 2
    assert plan.config["e2e_order_names"] == ["#1001", "#1002"]


@pytest.mark.asyncio
async def test_build_chatwoot_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATWOOT_BASE_URL", "https://app.chatwoot.com/")
    monkeypatch.setenv("CHATWOOT_ACCOUNT_ID", "7")
    monkeypatch.setenv("CHATWOOT_API_ACCESS_TOKEN", "cw_test_token")
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET_TOKEN", "cw_webhook_secret")
    monkeypatch.setenv("CHATWOOT_ESCALATION_TEAM_ID", "12")
    monkeypatch.setattr(script, "_validate_chatwoot", _async_return({"name": "Lunaria"}))

    plan = await script.build_chatwoot_plan()

    assert plan.kind == "helpdesk"
    assert plan.provider == "chatwoot"
    assert plan.credentials == {
        "api_access_token": "cw_test_token",
        "webhook_secret_token": "cw_webhook_secret",
    }
    assert plan.config["base_url"] == "https://app.chatwoot.com"
    assert plan.config["account_id"] == "7"
    assert plan.config["account_name"] == "Lunaria"
    assert plan.config["escalation_team_id"] == "12"


@pytest.mark.asyncio
async def test_apply_plan_passes_config_as_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    upsert = AsyncMock()
    monkeypatch.setattr(script, "upsert_integration", upsert)
    monkeypatch.setattr(script, "encrypt_credentials", lambda plaintext, key: b"encrypted")

    plan = script.IntegrationPlan(
        provider="shopify",
        kind="commerce",
        credentials={"domain": "x.myshopify.com", "token": "shpat_x"},
        config={"api_version": "2024-10", "e2e_order_count": 3},
    )

    await script._apply_plan(
        AsyncMock(),
        tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
        key=b"k" * 32,
        plan=plan,
    )

    assert upsert.await_args.kwargs["config"] == {
        "api_version": "2024-10",
        "e2e_order_count": 3,
    }


@pytest.mark.asyncio
async def test_connect_database_registers_json_codecs(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = AsyncMock()
    connect = AsyncMock(return_value=conn)
    monkeypatch.setattr(script.asyncpg, "connect", connect)

    result = await script._connect_database("postgresql://example")

    assert result is conn
    connect.assert_awaited_once_with("postgresql://example")
    assert conn.set_type_codec.await_count == 2


def _async_return(value: Any) -> Callable[..., Awaitable[Any]]:
    async def inner(*args: Any, **kwargs: Any) -> Any:
        return value

    return inner
