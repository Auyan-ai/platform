"""Tests para deliver_message_to_helpdesk (entrega del flujo de approvals al helpdesk)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from apps.api.services import channel_routing
from apps.api.services.helpdesk_delivery import deliver_message_to_helpdesk

TENANT = UUID("11111111-1111-1111-1111-111111111111")
CONV_ID = UUID("22222222-2222-2222-2222-222222222222")


def _conv(channel: str, external_id: str | None) -> SimpleNamespace:
    return SimpleNamespace(id=CONV_ID, channel=channel, external_id=external_id)


async def test_no_external_id_returns_false() -> None:
    conn = MagicMock()
    ok = await deliver_message_to_helpdesk(
        conn, tenant_id=TENANT, conversation=_conv("chatwoot", None), content="hola"
    )
    assert ok is False


async def test_unknown_channel_returns_false() -> None:
    # 'chat' (webhook de prueba) no es un helpdesk registrado → no hay a dónde entregar.
    conn = MagicMock()
    ok = await deliver_message_to_helpdesk(
        conn, tenant_id=TENANT, conversation=_conv("chat", "ext-1"), content="hola"
    )
    assert ok is False


async def test_no_active_integration_returns_false(monkeypatch) -> None:
    monkeypatch.setattr(channel_routing, "get_active_integration", AsyncMock(return_value=None))
    conn = MagicMock()
    ok = await deliver_message_to_helpdesk(
        conn, tenant_id=TENANT, conversation=_conv("chatwoot", "ext-1"), content="hola"
    )
    assert ok is False


async def test_happy_path_calls_send_outbound(monkeypatch) -> None:
    integration = SimpleNamespace(
        id=UUID("33333333-3333-3333-3333-333333333333"), config={"account_id": "167723"}
    )
    monkeypatch.setattr(
        channel_routing, "get_active_integration", AsyncMock(return_value=integration)
    )
    monkeypatch.setattr(
        channel_routing,
        "get_integration_credentials_encrypted",
        AsyncMock(return_value=b"enc"),
    )
    monkeypatch.setattr(channel_routing, "get_settings", lambda: object())
    monkeypatch.setattr(channel_routing, "get_integration_crypto_key", lambda _s: b"key")
    monkeypatch.setattr(
        channel_routing,
        "decrypt_credentials",
        lambda _enc, _key: json.dumps({"api_access_token": "t"}).encode(),
    )
    send_mock = AsyncMock(return_value=None)
    adapter_cls = MagicMock(return_value=SimpleNamespace(send_outbound=send_mock))

    with patch.object(channel_routing.IntegrationRegistry, "get", return_value=adapter_cls):
        conn = MagicMock()
        ok = await deliver_message_to_helpdesk(
            conn,
            tenant_id=TENANT,
            conversation=_conv("chatwoot", "ext-99"),
            content="¡Listo! Hemos actualizado tu dirección.",
        )

    assert ok is True
    send_mock.assert_awaited_once()
    args = send_mock.await_args.args
    assert args[1] == "ext-99"  # conversation_ref
    assert args[2] == "¡Listo! Hemos actualizado tu dirección."


async def test_send_failure_returns_false(monkeypatch) -> None:
    integration = SimpleNamespace(id=UUID("33333333-3333-3333-3333-333333333333"), config={})
    monkeypatch.setattr(
        channel_routing, "get_active_integration", AsyncMock(return_value=integration)
    )
    monkeypatch.setattr(
        channel_routing,
        "get_integration_credentials_encrypted",
        AsyncMock(return_value=b"enc"),
    )
    monkeypatch.setattr(channel_routing, "get_settings", lambda: object())
    monkeypatch.setattr(channel_routing, "get_integration_crypto_key", lambda _s: b"key")
    monkeypatch.setattr(
        channel_routing, "decrypt_credentials", lambda _e, _k: json.dumps({"x": 1}).encode()
    )
    send_mock = AsyncMock(side_effect=RuntimeError("helpdesk down"))
    adapter_cls = MagicMock(return_value=SimpleNamespace(send_outbound=send_mock))

    with patch.object(channel_routing.IntegrationRegistry, "get", return_value=adapter_cls):
        ok = await deliver_message_to_helpdesk(
            MagicMock(), tenant_id=TENANT, conversation=_conv("chatwoot", "ext-1"), content="x"
        )
    assert ok is False
