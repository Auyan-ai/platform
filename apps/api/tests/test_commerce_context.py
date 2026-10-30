"""Tests de `build_commerce_integration_ctx`.

Fuente única de la lógica sensible de cripto (descifrado + token exchange Shopify)
que comparten el nodo `load_tenant_context` y el endpoint de approvals.
"""

from __future__ import annotations

import json
import secrets
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from apps.api.db.models import TenantIntegration
from apps.api.services.commerce_context import build_commerce_integration_ctx
from apps.api.services.integrations_crypto import encrypt_credentials

from tests.conftest import TENANT_ID

MODULE = "apps.api.services.commerce_context"


def _patch_integration(
    monkeypatch,
    *,
    integration=None,
    encrypted=None,
    key: bytes | None = None,
) -> None:
    """Parchea las queries y el settings del módulo del helper."""
    monkeypatch.setattr(
        f"{MODULE}.get_primary_integration_for_kind",
        AsyncMock(return_value=integration),
    )
    monkeypatch.setattr(
        f"{MODULE}.get_integration_credentials_encrypted",
        AsyncMock(return_value=encrypted),
    )
    if key is not None:
        fake_settings = MagicMock()
        fake_settings.integrations_secret_key = key.hex()
        monkeypatch.setattr(f"{MODULE}.get_settings", lambda: fake_settings)


def _shopify_integration(*, config: dict | None = None) -> TenantIntegration:
    return TenantIntegration(
        id=UUID("99999999-9999-9999-9999-999999999999"),
        tenant_id=TENANT_ID,
        kind="commerce",
        provider="shopify",
        config=config or {},
        is_active=True,
        is_primary_for_kind=True,
    )


@pytest.mark.asyncio
async def test_no_integration_no_extra_returns_none(monkeypatch) -> None:
    """Sin integración en DB ni creds en extra → None."""
    _patch_integration(monkeypatch, integration=None)

    ctx = await build_commerce_integration_ctx(MagicMock(), TENANT_ID)

    assert ctx is None


@pytest.mark.asyncio
async def test_falls_back_to_extra_shopify_creds(monkeypatch) -> None:
    """Sin tenant_integrations, lee credentials de tenant_config.extra (legacy)."""
    _patch_integration(monkeypatch, integration=None)

    ctx = await build_commerce_integration_ctx(
        MagicMock(),
        TENANT_ID,
        extra={"shopify_domain": "legacy.myshopify.com", "shopify_token": "shpat_legacy"},
    )

    assert ctx is not None
    assert ctx.tenant_id == TENANT_ID
    assert ctx.credentials == {"domain": "legacy.myshopify.com", "token": "shpat_legacy"}
    assert ctx.config == {}


@pytest.mark.asyncio
async def test_loads_from_tenant_integrations_decrypted(monkeypatch) -> None:
    """Tenant con integración en DB carga sus credentials cifradas."""
    key = secrets.token_bytes(32)
    creds = {"domain": "tenant-a.myshopify.com", "token": "shpat_aaaaa"}
    encrypted = encrypt_credentials(json.dumps(creds).encode(), key)

    _patch_integration(
        monkeypatch,
        integration=_shopify_integration(config={"shop_name": "Tenant A"}),
        encrypted=encrypted,
        key=key,
    )

    ctx = await build_commerce_integration_ctx(MagicMock(), TENANT_ID)

    assert ctx is not None
    assert ctx.credentials == {"domain": "tenant-a.myshopify.com", "token": "shpat_aaaaa"}
    assert ctx.config == {"shop_name": "Tenant A"}


@pytest.mark.asyncio
async def test_tenant_integrations_takes_precedence_over_extra(monkeypatch) -> None:
    """Si hay integración en DB Y creds en extra, DB gana."""
    key = secrets.token_bytes(32)
    creds = {"domain": "from-db.myshopify.com", "token": "shpat_db"}
    encrypted = encrypt_credentials(json.dumps(creds).encode(), key)

    _patch_integration(
        monkeypatch,
        integration=_shopify_integration(),
        encrypted=encrypted,
        key=key,
    )

    ctx = await build_commerce_integration_ctx(
        MagicMock(),
        TENANT_ID,
        extra={"shopify_domain": "from-extra.myshopify.com", "shopify_token": "shpat_extra"},
    )

    assert ctx is not None
    assert ctx.credentials["domain"] == "from-db.myshopify.com"


@pytest.mark.asyncio
async def test_decrypt_failure_falls_back_to_extra(monkeypatch) -> None:
    """Si descifrar falla (ciphertext basura), cae al fallback de extra sin romper."""
    _patch_integration(
        monkeypatch,
        integration=_shopify_integration(),
        encrypted=b"corrupt-cipher",
        key=bytes.fromhex("00" * 32),  # key válida, ciphertext inválido → InvalidTag
    )

    ctx = await build_commerce_integration_ctx(
        MagicMock(),
        TENANT_ID,
        extra={"shopify_domain": "fallback.myshopify.com", "shopify_token": "shpat_fb"},
    )

    assert ctx is not None
    assert ctx.credentials["domain"] == "fallback.myshopify.com"


@pytest.mark.asyncio
async def test_shopify_client_credentials_trigger_token_exchange(monkeypatch) -> None:
    """Creds con client_id/secret → resuelve el access_token corto y no expone los secretos."""
    key = secrets.token_bytes(32)
    creds = {
        "domain": "exchange.myshopify.com",
        "client_id": "cid",
        "client_secret": "csecret",
    }
    encrypted = encrypt_credentials(json.dumps(creds).encode(), key)

    _patch_integration(
        monkeypatch,
        integration=_shopify_integration(),
        encrypted=encrypted,
        key=key,
    )
    exchange = AsyncMock(return_value=("shpat_resolved", 3600))
    monkeypatch.setattr("apps.api.integrations.shopify.ensure_shopify_access_token", exchange)

    ctx = await build_commerce_integration_ctx(MagicMock(), TENANT_ID)

    assert ctx is not None
    # El adapter solo recibe domain + access_token (no client_id/secret).
    assert ctx.credentials == {
        "domain": "exchange.myshopify.com",
        "access_token": "shpat_resolved",
    }
    exchange.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        domain="exchange.myshopify.com",
        client_id="cid",
        client_secret="csecret",
    )


async def test_a_commerce_integration_without_adapter_is_not_saved() -> None:
    from apps.api.db.queries import upsert_integration

    conn = AsyncMock()

    with pytest.raises(ValueError, match="unknown_integration: commerce/magento"):
        await upsert_integration(
            conn,
            tenant_id=TENANT_ID,
            kind="commerce",
            provider="magento",
            credentials_encrypted=b"x",
            config={},
        )
    conn.fetchrow.assert_not_awaited()
