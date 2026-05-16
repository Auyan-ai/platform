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


def _patch_module(monkeypatch, *, tenant, config, system_prompt) -> None:
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_tenant_by_id", AsyncMock(return_value=tenant))
    monkeypatch.setattr(f"{MODULE}.get_tenant_configuration", AsyncMock(return_value=config))
    monkeypatch.setattr(
        f"{MODULE}.get_active_system_prompt", AsyncMock(return_value=system_prompt)
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
