"""Tests del ZendeskAdapter: registry + multi-tenant + protocol + HMAC + webhook handler.

Smoke test crítico: dos tenants distintos con subdomains de Zendesk distintos
coexisten sin cruce de credenciales — la razón del refactor 0.5.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx
import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.integrations.zendesk import (
    ZENDESK_OAUTH_SCOPES,
    ZendeskAdapter,
    ZendeskClient,
    clear_client_credentials_cache,
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

    @pytest.mark.asyncio
    async def test_headers_include_bearer(self) -> None:
        client = ZendeskClient("myco", oauth_token="mytoken")
        headers = await client._headers()
        assert headers["Authorization"] == "Bearer mytoken"
        assert headers["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_headers_basic_auth_with_api_token(self) -> None:
        client = ZendeskClient("myco", email="agent@test.com", api_token="tok123")
        expected = base64.b64encode(b"agent@test.com/token:tok123").decode()
        headers = await client._headers()
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Content-Type"] == "application/json"

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
        digest = hmac.new(key=secret.encode(), msg=msg, digestmod=hashlib.sha256).digest()
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


# ---------------------------------------------------------------------------
# OAuth client_credentials (reemplazo de los API tokens, deprecados por Zendesk)
# ---------------------------------------------------------------------------


class _ZendeskStub:
    """Transport httpx que simula /oauth/tokens + /api/v2/tickets."""

    def __init__(self, *, expires_in: int = 1800, ticket_401_once: bool = False) -> None:
        self.token_requests: list[dict] = []
        self.ticket_auth_headers: list[str] = []
        self._expires_in = expires_in
        self._ticket_401_once = ticket_401_once
        self._issued = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/tokens":
            self.token_requests.append(json.loads(request.content))
            self._issued += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"cc_token_{self._issued}",
                    "token_type": "bearer",
                    "expires_in": self._expires_in,
                },
            )
        self.ticket_auth_headers.append(request.headers["Authorization"])
        if self._ticket_401_once and len(self.ticket_auth_headers) == 1:
            return httpx.Response(401, json={"error": "invalid_token"})
        return httpx.Response(200, json={"ticket": {"id": 10}})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture(autouse=True)
def _clear_token_cache() -> None:
    clear_client_credentials_cache()


class TestClientCredentials:
    @pytest.mark.asyncio
    async def test_fetches_token_with_client_credentials_grant(self) -> None:
        stub = _ZendeskStub()
        client = ZendeskClient(
            "myco", client_id="auyan", client_secret="s3cret", transport=stub.transport()
        )

        await client.add_comment("10", "hola")

        assert stub.token_requests == [
            {
                "grant_type": "client_credentials",
                "client_id": "auyan",
                "client_secret": "s3cret",
                "scope": ZENDESK_OAUTH_SCOPES,
            }
        ]
        assert stub.ticket_auth_headers == ["Bearer cc_token_1"]

    @pytest.mark.asyncio
    async def test_token_is_cached_across_clients(self) -> None:
        """El adapter crea un ZendeskClient por llamada: el token se reutiliza."""
        stub = _ZendeskStub()
        for _ in range(3):
            client = ZendeskClient(
                "myco", client_id="auyan", client_secret="s3cret", transport=stub.transport()
            )
            await client.add_comment("10", "hola")

        assert len(stub.token_requests) == 1
        assert stub.ticket_auth_headers == ["Bearer cc_token_1"] * 3

    @pytest.mark.asyncio
    async def test_expired_token_is_refreshed(self) -> None:
        # expires_in por debajo del margen de refresco → nunca se considera vigente.
        stub = _ZendeskStub(expires_in=1)
        for _ in range(2):
            client = ZendeskClient(
                "myco", client_id="auyan", client_secret="s3cret", transport=stub.transport()
            )
            await client.add_comment("10", "hola")

        assert len(stub.token_requests) == 2
        assert stub.ticket_auth_headers == ["Bearer cc_token_1", "Bearer cc_token_2"]

    @pytest.mark.asyncio
    async def test_401_invalidates_token_and_retries_once(self) -> None:
        stub = _ZendeskStub(ticket_401_once=True)
        client = ZendeskClient(
            "myco", client_id="auyan", client_secret="s3cret", transport=stub.transport()
        )

        await client.add_comment("10", "hola")

        assert len(stub.token_requests) == 2
        assert stub.ticket_auth_headers == ["Bearer cc_token_1", "Bearer cc_token_2"]

    @pytest.mark.asyncio
    async def test_cache_is_isolated_per_subdomain(self) -> None:
        """Dos tenants (subdomains distintos) nunca comparten token."""
        stub = _ZendeskStub()
        a = ZendeskClient(
            "empresa-a", client_id="auyan", client_secret="a", transport=stub.transport()
        )
        b = ZendeskClient(
            "empresa-b", client_id="auyan", client_secret="b", transport=stub.transport()
        )

        await a.add_comment("1", "hola")
        await b.add_comment("2", "hola")

        assert len(stub.token_requests) == 2
        assert stub.ticket_auth_headers == ["Bearer cc_token_1", "Bearer cc_token_2"]

    @pytest.mark.asyncio
    async def test_token_endpoint_error_raises(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(401, json={"error": "invalid_client"})
        )
        client = ZendeskClient("myco", client_id="auyan", client_secret="bad", transport=transport)
        with pytest.raises(httpx.HTTPStatusError):
            await client.add_comment("10", "hola")

    def test_rejects_partial_client_credentials(self) -> None:
        with pytest.raises(ValueError, match="client_id"):
            ZendeskClient("myco", client_id="auyan")

    @pytest.mark.asyncio
    async def test_adapter_passes_client_credentials(self) -> None:
        ctx = IntegrationContext(
            tenant_id=UUID("66666666-6666-6666-6666-666666666666"),
            credentials={"client_id": "auyan", "client_secret": "s3cret"},
            config={"subdomain": "empresa-d"},
        )
        adapter = ZendeskAdapter()
        with patch("apps.api.integrations.zendesk.ZendeskClient") as MockClient:
            MockClient.return_value.add_comment = AsyncMock(return_value={})
            await adapter.send_outbound(ctx, "404", "hola")
        call = MockClient.call_args
        assert call.kwargs["client_id"] == "auyan"
        assert call.kwargs["client_secret"] == "s3cret"
        assert call.kwargs["subdomain"] == "empresa-d"
