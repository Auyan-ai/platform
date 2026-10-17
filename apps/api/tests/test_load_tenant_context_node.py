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
    commerce_ctx=None,
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
        f"{MODULE}.build_commerce_integration_ctx",
        AsyncMock(return_value=commerce_ctx),
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


# ---------------------------------------------------------------------------
# commerce_integration_ctx — el nodo delega en build_commerce_integration_ctx
# y serializa el IntegrationContext resultante al state. La lógica de cripto
# (descifrado, token exchange, fallback) se prueba en test_commerce_context.py.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_commerce_integration_returns_none(fake_deps, monkeypatch) -> None:
    """Helper devuelve None (sin integración ni creds) → ctx es None."""
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
        commerce_ctx=None,
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    assert out["commerce_integration_ctx"] is None


@pytest.mark.asyncio
async def test_serializes_commerce_ctx_to_dict(fake_deps, monkeypatch) -> None:
    """Helper devuelve IntegrationContext → el nodo lo serializa JSON-safe al state."""
    from apps.api.integrations.base import IntegrationContext

    ctx = IntegrationContext(
        tenant_id=TENANT_ID,
        credentials={"domain": "tenant-a.myshopify.com", "access_token": "shpat_x"},
        config={"shop_name": "Tenant A"},
    )
    _patch_module(
        monkeypatch,
        tenant=make_tenant(),
        config=make_tenant_configuration(),
        system_prompt="ok",
        commerce_ctx=ctx,
    )
    node = make_load_tenant_context_node(fake_deps)

    out = await node(_state())

    result = out["commerce_integration_ctx"]
    assert result == {
        "tenant_id": str(TENANT_ID),
        "credentials": {"domain": "tenant-a.myshopify.com", "access_token": "shpat_x"},
        "config": {"shop_name": "Tenant A"},
    }
    assert isinstance(result["tenant_id"], str)  # UUID serializado a str para el state


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
