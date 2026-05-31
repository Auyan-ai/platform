"""Tests del ChatwootAdapter: registry + multi-tenant + protocol + webhook handler.

Smoke test crítico: dos tenants distintos con accounts de Chatwoot distintos
coexisten sin cruce de credenciales — la razón del refactor 0.4.
"""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.chatwoot import (
    ChatwootAdapter,
    ChatwootClient,
    verify_chatwoot_signature,
)
from apps.api.integrations.registry import IntegrationRegistry


def _mock_httpx(json_data: object) -> tuple[MagicMock, AsyncMock]:
    """Devuelve (mock_cm, mock_client) con response.json() → json_data."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client.post = AsyncMock(return_value=resp)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm, mock_client


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_adapter_registered_under_helpdesk_chatwoot(self) -> None:
        cls = IntegrationRegistry.get("helpdesk", "chatwoot")
        assert cls is ChatwootAdapter

    def test_adapter_is_stateless(self) -> None:
        a = ChatwootAdapter()
        b = ChatwootAdapter()
        assert a is not b
        assert not hasattr(a, "_base_url")
        assert not hasattr(a, "_token")
        assert not hasattr(a, "_account_id")


# ---------------------------------------------------------------------------
# Multi-tenant smoke test
# ---------------------------------------------------------------------------

_CTX_A = IntegrationContext(
    tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
    credentials={"api_access_token": "token_a"},
    config={"base_url": "https://chat-a.example.com", "account_id": "10"},
)
_CTX_B = IntegrationContext(
    tenant_id=UUID("22222222-2222-2222-2222-222222222222"),
    credentials={"api_access_token": "token_b"},
    config={"base_url": "https://chat-b.example.com", "account_id": "20"},
)


class TestMultiTenantIsolation:
    @pytest.mark.asyncio
    async def test_two_tenants_use_their_own_credentials(self) -> None:
        adapter = ChatwootAdapter()
        with patch("apps.api.integrations.chatwoot.ChatwootClient") as MockClient:
            instance = MockClient.return_value
            instance.send_message = AsyncMock(return_value={})

            await adapter.send_outbound(_CTX_A, "100", "hola")
            await adapter.send_outbound(_CTX_B, "200", "hello")

            assert MockClient.call_count == 2
            call_a = MockClient.call_args_list[0]
            call_b = MockClient.call_args_list[1]
            assert call_a.kwargs["api_access_token"] == "token_a"
            assert call_a.kwargs["base_url"] == "https://chat-a.example.com"
            assert call_b.kwargs["api_access_token"] == "token_b"
            assert call_b.kwargs["base_url"] == "https://chat-b.example.com"


# ---------------------------------------------------------------------------
# ChatwootClient constructor
# ---------------------------------------------------------------------------


class TestChatwootClient:
    def test_url_helper(self) -> None:
        client = ChatwootClient("https://app.chatwoot.com", "tok", 7)
        assert client._url("/conversations/1/messages") == (
            "https://app.chatwoot.com/api/v1/accounts/7/conversations/1/messages"
        )

    def test_url_strips_trailing_slash(self) -> None:
        client = ChatwootClient("https://app.chatwoot.com/", "tok", 3)
        assert client._url("/x") == "https://app.chatwoot.com/api/v1/accounts/3/x"

    def test_headers_include_token(self) -> None:
        client = ChatwootClient("https://x.com", "mytoken", 1)
        assert client._headers()["api_access_token"] == "mytoken"

    @pytest.mark.asyncio
    async def test_validate_returns_account(self) -> None:
        mock_cm, mock_client = _mock_httpx({"id": 5, "name": "Marea"})
        with patch("apps.api.integrations.chatwoot.httpx.AsyncClient", return_value=mock_cm):
            account = await ChatwootClient("https://app.chatwoot.com", "tok", 5).validate()
        assert account["name"] == "Marea"
        assert mock_client.get.call_args[0][0] == (
            "https://app.chatwoot.com/api/v1/accounts/5"
        )

    @pytest.mark.asyncio
    async def test_list_webhooks_unwraps_payload(self) -> None:
        mock_cm, _ = _mock_httpx({"payload": [{"id": 1, "url": "https://a/webhooks/chatwoot"}]})
        with patch("apps.api.integrations.chatwoot.httpx.AsyncClient", return_value=mock_cm):
            hooks = await ChatwootClient("https://app.chatwoot.com", "tok", 5).list_webhooks()
        assert hooks == [{"id": 1, "url": "https://a/webhooks/chatwoot"}]

    @pytest.mark.asyncio
    async def test_list_webhooks_accepts_flat_list(self) -> None:
        mock_cm, _ = _mock_httpx([{"id": 2, "url": "https://b/webhooks/chatwoot"}])
        with patch("apps.api.integrations.chatwoot.httpx.AsyncClient", return_value=mock_cm):
            hooks = await ChatwootClient("https://app.chatwoot.com", "tok", 5).list_webhooks()
        assert hooks[0]["id"] == 2

    @pytest.mark.asyncio
    async def test_create_webhook_posts_url_and_subscriptions(self) -> None:
        mock_cm, mock_client = _mock_httpx({"id": 9, "url": "https://api/webhooks/chatwoot"})
        with patch("apps.api.integrations.chatwoot.httpx.AsyncClient", return_value=mock_cm):
            await ChatwootClient("https://app.chatwoot.com", "tok", 5).create_webhook(
                "https://api/webhooks/chatwoot", ["message_created"]
            )
        url = mock_client.post.call_args[0][0]
        assert url == "https://app.chatwoot.com/api/v1/accounts/5/webhooks"
        body = mock_client.post.call_args.kwargs["json"]
        assert body == {
            "url": "https://api/webhooks/chatwoot",
            "subscriptions": ["message_created"],
        }


# ---------------------------------------------------------------------------
# parse_inbound_webhook
# ---------------------------------------------------------------------------

_SAMPLE_PAYLOAD: dict = {
    "event": "message_created",
    "id": 42,
    "content": "¿Dónde está mi pedido?",
    "message_type": "incoming",
    "conversation": {"id": 7},
    "sender": {"id": 1, "type": "contact", "email": "user@test.com", "name": "Juan"},
    "account": {"id": 5},
}


class TestParseInboundWebhook:
    @pytest.mark.asyncio
    async def test_basic_fields(self) -> None:
        adapter = ChatwootAdapter()
        msg = await adapter.parse_inbound_webhook(_SAMPLE_PAYLOAD)
        assert msg.external_id == "42"
        assert msg.channel == "chatwoot"
        assert msg.content == "¿Dónde está mi pedido?"
        assert msg.sender_email == "user@test.com"
        assert msg.sender_name == "Juan"

    @pytest.mark.asyncio
    async def test_missing_sender(self) -> None:
        payload = {**_SAMPLE_PAYLOAD, "sender": None}
        adapter = ChatwootAdapter()
        msg = await adapter.parse_inbound_webhook(payload)
        assert msg.sender_email is None
        assert msg.sender_name is None

    @pytest.mark.asyncio
    async def test_empty_content(self) -> None:
        payload = {**_SAMPLE_PAYLOAD, "content": None}
        adapter = ChatwootAdapter()
        msg = await adapter.parse_inbound_webhook(payload)
        assert msg.content == ""


# ---------------------------------------------------------------------------
# verify_chatwoot_signature
# ---------------------------------------------------------------------------


class TestVerifyChatwootSignature:
    def _make_sig(self, secret: str, timestamp: str, body: bytes) -> str:
        message = timestamp.encode() + b"." + body
        digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_valid_signature(self) -> None:
        secret = "cw_secret"
        ts = "1780045200"
        body = b'{"event":"message_created","content":"hola"}'
        assert verify_chatwoot_signature(
            signing_secret=secret,
            timestamp=ts,
            raw_body=body,
            signature_header=self._make_sig(secret, ts, body),
        )

    def test_tampered_body_fails(self) -> None:
        secret = "cw_secret"
        ts = "1780045200"
        signature = self._make_sig(secret, ts, b'{"content":"hola"}')
        assert not verify_chatwoot_signature(
            signing_secret=secret,
            timestamp=ts,
            raw_body=b'{"content":"pedido #1002"}',
            signature_header=signature,
        )

    def test_wrong_secret_fails(self) -> None:
        ts = "1780045200"
        body = b'{"content":"hola"}'
        signature = self._make_sig("right_secret", ts, body)
        assert not verify_chatwoot_signature(
            signing_secret="wrong_secret",
            timestamp=ts,
            raw_body=body,
            signature_header=signature,
        )

    def test_missing_prefix_fails(self) -> None:
        secret = "cw_secret"
        ts = "1780045200"
        body = b'{"content":"hola"}'
        signature = self._make_sig(secret, ts, body).removeprefix("sha256=")
        assert not verify_chatwoot_signature(
            signing_secret=secret,
            timestamp=ts,
            raw_body=body,
            signature_header=signature,
        )


# ---------------------------------------------------------------------------
# Protocol methods — delegan a ChatwootClient
# ---------------------------------------------------------------------------

_CTX = IntegrationContext(
    tenant_id=UUID("33333333-3333-3333-3333-333333333333"),
    credentials={"api_access_token": "tok"},
    config={"base_url": "https://x.com", "account_id": "1"},
)


class TestAdapterMethods:
    @pytest.mark.asyncio
    async def test_send_outbound(self) -> None:
        adapter = ChatwootAdapter()
        with patch("apps.api.integrations.chatwoot.ChatwootClient") as MockClient:
            inst = MockClient.return_value
            inst.send_message = AsyncMock(return_value={})
            await adapter.send_outbound(_CTX, "5", "hola")
        inst.send_message.assert_awaited_once_with(5, "hola")

    @pytest.mark.asyncio
    async def test_add_internal_note(self) -> None:
        adapter = ChatwootAdapter()
        with patch("apps.api.integrations.chatwoot.ChatwootClient") as MockClient:
            inst = MockClient.return_value
            inst.send_internal_note = AsyncMock(return_value={})
            await adapter.add_internal_note(_CTX, "5", "nota interna")
        inst.send_internal_note.assert_awaited_once_with(5, "nota interna")

    @pytest.mark.asyncio
    async def test_assign_to_human_with_team(self) -> None:
        ctx = IntegrationContext(
            tenant_id=UUID("33333333-3333-3333-3333-333333333333"),
            credentials={"api_access_token": "tok"},
            config={"base_url": "https://x.com", "account_id": "1", "escalation_team_id": "9"},
        )
        adapter = ChatwootAdapter()
        with patch("apps.api.integrations.chatwoot.ChatwootClient") as MockClient:
            inst = MockClient.return_value
            inst.assign_to_team = AsyncMock(return_value={})
            await adapter.assign_to_human(ctx, "5", "cliente frustrado")
        inst.assign_to_team.assert_awaited_once_with(5, 9)

    @pytest.mark.asyncio
    async def test_assign_to_human_no_team_is_noop(self) -> None:
        adapter = ChatwootAdapter()
        with patch("apps.api.integrations.chatwoot.ChatwootClient") as MockClient:
            inst = MockClient.return_value
            inst.assign_to_team = AsyncMock()
            await adapter.assign_to_human(_CTX, "5", "reason")
        inst.assign_to_team.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_status(self) -> None:
        adapter = ChatwootAdapter()
        with patch("apps.api.integrations.chatwoot.ChatwootClient") as MockClient:
            inst = MockClient.return_value
            inst.update_status = AsyncMock()
            await adapter.update_status(_CTX, "5", "resolved")
        inst.update_status.assert_awaited_once_with(5, "resolved")

    @pytest.mark.asyncio
    async def test_push_escalation_returns_external_ref(self) -> None:
        ctx = IntegrationContext(
            tenant_id=UUID("33333333-3333-3333-3333-333333333333"),
            credentials={"api_access_token": "tok"},
            config={
                "base_url": "https://chatwoot.example.com",
                "account_id": "3",
                "escalation_team_id": "7",
            },
        )
        adapter = ChatwootAdapter()
        with patch("apps.api.integrations.chatwoot.ChatwootClient") as MockClient:
            inst = MockClient.return_value
            inst.send_internal_note = AsyncMock(return_value={})
            inst.assign_to_team = AsyncMock(return_value={})
            ref = await adapter.push_escalation(ctx, "99", "no resuelto", {"aop": "consulta"})

        assert ref.provider == "chatwoot"
        assert ref.ticket_id == "99"
        assert ref.url == "https://chatwoot.example.com/app/accounts/3/conversations/99"
        inst.send_internal_note.assert_awaited_once()
        inst.assign_to_team.assert_awaited_once_with(99, 7)

    @pytest.mark.asyncio
    async def test_push_escalation_no_team(self) -> None:
        adapter = ChatwootAdapter()
        with patch("apps.api.integrations.chatwoot.ChatwootClient") as MockClient:
            inst = MockClient.return_value
            inst.send_internal_note = AsyncMock(return_value={})
            inst.assign_to_team = AsyncMock()
            await adapter.push_escalation(_CTX, "10", "reason", {})
        inst.assign_to_team.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_credentials_raises(self) -> None:
        ctx_bad = IntegrationContext(
            tenant_id=UUID("44444444-4444-4444-4444-444444444444"),
            credentials={},
            config={"base_url": "https://x.com", "account_id": "1"},
        )
        adapter = ChatwootAdapter()
        with pytest.raises(KeyError):
            await adapter.send_outbound(ctx_bad, "1", "hello")
