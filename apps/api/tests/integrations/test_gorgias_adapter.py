"""Tests del GorgiasAdapter: registry + multi-tenant + protocol + HMAC.

Smoke test crítico: dos tenants distintos con domains de Gorgias distintos
coexisten sin cruce de credenciales — la misma garantía que 0.3/0.4/0.5.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.gorgias import (
    GorgiasAdapter,
    GorgiasClient,
    _build_reply_payload,
    verify_gorgias_signature,
)
from apps.api.integrations.registry import IntegrationRegistry

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_adapter_registered_under_helpdesk_gorgias(self) -> None:
        cls = IntegrationRegistry.get("helpdesk", "gorgias")
        assert cls is GorgiasAdapter

    def test_adapter_is_stateless(self) -> None:
        a = GorgiasAdapter()
        b = GorgiasAdapter()
        assert a is not b
        assert not hasattr(a, "_domain")
        assert not hasattr(a, "_token")


# ---------------------------------------------------------------------------
# Multi-tenant smoke test
# ---------------------------------------------------------------------------

_CTX_A = IntegrationContext(
    tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
    credentials={"oauth_token": "token_a"},
    config={"domain": "empresa-a"},
)
_CTX_B = IntegrationContext(
    tenant_id=UUID("22222222-2222-2222-2222-222222222222"),
    credentials={"oauth_token": "token_b"},
    config={"domain": "empresa-b"},
)


class TestMultiTenantIsolation:
    @pytest.mark.asyncio
    async def test_two_tenants_use_their_own_credentials(self) -> None:
        adapter = GorgiasAdapter()
        with patch("apps.api.integrations.gorgias.GorgiasClient") as MockClient:
            instance = MockClient.return_value
            instance.send_message = AsyncMock(return_value={})

            await adapter.send_outbound(_CTX_A, "101", "hola")
            await adapter.send_outbound(_CTX_B, "202", "hello")

            assert MockClient.call_count == 2
            call_a = MockClient.call_args_list[0]
            call_b = MockClient.call_args_list[1]
            assert call_a.kwargs["oauth_token"] == "token_a"
            assert call_a.kwargs["domain"] == "empresa-a"
            assert call_b.kwargs["oauth_token"] == "token_b"
            assert call_b.kwargs["domain"] == "empresa-b"

    @pytest.mark.asyncio
    async def test_basic_auth_credentials_passed_through(self) -> None:
        ctx = IntegrationContext(
            tenant_id=UUID("33333333-3333-3333-3333-333333333333"),
            credentials={"email": "ops@empresa-c.com", "api_key": "key_c"},
            config={"domain": "empresa-c"},
        )
        adapter = GorgiasAdapter()
        with patch("apps.api.integrations.gorgias.GorgiasClient") as MockClient:
            instance = MockClient.return_value
            instance.send_message = AsyncMock(return_value={})

            await adapter.send_outbound(ctx, "303", "hola")

            call = MockClient.call_args_list[0]
            assert call.kwargs["email"] == "ops@empresa-c.com"
            assert call.kwargs["api_key"] == "key_c"
            assert call.kwargs["oauth_token"] is None
            assert call.kwargs["domain"] == "empresa-c"


# ---------------------------------------------------------------------------
# GorgiasClient
# ---------------------------------------------------------------------------


class TestGorgiasClient:
    def test_base_url(self) -> None:
        client = GorgiasClient(domain="mitienda", oauth_token="tok")
        assert client.base_url == "https://mitienda.gorgias.com/api"

    def test_headers_bearer(self) -> None:
        client = GorgiasClient(domain="x", oauth_token="mytoken")
        headers = client._headers()
        assert headers["Authorization"] == "Bearer mytoken"

    def test_headers_basic(self) -> None:
        client = GorgiasClient(domain="x", email="u", api_key="p")
        headers = client._headers()
        # base64("u:p") == "dTpw"
        assert headers["Authorization"] == "Basic dTpw"

    def test_requires_some_auth(self) -> None:
        with pytest.raises(ValueError):
            GorgiasClient(domain="x")

    @pytest.mark.asyncio
    async def test_send_message(self) -> None:
        client = GorgiasClient(domain="d", oauth_token="t")
        ticket = {
            "messages": [
                {
                    "from_agent": False,
                    "channel": "email",
                    "source": {
                        "type": "email",
                        "to": [{"address": "support@store.gorgias.com"}],
                        "from": {"address": "cliente@example.com"},
                    },
                    "sender": {"id": 111},
                    "receiver": {"id": 222},
                }
            ]
        }
        get_resp = MagicMock()
        get_resp.json.return_value = ticket
        get_resp.raise_for_status = MagicMock()
        post_resp = MagicMock()
        post_resp.json.return_value = {"id": 1}
        post_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockHTTP:
            inst = MockHTTP.return_value.__aenter__.return_value
            inst.get = AsyncMock(return_value=get_resp)
            inst.post = AsyncMock(return_value=post_resp)
            result = await client.send_message(123, "hola")

        assert result == {"id": 1}
        body = inst.post.call_args.kwargs["json"]
        assert body["channel"] == "email"
        assert body["from_agent"] is True
        assert body["body_text"] == "hola"
        # source espejado: el cliente ahora es el destinatario
        assert body["source"]["to"] == [{"address": "cliente@example.com"}]
        assert body["receiver"] == {"id": 111}

    @pytest.mark.asyncio
    async def test_send_internal_note(self) -> None:
        client = GorgiasClient(domain="d", oauth_token="t")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": 2}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockHTTP:
            MockHTTP.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
            await client.send_internal_note(123, "nota interna")

        call_kwargs = MockHTTP.return_value.__aenter__.return_value.post.call_args
        body = call_kwargs.kwargs["json"]
        assert body["channel"] == "note"
        assert body["from_agent"] is True

    @pytest.mark.asyncio
    async def test_update_status(self) -> None:
        client = GorgiasClient(domain="d", oauth_token="t")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockHTTP:
            MockHTTP.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_resp)
            await client.update_status(123, "closed")

        call_kwargs = MockHTTP.return_value.__aenter__.return_value.put.call_args
        assert call_kwargs.kwargs["json"] == {"status": "closed"}

    @pytest.mark.asyncio
    async def test_assign_to_team(self) -> None:
        client = GorgiasClient(domain="d", oauth_token="t")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockHTTP:
            MockHTTP.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_resp)
            await client.assign_to_team(123, 99)

        call_kwargs = MockHTTP.return_value.__aenter__.return_value.put.call_args
        assert call_kwargs.kwargs["json"] == {"assignee_team": {"id": 99}}


# ---------------------------------------------------------------------------
# verify_gorgias_signature
# ---------------------------------------------------------------------------


class TestVerifySignature:
    def _make_sig(self, secret: str, body: bytes) -> str:
        mac = hmac.new(secret.encode(), body, hashlib.sha256).digest()
        return base64.b64encode(mac).decode()

    def test_valid_signature(self) -> None:
        body = b'{"event":{"type":"ticket-message-created"}}'
        secret = "mysecret"
        sig = self._make_sig(secret, body)
        assert verify_gorgias_signature(body, secret, sig) is True

    def test_wrong_secret(self) -> None:
        body = b"hello"
        sig = self._make_sig("correct_secret", body)
        assert verify_gorgias_signature(body, "wrong_secret", sig) is False

    def test_tampered_body(self) -> None:
        body = b"original"
        sig = self._make_sig("secret", body)
        assert verify_gorgias_signature(b"tampered", "secret", sig) is False

    def test_empty_signature(self) -> None:
        assert verify_gorgias_signature(b"body", "secret", "") is False


# ---------------------------------------------------------------------------
# parse_inbound_webhook
# ---------------------------------------------------------------------------

_GORGIAS_PAYLOAD = {
    "event": {"type": "ticket-message-created"},
    "data": {
        "ticket": {"id": 123, "subject": "Problema con mi pedido", "status": "open"},
        "message": {
            "id": 456,
            "body_text": "Hola, ¿dónde está mi pedido?",
            "from_agent": False,
            "sender": {"email": "cliente@example.com", "name": "María García"},
        },
    },
    "meta": {"domain": "mitienda"},
}


class TestParseInboundWebhook:
    @pytest.mark.asyncio
    async def test_parses_correctly(self) -> None:
        adapter = GorgiasAdapter()
        msg = await adapter.parse_inbound_webhook(_GORGIAS_PAYLOAD)

        assert msg.channel == "gorgias"
        assert msg.content == "Hola, ¿dónde está mi pedido?"
        assert msg.sender_email == "cliente@example.com"
        assert msg.sender_name == "María García"
        assert msg.subject == "Problema con mi pedido"
        assert "123" in msg.external_id
        assert "456" in msg.external_id

    @pytest.mark.asyncio
    async def test_external_id_includes_both_ids(self) -> None:
        adapter = GorgiasAdapter()
        msg = await adapter.parse_inbound_webhook(_GORGIAS_PAYLOAD)
        assert msg.external_id == "123:456"

    @pytest.mark.asyncio
    async def test_missing_sender_gracefully(self) -> None:
        payload = {
            "event": {"type": "ticket-message-created"},
            "data": {
                "ticket": {"id": 1},
                "message": {"id": 2, "body_text": "hola", "from_agent": False, "sender": {}},
            },
            "meta": {"domain": "x"},
        }
        adapter = GorgiasAdapter()
        msg = await adapter.parse_inbound_webhook(payload)
        assert msg.sender_email is None
        assert msg.sender_name is None


# ---------------------------------------------------------------------------
# HelpdeskProvider — protocol methods
# ---------------------------------------------------------------------------


class TestProtocolMethods:
    @pytest.mark.asyncio
    async def test_send_outbound_calls_send_message(self) -> None:
        adapter = GorgiasAdapter()
        with patch("apps.api.integrations.gorgias.GorgiasClient") as MockClient:
            instance = MockClient.return_value
            instance.send_message = AsyncMock(return_value={})
            await adapter.send_outbound(_CTX_A, "123", "Hola")
            instance.send_message.assert_called_once_with(123, "Hola")

    @pytest.mark.asyncio
    async def test_add_internal_note(self) -> None:
        adapter = GorgiasAdapter()
        with patch("apps.api.integrations.gorgias.GorgiasClient") as MockClient:
            instance = MockClient.return_value
            instance.send_internal_note = AsyncMock(return_value={})
            await adapter.add_internal_note(_CTX_A, "123", "nota")
            instance.send_internal_note.assert_called_once_with(123, "nota")

    @pytest.mark.asyncio
    async def test_assign_to_human_with_team_id(self) -> None:
        ctx = IntegrationContext(
            tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
            credentials={"oauth_token": "tok"},
            config={"domain": "d", "escalation_team_id": "99"},
        )
        adapter = GorgiasAdapter()
        with patch("apps.api.integrations.gorgias.GorgiasClient") as MockClient:
            instance = MockClient.return_value
            instance.assign_to_team = AsyncMock()
            await adapter.assign_to_human(ctx, "123", "cliente pide humano")
            instance.assign_to_team.assert_called_once_with(123, 99)

    @pytest.mark.asyncio
    async def test_assign_to_human_no_team_is_noop(self) -> None:
        adapter = GorgiasAdapter()
        with patch("apps.api.integrations.gorgias.GorgiasClient") as MockClient:
            instance = MockClient.return_value
            instance.assign_to_team = AsyncMock()
            await adapter.assign_to_human(_CTX_A, "123", "razon")
            instance.assign_to_team.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_status(self) -> None:
        adapter = GorgiasAdapter()
        with patch("apps.api.integrations.gorgias.GorgiasClient") as MockClient:
            instance = MockClient.return_value
            instance.update_status = AsyncMock()
            await adapter.update_status(_CTX_A, "123", "closed")
            instance.update_status.assert_called_once_with(123, "closed")

    @pytest.mark.asyncio
    async def test_push_escalation_posts_note_and_assigns(self) -> None:
        ctx = IntegrationContext(
            tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
            credentials={"oauth_token": "tok"},
            config={"domain": "mitienda", "escalation_team_id": "5"},
        )
        adapter = GorgiasAdapter()
        with patch("apps.api.integrations.gorgias.GorgiasClient") as MockClient:
            instance = MockClient.return_value
            instance.send_internal_note = AsyncMock(return_value={})
            instance.assign_to_team = AsyncMock()

            ref = await adapter.push_escalation(ctx, "123", "no sé", {"order": "1234"})

            instance.send_internal_note.assert_called_once()
            note_text = instance.send_internal_note.call_args.args[1]
            assert "Escalado" in note_text
            assert "no sé" in note_text

            instance.assign_to_team.assert_called_once_with(123, 5)

            assert ref.provider == "gorgias"
            assert ref.ticket_id == "123"
            assert "mitienda" in ref.url

    @pytest.mark.asyncio
    async def test_push_escalation_url_format(self) -> None:
        ctx = IntegrationContext(
            tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
            credentials={"oauth_token": "tok"},
            config={"domain": "cliente"},
        )
        adapter = GorgiasAdapter()
        with patch("apps.api.integrations.gorgias.GorgiasClient") as MockClient:
            instance = MockClient.return_value
            instance.send_internal_note = AsyncMock(return_value={})
            instance.assign_to_team = AsyncMock()

            ref = await adapter.push_escalation(ctx, "99", "razon", {})

        assert ref.url == "https://cliente.gorgias.com/app/ticket/99"


# ---------------------------------------------------------------------------
# _build_reply_payload (mirror del mensaje entrante)
# ---------------------------------------------------------------------------


class TestBuildReplyPayload:
    _TICKET = {
        "messages": [
            {
                "from_agent": False,
                "channel": "email",
                "source": {
                    "type": "email",
                    "to": [{"address": "support@store.gorgias.com"}],
                    "from": {"name": "Cliente", "address": "cliente@example.com"},
                },
                "sender": {"id": 111},
                "receiver": {"id": 222},
            }
        ]
    }

    def test_mirrors_inbound(self) -> None:
        reply = _build_reply_payload(self._TICKET, "Hola, tu pedido va en camino.")
        assert reply["from_agent"] is True
        assert reply["channel"] == "email"
        assert reply["via"] == "api"
        assert reply["body_text"] == "Hola, tu pedido va en camino."
        # body_html es obligatorio o Gorgias envía un email vacío
        assert reply["body_html"] == "<div>Hola, tu pedido va en camino.</div>"
        # source invertido: from = soporte, to = [cliente]
        assert reply["source"]["type"] == "email"
        assert reply["source"]["from"] == {"address": "support@store.gorgias.com"}
        assert reply["source"]["to"] == [{"name": "Cliente", "address": "cliente@example.com"}]
        # sender/receiver invertidos
        assert reply["sender"] == {"id": 222}
        assert reply["receiver"] == {"id": 111}

    def test_uses_last_inbound_when_agent_replies_exist(self) -> None:
        ticket = {
            "messages": [
                {
                    "from_agent": False,
                    "source": {"from": {"address": "a@x.com"}, "to": [{"address": "s@x.com"}]},
                    "sender": {"id": 1},
                    "receiver": {"id": 2},
                    "channel": "email",
                },
                {"from_agent": True, "source": {}, "sender": {"id": 2}, "receiver": {"id": 1}},
                {
                    "from_agent": False,
                    "source": {"from": {"address": "b@x.com"}, "to": [{"address": "s@x.com"}]},
                    "sender": {"id": 3},
                    "receiver": {"id": 2},
                    "channel": "email",
                },
            ]
        }
        reply = _build_reply_payload(ticket, "ok")
        assert reply["source"]["to"] == [{"address": "b@x.com"}]
        assert reply["receiver"] == {"id": 3}

    def test_raises_without_inbound(self) -> None:
        with pytest.raises(ValueError):
            _build_reply_payload({"messages": [{"from_agent": True}]}, "x")
