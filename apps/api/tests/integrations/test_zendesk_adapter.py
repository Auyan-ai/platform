"""Tests del ZendeskAdapter: registry + multi-tenant + protocol + HMAC + webhook handler.

Smoke test crítico: dos tenants distintos con subdomains de Zendesk distintos
coexisten sin cruce de credenciales — la razón del refactor 0.5.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.integrations.zendesk import (
    ZendeskAdapter,
    ZendeskClient,
    verify_zendesk_signature,
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_adapter_registered_under_helpdesk_zendesk(self) -> None:
        cls = IntegrationRegistry.get("helpdesk", "zendesk")
        assert cls is ZendeskAdapter

    def test_adapter_is_stateless(self) -> None:
        a = ZendeskAdapter()
        b = ZendeskAdapter()
        assert a is not b
        assert not hasattr(a, "_subdomain")
        assert not hasattr(a, "_token")


# ---------------------------------------------------------------------------
# Multi-tenant smoke test
# ---------------------------------------------------------------------------

_CTX_A = IntegrationContext(
    tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
    credentials={"oauth_token": "token_a"},
    config={"subdomain": "empresa-a"},
)
_CTX_B = IntegrationContext(
    tenant_id=UUID("22222222-2222-2222-2222-222222222222"),
    credentials={"oauth_token": "token_b"},
    config={"subdomain": "empresa-b"},
)


class TestMultiTenantIsolation:
    @pytest.mark.asyncio
    async def test_two_tenants_use_their_own_credentials(self) -> None:
        adapter = ZendeskAdapter()
        with patch("apps.api.integrations.zendesk.ZendeskClient") as MockClient:
            instance = MockClient.return_value
            instance.add_comment = AsyncMock(return_value={})

            await adapter.send_outbound(_CTX_A, "101", "hola")
            await adapter.send_outbound(_CTX_B, "202", "hello")

            assert MockClient.call_count == 2
            call_a = MockClient.call_args_list[0]
            call_b = MockClient.call_args_list[1]
            assert call_a.kwargs["oauth_token"] == "token_a"
            assert call_a.kwargs["subdomain"] == "empresa-a"
            assert call_b.kwargs["oauth_token"] == "token_b"
            assert call_b.kwargs["subdomain"] == "empresa-b"

    @pytest.mark.asyncio
    async def test_api_token_credentials_passed_through(self) -> None:
        """El modo managed (email + api_token) llega intacto al ZendeskClient."""
        ctx = IntegrationContext(
            tenant_id=UUID("55555555-5555-5555-5555-555555555555"),
            credentials={"email": "agent@test.com", "api_token": "tok_x"},
            config={"subdomain": "empresa-c"},
        )
        adapter = ZendeskAdapter()
        with patch("apps.api.integrations.zendesk.ZendeskClient") as MockClient:
            instance = MockClient.return_value
            instance.add_comment = AsyncMock(return_value={})
            await adapter.send_outbound(ctx, "303", "hola")
            call = MockClient.call_args
            assert call.kwargs["email"] == "agent@test.com"
            assert call.kwargs["api_token"] == "tok_x"
            assert call.kwargs["oauth_token"] is None
            assert call.kwargs["subdomain"] == "empresa-c"


# ---------------------------------------------------------------------------
# ZendeskClient
# ---------------------------------------------------------------------------


class TestZendeskClient:
    def test_base_url(self) -> None:
        client = ZendeskClient("myco", oauth_token="tok")
        assert client.base_url == "https://myco.zendesk.com/api/v2"

    def test_headers_include_bearer(self) -> None:
        client = ZendeskClient("myco", oauth_token="mytoken")
        assert client._headers()["Authorization"] == "Bearer mytoken"
        assert client._headers()["Content-Type"] == "application/json"

    def test_headers_basic_auth_with_api_token(self) -> None:
        client = ZendeskClient("myco", email="agent@test.com", api_token="tok123")
        expected = base64.b64encode(b"agent@test.com/token:tok123").decode()
        assert client._headers()["Authorization"] == f"Basic {expected}"
        assert client._headers()["Content-Type"] == "application/json"

    def test_requires_some_auth(self) -> None:
        with pytest.raises(ValueError, match="oauth_token"):
            ZendeskClient("myco")


# ---------------------------------------------------------------------------
# parse_inbound_webhook
# ---------------------------------------------------------------------------

_SAMPLE_PAYLOAD: dict = {
    "ticket_id": "456",
    "subject": "¿Dónde está mi pedido?",
    "content": "Hola, necesito saber el estado de mi pedido #1234.",
    "requester_email": "cliente@test.com",
    "requester_name": "María López",
    "subdomain": "empresa-x",
}


class TestParseInboundWebhook:
    @pytest.mark.asyncio
    async def test_basic_fields(self) -> None:
        adapter = ZendeskAdapter()
        msg = await adapter.parse_inbound_webhook(_SAMPLE_PAYLOAD)
        assert msg.external_id == "456"
        assert msg.channel == "zendesk"
        assert msg.content == "Hola, necesito saber el estado de mi pedido #1234."
        assert msg.sender_email == "cliente@test.com"
        assert msg.sender_name == "María López"
        assert msg.subject == "¿Dónde está mi pedido?"

    @pytest.mark.asyncio
    async def test_missing_email(self) -> None:
        payload = {**_SAMPLE_PAYLOAD, "requester_email": None}
        adapter = ZendeskAdapter()
        msg = await adapter.parse_inbound_webhook(payload)
        assert msg.sender_email is None

    @pytest.mark.asyncio
    async def test_empty_content_normalizes_to_empty_string(self) -> None:
        payload = {**_SAMPLE_PAYLOAD, "content": None}
        adapter = ZendeskAdapter()
        msg = await adapter.parse_inbound_webhook(payload)
        assert msg.content == ""


# ---------------------------------------------------------------------------
# Protocol methods — delegan a ZendeskClient
# ---------------------------------------------------------------------------

_CTX = IntegrationContext(
    tenant_id=UUID("33333333-3333-3333-3333-333333333333"),
    credentials={"oauth_token": "tok"},
    config={"subdomain": "testco"},
)


class TestAdapterMethods:
    @pytest.mark.asyncio
    async def test_send_outbound(self) -> None:
        adapter = ZendeskAdapter()
        with patch("apps.api.integrations.zendesk.ZendeskClient") as MockClient:
            inst = MockClient.return_value
            inst.add_comment = AsyncMock(return_value={})
            await adapter.send_outbound(_CTX, "10", "respuesta")
        inst.add_comment.assert_awaited_once_with("10", "respuesta", public=True)

    @pytest.mark.asyncio
    async def test_add_internal_note(self) -> None:
        adapter = ZendeskAdapter()
        with patch("apps.api.integrations.zendesk.ZendeskClient") as MockClient:
            inst = MockClient.return_value
            inst.add_comment = AsyncMock(return_value={})
            await adapter.add_internal_note(_CTX, "10", "nota interna")
        inst.add_comment.assert_awaited_once_with("10", "nota interna", public=False)

    @pytest.mark.asyncio
    async def test_assign_to_human_with_group(self) -> None:
        ctx = IntegrationContext(
            tenant_id=UUID("33333333-3333-3333-3333-333333333333"),
            credentials={"oauth_token": "tok"},
            config={"subdomain": "testco", "escalation_group_id": "42"},
        )
        adapter = ZendeskAdapter()
        with patch("apps.api.integrations.zendesk.ZendeskClient") as MockClient:
            inst = MockClient.return_value
            inst.update_ticket = AsyncMock(return_value={})
            await adapter.assign_to_human(ctx, "10", "cliente frustrado")
        inst.update_ticket.assert_awaited_once_with("10", group_id=42)

    @pytest.mark.asyncio
    async def test_assign_to_human_no_group_is_noop(self) -> None:
        adapter = ZendeskAdapter()
        with patch("apps.api.integrations.zendesk.ZendeskClient") as MockClient:
            inst = MockClient.return_value
            inst.update_ticket = AsyncMock()
            await adapter.assign_to_human(_CTX, "10", "reason")
        inst.update_ticket.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_status(self) -> None:
        adapter = ZendeskAdapter()
        with patch("apps.api.integrations.zendesk.ZendeskClient") as MockClient:
            inst = MockClient.return_value
            inst.update_ticket = AsyncMock(return_value={})
            await adapter.update_status(_CTX, "10", "solved")
        inst.update_ticket.assert_awaited_once_with("10", status="solved")

    @pytest.mark.asyncio
    async def test_push_escalation_returns_external_ref(self) -> None:
        ctx = IntegrationContext(
            tenant_id=UUID("33333333-3333-3333-3333-333333333333"),
            credentials={"oauth_token": "tok"},
            config={"subdomain": "testco", "escalation_group_id": "7"},
        )
        adapter = ZendeskAdapter()
        with patch("apps.api.integrations.zendesk.ZendeskClient") as MockClient:
            inst = MockClient.return_value
            inst.update_ticket = AsyncMock(return_value={})
            ref = await adapter.push_escalation(ctx, "99", "no resuelto", {"aop": "devolucion"})

        assert ref.provider == "zendesk"
        assert ref.ticket_id == "99"
        assert ref.url == "https://testco.zendesk.com/agent/tickets/99"
        inst.update_ticket.assert_awaited_once()
        call_kwargs = inst.update_ticket.call_args.kwargs
        assert call_kwargs["status"] == "pending"
        assert call_kwargs["group_id"] == 7
        assert "no resuelto" in call_kwargs["comment_body"]
        assert call_kwargs["comment_public"] is False

    @pytest.mark.asyncio
    async def test_push_escalation_no_group(self) -> None:
        adapter = ZendeskAdapter()
        with patch("apps.api.integrations.zendesk.ZendeskClient") as MockClient:
            inst = MockClient.return_value
            inst.update_ticket = AsyncMock(return_value={})
            ref = await adapter.push_escalation(_CTX, "50", "reason", {})
        # group_id debe ser None cuando no hay escalation_group_id
        call_kwargs = inst.update_ticket.call_args.kwargs
        assert call_kwargs["group_id"] is None
        assert ref.provider == "zendesk"

    @pytest.mark.asyncio
    async def test_missing_all_creds_raises(self) -> None:
        ctx_bad = IntegrationContext(
            tenant_id=UUID("44444444-4444-4444-4444-444444444444"),
            credentials={},
            config={"subdomain": "testco"},
        )
        adapter = ZendeskAdapter()
        with pytest.raises(ValueError, match="oauth_token"):
            await adapter.send_outbound(ctx_bad, "1", "hello")


# ---------------------------------------------------------------------------
# verify_zendesk_signature
# ---------------------------------------------------------------------------


class TestVerifyZendeskSignature:
    def _make_sig(self, secret: str, timestamp: str, body: bytes) -> str:
        msg = timestamp.encode() + body
        digest = hmac.new(
            key=secret.encode(), msg=msg, digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(digest).decode()

    def test_valid_signature(self) -> None:
        secret = "mi_secreto"
        ts = "1716000000"
        body = b'{"ticket_id":"1"}'
        sig = self._make_sig(secret, ts, body)
        assert verify_zendesk_signature(
            signing_secret=secret,
            timestamp=ts,
            raw_body=body,
            signature_header=sig,
        )

    def test_wrong_secret_fails(self) -> None:
        ts = "1716000000"
        body = b'{"ticket_id":"1"}'
        sig = self._make_sig("secreto_correcto", ts, body)
        assert not verify_zendesk_signature(
            signing_secret="secreto_incorrecto",
            timestamp=ts,
            raw_body=body,
            signature_header=sig,
        )

    def test_tampered_body_fails(self) -> None:
        secret = "mi_secreto"
        ts = "1716000000"
        sig = self._make_sig(secret, ts, b'{"ticket_id":"1"}')
        assert not verify_zendesk_signature(
            signing_secret=secret,
            timestamp=ts,
            raw_body=b'{"ticket_id":"2"}',  # body alterado
            signature_header=sig,
        )
