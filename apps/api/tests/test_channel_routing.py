"""Tests del resolutor único del canal de entrega (services/channel_routing)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.services import channel_routing, helpdesk_closure, helpdesk_escalation
from apps.api.services.channel_routing import (
    DELIVERY_ROUTES,
    delivery_route,
    is_messaging_channel,
    load_delivery_client,
)
from apps.api.tests.conftest import TENANT_ID, make_conversation


def test_delivery_routes_mapping() -> None:
    assert DELIVERY_ROUTES == {
        "zendesk": ("helpdesk", "zendesk"),
        "gorgias": ("helpdesk", "gorgias"),
        "chatwoot": ("helpdesk", "chatwoot"),
        "whatsapp": ("channel", "zernio"),
    }


@pytest.mark.parametrize("channel", ["chat", "widget", "email", "instagram", "intercom"])
def test_channels_without_route(channel: str) -> None:
    assert delivery_route(channel) is None
    assert is_messaging_channel(channel) is False


@pytest.mark.parametrize("channel", ["zendesk", "gorgias", "chatwoot"])
def test_helpdesks_are_not_messaging(channel: str) -> None:
    assert delivery_route(channel) == ("helpdesk", channel)
    assert is_messaging_channel(channel) is False


def test_whatsapp_is_messaging() -> None:
    assert delivery_route("whatsapp") == ("channel", "zernio")
    assert is_messaging_channel("whatsapp") is True


async def test_load_delivery_client_chat_returns_none() -> None:
    conv = make_conversation(channel="chat", external_id="ext-1")
    assert await load_delivery_client(MagicMock(), tenant_id=TENANT_ID, conversation=conv) is None


async def test_load_delivery_client_without_external_id_returns_none() -> None:
    conv = make_conversation(channel="zendesk", external_id=None)
    assert await load_delivery_client(MagicMock(), tenant_id=TENANT_ID, conversation=conv) is None


async def test_load_delivery_client_uses_channel_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    """WhatsApp se resuelve contra (channel, zernio), no contra un helpdesk."""
    get_integration = AsyncMock(return_value=None)
    monkeypatch.setattr(channel_routing, "get_active_integration", get_integration)
    monkeypatch.setattr(
        channel_routing.IntegrationRegistry, "get", MagicMock(return_value=MagicMock())
    )
    conv = make_conversation(channel="whatsapp", external_id="zconv-1")
    assert await load_delivery_client(MagicMock(), tenant_id=TENANT_ID, conversation=conv) is None
    channel_routing.IntegrationRegistry.get.assert_called_once_with("channel", "zernio")
    assert get_integration.await_args.kwargs == {
        "tenant_id": TENANT_ID,
        "kind": "channel",
        "provider": "zernio",
    }


async def test_load_delivery_client_unregistered_adapter_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing(kind: str, provider: str) -> None:
        raise ValueError(f"unknown_integration: {kind}/{provider}")

    monkeypatch.setattr(channel_routing.IntegrationRegistry, "get", _missing)
    get_integration = AsyncMock()
    monkeypatch.setattr(channel_routing, "get_active_integration", get_integration)
    conv = make_conversation(channel="whatsapp", external_id="zconv-1")
    assert await load_delivery_client(MagicMock(), tenant_id=TENANT_ID, conversation=conv) is None
    get_integration.assert_not_awaited()


async def test_escalation_push_is_noop_on_messaging_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = MagicMock()
    monkeypatch.setattr(helpdesk_escalation, "tenant_scope", scope)
    conv = make_conversation(channel="whatsapp", external_id="zconv-1")
    ok = await helpdesk_escalation.push_escalation_to_helpdesk(
        tenant_id=TENANT_ID, conversation=conv, reason="quiere hablar con una persona"
    )
    assert ok is False
    scope.assert_not_called()


async def test_helpdesk_closure_is_noop_on_messaging_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = MagicMock()
    monkeypatch.setattr(helpdesk_closure, "tenant_scope", scope)
    conv = make_conversation(channel="whatsapp", external_id="zconv-1")
    ok = await helpdesk_closure.close_external_helpdesk_ticket(
        tenant_id=TENANT_ID, conversation=conv, settings=MagicMock()
    )
    assert ok is False
    scope.assert_not_called()
