"""Tests del cierre sincronizado con helpdesks externos."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from apps.api.core.errors import ExternalIntegrationError
from apps.api.db.models import TenantIntegration
from apps.api.services import helpdesk_closure
from apps.api.tests.conftest import TENANT_ID, make_conversation, make_fake_tenant_scope


class _FakeSettings:
    integrations_secret_key = "0" * 64


class _FakeAdapter:
    calls: list[tuple[Any, str, str]] = []

    async def update_status(self, ctx: Any, ticket_ref: str, status: str) -> None:
        self.calls.append((ctx, ticket_ref, status))


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


@pytest.mark.parametrize(
    ("provider", "external_status", "config", "credentials"),
    [
        ("zendesk", "solved", {"subdomain": "acme"}, {"oauth_token": "tok"}),
        ("gorgias", "closed", {"domain": "acme"}, {"oauth_token": "tok"}),
        (
            "chatwoot",
            "resolved",
            {"base_url": "https://app.chatwoot.com", "account_id": "7"},
            {"api_access_token": "tok"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_close_external_helpdesk_ticket_maps_provider_status(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    external_status: str,
    config: dict[str, Any],
    credentials: dict[str, str],
) -> None:
    _FakeAdapter.calls = []
    encrypted = b"encrypted"
    monkeypatch.setattr(helpdesk_closure, "tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        helpdesk_closure,
        "get_active_integration",
        AsyncMock(return_value=_integration(provider, config)),
    )
    monkeypatch.setattr(
        helpdesk_closure,
        "get_integration_credentials_encrypted",
        AsyncMock(return_value=encrypted),
    )
    monkeypatch.setattr(helpdesk_closure, "get_integration_crypto_key", lambda settings: b"0" * 32)
    monkeypatch.setattr(
        helpdesk_closure,
        "decrypt_credentials",
        lambda ciphertext, key: __import__("json").dumps(credentials).encode(),
    )
    monkeypatch.setitem(helpdesk_closure._ADAPTER_BY_PROVIDER, provider, _FakeAdapter)

    result = await helpdesk_closure.close_external_helpdesk_ticket(
        tenant_id=TENANT_ID,
        conversation=make_conversation(channel=provider, external_id="123"),
        settings=_FakeSettings(),  # type: ignore[arg-type]
    )

    assert result is True
    assert len(_FakeAdapter.calls) == 1
    ctx, ticket_ref, status = _FakeAdapter.calls[0]
    assert ctx.credentials == credentials
    assert ctx.config == config
    assert ticket_ref == "123"
    assert status == external_status


@pytest.mark.asyncio
async def test_close_external_helpdesk_ticket_skips_non_helpdesk_channel() -> None:
    result = await helpdesk_closure.close_external_helpdesk_ticket(
        tenant_id=TENANT_ID,
        conversation=make_conversation(channel="chat", external_id="123"),
        settings=_FakeSettings(),  # type: ignore[arg-type]
    )

    assert result is False


@pytest.mark.asyncio
async def test_close_external_helpdesk_ticket_raises_when_provider_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingAdapter:
        async def update_status(self, ctx: Any, ticket_ref: str, status: str) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(helpdesk_closure, "tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        helpdesk_closure,
        "get_active_integration",
        AsyncMock(return_value=_integration("zendesk", {"subdomain": "acme"})),
    )
    monkeypatch.setattr(
        helpdesk_closure,
        "get_integration_credentials_encrypted",
        AsyncMock(return_value=b"encrypted"),
    )
    monkeypatch.setattr(helpdesk_closure, "get_integration_crypto_key", lambda settings: b"0" * 32)
    monkeypatch.setattr(
        helpdesk_closure,
        "decrypt_credentials",
        lambda ciphertext, key: b'{"oauth_token":"tok"}',
    )
    monkeypatch.setitem(helpdesk_closure._ADAPTER_BY_PROVIDER, "zendesk", FailingAdapter)

    with pytest.raises(ExternalIntegrationError, match="failed to close external zendesk ticket"):
        await helpdesk_closure.close_external_helpdesk_ticket(
            tenant_id=TENANT_ID,
            conversation=make_conversation(channel="zendesk", external_id="123"),
            settings=_FakeSettings(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_close_safe_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """La variante _safe nunca lanza: devuelve False si el cierre falla."""
    monkeypatch.setattr(
        helpdesk_closure,
        "close_external_helpdesk_ticket",
        AsyncMock(side_effect=ExternalIntegrationError("boom", code="x")),
    )
    result = await helpdesk_closure.close_external_helpdesk_ticket_safe(
        tenant_id=TENANT_ID,
        conversation=make_conversation(channel="zendesk", external_id="123"),
        settings=_FakeSettings(),  # type: ignore[arg-type]
    )
    assert result is False
