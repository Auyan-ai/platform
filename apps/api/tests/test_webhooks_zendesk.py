"""Tests del webhook handler de Zendesk.

El Trigger solo manda IDs; el comentario, su autor y el requester se leen de la
API. Bugs cubiertos (todos vistos en el E2E en vivo):
- placeholder inexistente → content vacío → 200 mudo;
- texto libre sin escapar en el body → JSON inválido → 500;
- idempotencia por ticket (solo se procesaba el primer mensaje);
- la respuesta del propio agente re-disparaba el Trigger (loop).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from apps.api.core.config import get_settings
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.zendesk import (
    ZendeskAdapter,
    ZendeskInboundComment,
    clear_client_credentials_cache,
    select_inbound_comment,
)
from apps.api.routers.webhooks_zendesk import (
    _ignore_reason,
    _parse_payload,
    _placeholder_value,
    router,
)
from apps.api.tests.conftest import TENANT_ID
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_client_credentials_cache()


class TestPlaceholderValue:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("123", "123"),
            (123, "123"),
            ("  456 ", "456"),
            ("", None),
            (None, None),
            ("{{ticket.latest_comment.id}}", None),
            ("{% for c in ticket.comments limit:1 %}{{c.id}}{% endfor %}", None),
        ],
    )
    def test_normalizes(self, value: Any, expected: str | None) -> None:
        assert _placeholder_value(value) == expected


class TestParsePayload:
    def test_valid_object(self) -> None:
        assert _parse_payload(b'{"ticket_id": "2"}') == {"ticket_id": "2"}

    @pytest.mark.parametrize(
        "body",
        [
            # Texto libre sin escapar (lo que hacía {{ticket.latest_comment}}).
            b'{"ticket_id": "2", "content": "dijo "hola" y se fue"}',
            b"not json",
            b"[1, 2]",
            b"\xff\xfe",
        ],
    )
    def test_invalid_returns_none(self, body: bytes) -> None:
        assert _parse_payload(body) is None

    def test_router_returns_400_on_invalid_json(self) -> None:
        app = FastAPI()
        app.include_router(router)
        app.state.agent_service = object()
        # Sin .env (CI): Settings real falla por variables obligatorias.
        app.dependency_overrides[get_settings] = lambda: object()
        with TestClient(app) as client:
            r = client.post(
                "/webhooks/zendesk",
                content=b'{"subdomain": "acme", "content": "roto "aqui""}',
                headers={"Content-Type": "application/json"},
            )
        assert r.status_code == 400
        assert r.json()["detail"] == "invalid_json"


def _comment(**overrides: Any) -> ZendeskInboundComment:
    base: dict[str, Any] = {
        "ticket_id": "2",
        "comment_id": "900",
        "author_id": "7",
        "public": True,
        "content": "¿dónde está mi pedido #1181?",
        "requester_id": "7",
        "requester_email": "cliente@test.com",
        "requester_name": "Cliente",
        "subject": None,
    }
    return ZendeskInboundComment(**{**base, **overrides})


class TestIgnoreReason:
    def test_customer_public_comment_is_processed(self) -> None:
        assert _ignore_reason(_comment()) is None

    def test_agent_reply_is_ignored(self) -> None:
        """La respuesta pública del agente re-dispara el Trigger: no reentra."""
        assert _ignore_reason(_comment(author_id="99")) == "non_requester_comment"

    def test_private_note_is_ignored(self) -> None:
        assert _ignore_reason(_comment(public=False)) == "private_comment"

    def test_empty_content_is_ignored(self) -> None:
        assert _ignore_reason(_comment(content="  ")) == "empty_content"


class TestSelectInboundComment:
    _COMMENTS = [
        {"id": 3, "public": False},
        {"id": 2, "public": True},
        {"id": 1, "public": True},
    ]

    def test_by_id(self) -> None:
        assert select_inbound_comment(self._COMMENTS, "1") == {"id": 1, "public": True}

    def test_without_id_takes_latest_public(self) -> None:
        assert select_inbound_comment(self._COMMENTS, None) == {"id": 2, "public": True}

    def test_unknown_id_falls_back_to_latest_public(self) -> None:
        assert select_inbound_comment(self._COMMENTS, "404") == {"id": 2, "public": True}

    def test_no_public_comments(self) -> None:
        assert select_inbound_comment([{"id": 3, "public": False}], None) is None


class TestFetchInboundComment:
    @pytest.mark.asyncio
    async def test_reads_comment_and_requester_from_api(self) -> None:
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            assert request.headers["Authorization"] == "Bearer tok"
            if request.url.path == "/api/v2/tickets/2.json":
                assert request.url.params["include"] == "users"
                return httpx.Response(
                    200,
                    json={
                        "ticket": {
                            "id": 2,
                            "requester_id": 7,
                            "subject": "Pedido",
                            "via": {"channel": "web"},
                        },
                        "users": [
                            {"id": 99, "email": "agente@acme.test", "name": "Agente"},
                            {"id": 7, "email": "cliente@test.com", "name": "Cliente"},
                        ],
                    },
                )
            assert request.url.params["sort_order"] == "desc"
            return httpx.Response(
                200,
                json={
                    "comments": [
                        {
                            "id": 901,
                            "author_id": 7,
                            "public": True,
                            "plain_body": 'dijo "hola"\ny',
                            "via": {"channel": "email"},
                        },
                        {"id": 900, "author_id": 99, "public": True, "plain_body": "respuesta"},
                    ]
                },
            )

        ctx = IntegrationContext(
            tenant_id=TENANT_ID, credentials={"oauth_token": "tok"}, config={"subdomain": "acme"}
        )
        adapter = ZendeskAdapter()
        original = adapter._client

        def _client_with_transport(c: IntegrationContext) -> Any:
            client = original(c)
            client._transport = httpx.MockTransport(handler)
            return client

        adapter._client = _client_with_transport  # type: ignore[method-assign]

        comment = await adapter.fetch_inbound_comment(ctx, "2", "901")

        assert comment == ZendeskInboundComment(
            ticket_id="2",
            comment_id="901",
            author_id="7",
            public=True,
            content='dijo "hola"\ny',
            requester_id="7",
            requester_email="cliente@test.com",
            requester_name="Cliente",
            subject="Pedido",
            via_channel="email",
        )
        assert comment.from_requester is True
        assert requests == ["/api/v2/tickets/2.json", "/api/v2/tickets/2/comments.json"]


def test_payload_with_only_ids_is_valid_json() -> None:
    """El body documentado para el Trigger no lleva texto libre."""
    body = {
        "ticket_id": "2",
        "comment_id": "901",
        "subdomain": "auyan",
    }
    assert _parse_payload(json.dumps(body).encode()) == body
