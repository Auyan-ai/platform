"""Tests del nodo `load_tenant_context`."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apps.api.agents.nodes.load_tenant_context import make_load_tenant_context_node

from tests.conftest import (
    TENANT_ID,
    make_fake_tenant_scope,
    make_tenant,
    make_tenant_configuration,
)

MODULE = "apps.api.agents.nodes.load_tenant_context"


def _state() -> dict:
    return {"tenant_id": str(TENANT_ID)}


def _patch_module(
    monkeypatch,
    *,
    tenant,
    config,
    system_prompt,
    commerce_integration=None,
    commerce_encrypted=None,
    playbook=None,
    facts=None,
) -> None:
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_tenant_by_id", AsyncMock(return_value=tenant))
    monkeypatch.setattr(f"{MODULE}.get_tenant_configuration", AsyncMock(return_value=config))
    monkeypatch.setattr(
        f"{MODULE}.get_active_system_prompt", AsyncMock(return_value=system_prompt)
    )
    monkeypatch.setattr(f"{MODULE}.list_tool_permissions", AsyncMock(return_value=[]))
    monkeypatch.setattr(f"{MODULE}.get_tenant_playbook", AsyncMock(return_value=playbook))
    monkeypatch.setattr(f"{MODULE}.get_tenant_facts", AsyncMock(return_value=facts))
    monkeypatch.setattr(
        f"{MODULE}.get_primary_integration_for_kind",
        AsyncMock(return_value=commerce_integration),
    )
    monkeypatch.setattr(
        f"{MODULE}.get_integration_credentials_encrypted",
        AsyncMock(return_value=commerce_encrypted),
    )


@pytest.mark.asyncio
async def test_happy_path(fake_deps, monkeypatch) -> None:
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(agent_model="claude-opus-4-7"),
        system_prompt="Eres el agente de Acme.",
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["system_prompt"] == "Eres el agente de Acme."
    assert out["model_used"] == "claude-opus-4-7"
    assert out["tenant_config"]["escalation_threshold"] == 0.70
    assert "error" not in out


@pytest.mark.asyncio
async def test_tenant_not_found(fake_deps, monkeypatch) -> None:
    _patch_module(monkeypatch, tenant=None, config=None, system_prompt=None)
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["error"] == "tenant_not_found"


@pytest.mark.asyncio
async def test_tenant_inactive(fake_deps, monkeypatch) -> None:
    _patch_module(
        monkeypatch,
        tenant=make_tenant(status="suspended"),
        config=make_tenant_configuration(),
        system_prompt="x",
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["error"].startswith("tenant_not_active")
    assert "suspended" in out["error"]


@pytest.mark.asyncio
async def test_config_missing(fake_deps, monkeypatch) -> None:
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=None,
        system_prompt="x",
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["error"] == "tenant_config_missing"


@pytest.mark.asyncio
async def test_no_active_system_prompt(fake_deps, monkeypatch) -> None:
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt=None,
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["error"] == "no_active_system_prompt"


@pytest.mark.asyncio
async def test_empty_system_prompt_treated_as_missing(fake_deps, monkeypatch) -> None:
    """Un prompt activo pero con contenido vacío es un dato corrupto, escala."""
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="",
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["error"] == "no_active_system_prompt"


@pytest.mark.asyncio
async def test_passthrough_if_prior_error(fake_deps, monkeypatch) -> None:
    """Si el state ya tiene error, el nodo no ejecuta queries."""
    get_tenant_mock = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_tenant_by_id", get_tenant_mock)

    node = make_load_tenant_context_node(fake_deps)

    out = await node({"tenant_id": str(TENANT_ID), "error": "prior_failure"})

    assert out == {}
    get_tenant_mock.assert_not_called()


# ---------------------------------------------------------------------------
# commerce_integration_ctx — carga desde tenant_integrations + fallback extra
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_commerce_integration_returns_none(fake_deps, monkeypatch) -> None:
    """Tenant sin integración commerce ni creds en extra → ctx es None."""
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["commerce_integration_ctx"] is None


@pytest.mark.asyncio
async def test_falls_back_to_extra_shopify_creds(fake_deps, monkeypatch) -> None:
    """Sin tenant_integrations, lee credentials de tenant_config.extra (legacy)."""
    config = make_tenant_configuration(
        extra={"shopify_domain": "legacy.myshopify.com", "shopify_token": "shpat_legacy"}
    )
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=config,
        system_prompt="ok",
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    ctx = out["commerce_integration_ctx"]
    assert ctx is not None
    assert ctx["credentials"]["domain"] == "legacy.myshopify.com"
    assert ctx["credentials"]["token"] == "shpat_legacy"
    assert ctx["tenant_id"] == str(TENANT_ID)


@pytest.mark.asyncio
async def test_loads_from_tenant_integrations_decrypted(
    fake_deps, monkeypatch, tmp_path
) -> None:
    """Smoke test multi-tenant: tenant con integración en DB carga sus credentials cifradas."""
    import json
    import secrets
    from unittest.mock import MagicMock
    from uuid import UUID

    from apps.api.db.models import TenantIntegration
    from apps.api.services.integrations_crypto import encrypt_credentials

    # Key de 32 bytes para AES-GCM
    key = secrets.token_bytes(32)
    creds = {"domain": "tenant-a.myshopify.com", "token": "shpat_aaaaa"}
    encrypted = encrypt_credentials(json.dumps(creds).encode(), key)

    integration = TenantIntegration(
        id=UUID("99999999-9999-9999-9999-999999999999"),
        tenant_id=TENANT_ID,
        kind="commerce",
        provider="shopify",
        config={"shop_name": "Tenant A"},
        is_active=True,
        is_primary_for_kind=True,
    )

    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
        commerce_integration=integration,
        commerce_encrypted=encrypted,
    )
    # Inject key vía settings mock
    fake_settings = MagicMock()
    fake_settings.integrations_secret_key = key.hex()
    monkeypatch.setattr(
        f"{MODULE}.get_settings", lambda: fake_settings, raising=False
    )
    monkeypatch.setattr(
        "apps.api.core.config.get_settings", lambda: fake_settings
    )

    node = make_load_tenant_context_node(fake_deps)
    out = await node(_state())

    ctx = out["commerce_integration_ctx"]
    assert ctx is not None
    assert ctx["credentials"]["domain"] == "tenant-a.myshopify.com"
    assert ctx["credentials"]["token"] == "shpat_aaaaa"
    assert ctx["config"] == {"shop_name": "Tenant A"}


@pytest.mark.asyncio
async def test_tenant_integrations_takes_precedence_over_extra(
    fake_deps, monkeypatch
) -> None:
    """Si hay integración en DB Y creds en extra, DB gana."""
    import json
    import secrets
    from unittest.mock import MagicMock
    from uuid import UUID

    from apps.api.db.models import TenantIntegration
    from apps.api.services.integrations_crypto import encrypt_credentials

    key = secrets.token_bytes(32)
    creds = {"domain": "from-db.myshopify.com", "token": "shpat_db"}
    encrypted = encrypt_credentials(json.dumps(creds).encode(), key)

    integration = TenantIntegration(
        id=UUID("99999999-9999-9999-9999-999999999999"),
        tenant_id=TENANT_ID,
        kind="commerce",
        provider="shopify",
        config={},
        is_active=True,
        is_primary_for_kind=True,
    )

    config = make_tenant_configuration(
        extra={"shopify_domain": "from-extra.myshopify.com", "shopify_token": "shpat_extra"}
    )
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=config,
        system_prompt="ok",
        commerce_integration=integration,
        commerce_encrypted=encrypted,
    )
    fake_settings = MagicMock()
    fake_settings.integrations_secret_key = key.hex()
    monkeypatch.setattr("apps.api.core.config.get_settings", lambda: fake_settings)

    node = make_load_tenant_context_node(fake_deps)
    out = await node(_state())

    assert out["commerce_integration_ctx"]["credentials"]["domain"] == "from-db.myshopify.com"


@pytest.mark.asyncio
async def test_decrypt_failure_falls_back_to_extra(fake_deps, monkeypatch) -> None:
    """Si descifrar falla (key incorrecta), cae al fallback de extra sin romper el nodo."""
    from unittest.mock import MagicMock
    from uuid import UUID

    from apps.api.db.models import TenantIntegration

    integration = TenantIntegration(
        id=UUID("99999999-9999-9999-9999-999999999999"),
        tenant_id=TENANT_ID,
        kind="commerce",
        provider="shopify",
        config={},
        is_active=True,
        is_primary_for_kind=True,
    )

    config = make_tenant_configuration(
        extra={"shopify_domain": "fallback.myshopify.com", "shopify_token": "shpat_fb"}
    )
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=config,
        system_prompt="ok",
        commerce_integration=integration,
        commerce_encrypted=b"corrupt-cipher",
    )
    fake_settings = MagicMock()
    # Key válida (32 bytes hex) pero el ciphertext es basura → descifrado lanza
    fake_settings.integrations_secret_key = "00" * 32
    monkeypatch.setattr("apps.api.core.config.get_settings", lambda: fake_settings)

    node = make_load_tenant_context_node(fake_deps)
    out = await node(_state())

    # Fallback a extra
    ctx = out["commerce_integration_ctx"]
    assert ctx is not None
    assert ctx["credentials"]["domain"] == "fallback.myshopify.com"


# ---------------------------------------------------------------------------
# tenant_playbook + tenant_facts — cargados por load_tenant_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_playbook_and_facts_loaded_when_present(fake_deps, monkeypatch) -> None:
    from apps.api.db.models import TenantFacts, TenantPlaybook

    playbook = TenantPlaybook(
        tenant_id=TENANT_ID,
        brand_voice="Amigable y cercano",
        policies="30 días para devoluciones",
    )
    facts = TenantFacts(
        tenant_id=TENANT_ID,
        data={"business_hours": "L-V 9-18", "support_email": "hola@tienda.com"},
    )
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
        playbook=playbook,
        facts=facts,
    )
    node = make_load_tenant_context_node(fake_deps)
    out = await node(_state())

    assert out["tenant_playbook"]["brand_voice"] == "Amigable y cercano"
    assert out["tenant_playbook"]["policies"] == "30 días para devoluciones"
    assert out["tenant_facts"] == {"business_hours": "L-V 9-18", "support_email": "hola@tienda.com"}


@pytest.mark.asyncio
async def test_playbook_and_facts_none_when_not_configured(fake_deps, monkeypatch) -> None:
    """Tenant recién creado sin onboarding: playbook y facts son None."""
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
        playbook=None,
        facts=None,
    )
    node = make_load_tenant_context_node(fake_deps)
    out = await node(_state())

    assert out["tenant_playbook"] is None
    assert out["tenant_facts"] is None
