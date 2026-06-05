"""Tests del enrutado de escalados al helpdesk externo (nota interna + asignación)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from apps.api.db.models import TenantIntegration
from apps.api.services import helpdesk_escalation
from apps.api.tests.conftest import TENANT_ID, make_conversation, make_fake_tenant_scope


class _FakeSettings:
    integrations_secret_key = "0" * 64


class _FakeAdapter:
    calls: list[tuple[Any, str, str, dict[str, Any]]] = []

    async def push_escalation(
        self, ctx: Any, conversation_ref: str, reason: str, agent_context: dict[str, Any]
    ) -> None:
        self.calls.append((ctx, conversation_ref, reason, agent_context))


def _integration(provider: str, config: dict[str, Any]) -> TenantIntegration:
    return TenantIntegration(
        id=UUID("99999999-9999-9999-9999-999999999999"),
        tenant_id=TENANT_ID,
        kind="helpdesk",
        provider=provider,
        config=config,
        is_active=True,
        is_primary_for_kind=True,
    )


def _patch_resolution(monkeypatch, *, provider: str, config: dict[str, Any], creds: dict) -> None:
    monkeypatch.setattr(helpdesk_escalation, "tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        helpdesk_escalation,
        "get_active_integration",
        AsyncMock(return_value=_integration(provider, config)),
    )
    monkeypatch.setattr(
        helpdesk_escalation,
        "get_integration_credentials_encrypted",
        AsyncMock(return_value=b"encrypted"),
    )
    monkeypatch.setattr(helpdesk_escalation, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(
        helpdesk_escalation, "get_integration_crypto_key", lambda settings: b"0" * 32
    )
    monkeypatch.setattr(
        helpdesk_escalation,
        "decrypt_credentials",
        lambda ciphertext, key: __import__("json").dumps(creds).encode(),
    )
    monkeypatch.setattr(
        helpdesk_escalation.IntegrationRegistry,
        "get",
        lambda kind, provider: _FakeAdapter,
    )


@pytest.mark.parametrize(
    ("provider", "config", "creds"),
    [
        ("chatwoot", {"base_url": "https://app.chatwoot.com", "account_id": "7"}, {"api_access_token": "tok"}),
        ("gorgias", {"domain": "acme"}, {"oauth_token": "tok"}),
        ("zendesk", {"subdomain": "acme"}, {"oauth_token": "tok"}),
    ],
)
@pytest.mark.asyncio
async def test_push_escalation_calls_adapter_with_context(
    monkeypatch: pytest.MonkeyPatch, provider: str, config: dict[str, Any], creds: dict
) -> None:
    _FakeAdapter.calls = []
    _patch_resolution(monkeypatch, provider=provider, config=config, creds=creds)

    result = await helpdesk_escalation.push_escalation_to_helpdesk(
        tenant_id=TENANT_ID,
        conversation=make_conversation(channel=provider, external_id="123"),
        reason="cliente_pide_humano",
        agent_context={"mensaje_al_cliente": "Lo paso a mi equipo"},
    )

    assert result is True
    assert len(_FakeAdapter.calls) == 1
    ctx, ref, reason, agent_context = _FakeAdapter.calls[0]
    assert ctx.credentials == creds
    assert ctx.config == config
    assert ref == "123"
    assert reason == "cliente_pide_humano"
    assert agent_context == {"mensaje_al_cliente": "Lo paso a mi equipo"}


@pytest.mark.asyncio
async def test_skips_non_helpdesk_channel() -> None:
    """Canal sin adapter de helpdesk (widget de prueba) → no enruta, devuelve False."""
    result = await helpdesk_escalation.push_escalation_to_helpdesk(
        tenant_id=TENANT_ID,
        conversation=make_conversation(channel="chat", external_id="123"),
        reason="x",
        agent_context={},
    )
    assert result is False


@pytest.mark.asyncio
async def test_returns_false_without_external_id() -> None:
    """Sin external_id no hay ticket externo al que enrutar."""
    result = await helpdesk_escalation.push_escalation_to_helpdesk(
        tenant_id=TENANT_ID,
        conversation=make_conversation(channel="chatwoot", external_id=None),
        reason="x",
        agent_context={},
    )
    assert result is False


@pytest.mark.asyncio
async def test_returns_false_when_no_active_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider con adapter pero sin integración activa registrada → False, no lanza."""
    monkeypatch.setattr(helpdesk_escalation, "tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        helpdesk_escalation, "get_active_integration", AsyncMock(return_value=None)
    )
    result = await helpdesk_escalation.push_escalation_to_helpdesk(
        tenant_id=TENANT_ID,
        conversation=make_conversation(channel="chatwoot", external_id="123"),
        reason="x",
        agent_context={},
    )
    assert result is False


@pytest.mark.asyncio
async def test_safe_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """La variante _safe nunca lanza: devuelve False si el push falla."""
    monkeypatch.setattr(
        helpdesk_escalation,
        "push_escalation_to_helpdesk",
        AsyncMock(side_effect=RuntimeError("helpdesk caído")),
    )
    result = await helpdesk_escalation.push_escalation_to_helpdesk_safe(
        tenant_id=TENANT_ID,
        conversation=make_conversation(channel="chatwoot", external_id="123"),
        reason="x",
        agent_context={},
    )
    assert result is False
