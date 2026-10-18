"""Tests para routers/conversations.py + services/conversations.py."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import jwt
import pytest
from apps.api.core.errors import (
    ConflictError,
    ExternalIntegrationError,
    NotFoundError,
    register_exception_handlers,
)
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.routers.conversations import router as conversations_router
from apps.api.tests.conftest import (
    CONVERSATION_ID,
    ESCALATION_ID,
    OUTBOUND_MSG_ID,
    TENANT_ID,
    make_conversation,
    make_escalation,
    make_message,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret-for-unit-tests-32b!"
JWT_ALG = "HS256"
JWT_AUD = "authenticated"
USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


class _SecretWrap:
    def get_secret_value(self) -> str:
        return JWT_SECRET


@dataclass
class FakeAuthSettings:
    auth_user_cache_maxsize: int = 1000
    auth_user_cache_ttl_seconds: int = 60
    supabase_jwt_algorithm: str = JWT_ALG
    supabase_jwt_audience: str = JWT_AUD

    @property
    def supabase_jwt_secret(self) -> _SecretWrap:
        return _SecretWrap()


def _make_jwt() -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"aud": JWT_AUD, "sub": str(USER_ID), "exp": now + timedelta(hours=1), "iat": now},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


def _agent_record() -> UserRecord:
    return UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="agent@acme.io")


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_user_cache()
    yield  # type: ignore[misc]
    reset_user_cache()


def _make_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord:
        return _agent_record()

    monkeypatch.setattr("apps.api.core.security._lookup_user", _fake_lookup)

    @asynccontextmanager
    async def _fake_tenant_scope(tid: UUID) -> AsyncIterator[Any]:
        yield AsyncMock()

    monkeypatch.setattr("apps.api.routers.conversations.tenant_scope", _fake_tenant_scope)

    from apps.api.core.config import get_settings

    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(conversations_router)
    return app


AUTH_HDR = {"Authorization": f"Bearer {_make_jwt()}"}


class TestListConversations:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        convs = [
            make_conversation(),
            make_conversation(id=UUID("aaaaaaaa-0000-0000-0000-000000000000")),
        ]

        async def _fake_list(conn: Any, tenant_id: UUID, **kwargs: Any) -> Any:
            return convs

        monkeypatch.setattr("apps.api.routers.conversations.list_tenant_conversations", _fake_list)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get("/conversations", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["conversations"]) == 2
        assert body["limit"] == 50
        assert body["offset"] == 0

    def test_filters_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        received: dict = {}

        async def _fake_list(conn: Any, tenant_id: UUID, **kwargs: Any) -> list:
            received.update(kwargs)
            return []

        monkeypatch.setattr("apps.api.routers.conversations.list_tenant_conversations", _fake_list)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        client.get(
            "/conversations?status=open&limit=10&offset=5",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert received["status"] == "open"
        assert received["limit"] == 10
        assert received["offset"] == 5

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get("/conversations")
        assert resp.status_code == 401


class TestGetConversation:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conv = make_conversation()
        msgs = [
            make_message(),
            make_message(id=OUTBOUND_MSG_ID, role="agent_human", direction="outbound"),
        ]

        async def _fake_detail(
            conn: Any, tenant_id: UUID, conversation_id: UUID, **kwargs: Any
        ) -> Any:
            return conv, msgs

        monkeypatch.setattr("apps.api.routers.conversations.get_conversation_detail", _fake_detail)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get(
            f"/conversations/{CONVERSATION_ID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["conversation"]["id"] == str(CONVERSATION_ID)
        assert len(body["messages"]) == 2

    def test_whatsapp_detail_has_handoff_author_and_attachments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.api.db.models import ConversationHandoff

        conv = make_conversation(channel="whatsapp", external_id="zconv-1")
        msgs = [
            make_message(
                attachments=[
                    {
                        "path": "t/c/m/0.jpg",
                        "filename": "0.jpg",
                        "kind": "image",
                        "mime_type": "image/jpeg",
                    }
                ],
                metadata={"zernio_attachments": [{"url": "https://secret"}]},
            ),
            make_message(
                id=OUTBOUND_MSG_ID,
                role="agent_human",
                direction="outbound",
                metadata={
                    "external_author": {"provider": "zendesk", "id": "42", "name": "Laura"},
                    "delivery": "pending_window",
                },
            ),
        ]
        handoff = ConversationHandoff(
            id=UUID(int=3),
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            target="helpdesk",
            helpdesk_provider="zendesk",
            external_ticket_id="555",
            status="active",
            reason="persona",
            opened_at=datetime.now(UTC),
        )

        async def _fake_detail(
            conn: Any, tenant_id: UUID, conversation_id: UUID, **kwargs: Any
        ) -> Any:
            return conv, msgs

        monkeypatch.setattr("apps.api.routers.conversations.get_conversation_detail", _fake_detail)
        monkeypatch.setattr(
            "apps.api.routers.conversations.get_active_handoff_for_chat",
            AsyncMock(return_value=handoff),
        )
        app = _make_app(monkeypatch)
        resp = TestClient(app).get(
            f"/conversations/{CONVERSATION_ID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        body = resp.json()
        assert body["active_handoff"]["external_ticket_id"] == "555"
        assert body["messages"][0]["attachments"] == [
            {"filename": "0.jpg", "kind": "image", "mime_type": "image/jpeg"}
        ]
        assert "secret" not in resp.text  # la URL de Zernio no sale
        assert body["messages"][1]["external_author"] == {"provider": "zendesk", "name": "Laura"}
        assert body["messages"][1]["delivery"] == "pending_window"

    def test_helpdesk_detail_does_not_query_handoffs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conv = make_conversation(channel="zendesk", external_id="42")

        async def _fake_detail(
            conn: Any, tenant_id: UUID, conversation_id: UUID, **kwargs: Any
        ) -> Any:
            return conv, [make_message()]

        lookup = AsyncMock()
        monkeypatch.setattr("apps.api.routers.conversations.get_conversation_detail", _fake_detail)
        monkeypatch.setattr("apps.api.routers.conversations.get_active_handoff_for_chat", lookup)
        app = _make_app(monkeypatch)
        resp = TestClient(app).get(
            f"/conversations/{CONVERSATION_ID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.json()["active_handoff"] is None
        lookup.assert_not_awaited()

    def test_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_detail(
            conn: Any, tenant_id: UUID, conversation_id: UUID, **kwargs: Any
        ) -> Any:
            raise NotFoundError("not found", code="conversation_not_found")

        monkeypatch.setattr("apps.api.routers.conversations.get_conversation_detail", _fake_detail)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get(
            f"/conversations/{CONVERSATION_ID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"] == "conversation_not_found"


class TestAttachmentUrl:
    """Vista previa de adjuntos: URL firmada de vida corta, nunca de otro tenant."""

    PATH = f"{TENANT_ID}/{CONVERSATION_ID}/m/0.jpg"

    def _get(
        self, monkeypatch: pytest.MonkeyPatch, message: Any, index: int = 0
    ) -> tuple[Any, AsyncMock]:
        monkeypatch.setattr(
            "apps.api.routers.conversations.get_conversation_message",
            AsyncMock(return_value=message),
        )
        signer = AsyncMock(return_value="https://sb.example/storage/v1/object/sign/x?token=t")
        monkeypatch.setattr("apps.api.routers.conversations.create_signed_url", signer)
        app = _make_app(monkeypatch)
        resp = TestClient(app).get(
            f"/conversations/{CONVERSATION_ID}/messages/{OUTBOUND_MSG_ID}/attachments/{index}",
            headers=AUTH_HDR,
        )
        return resp, signer

    def _message(self, path: str) -> Any:
        return make_message(
            id=OUTBOUND_MSG_ID,
            attachments=[
                {"path": path, "filename": "0.jpg", "kind": "image", "mime_type": "image/jpeg"}
            ],
        )

    def test_returns_short_lived_signed_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp, signer = self._get(monkeypatch, self._message(self.PATH))
        assert resp.status_code == 200
        body = resp.json()
        assert body["url"].endswith("?token=t")
        assert body["kind"] == "image" and body["mime_type"] == "image/jpeg"
        assert body["expires_in"] == 300
        signer.assert_awaited_once_with(self.PATH)

    def test_index_out_of_range_is_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp, signer = self._get(monkeypatch, self._message(self.PATH), index=1)
        assert resp.status_code == 404
        signer.assert_not_awaited()

    def test_message_from_another_conversation_is_404(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resp, signer = self._get(monkeypatch, None)
        assert resp.status_code == 404
        signer.assert_not_awaited()

    def test_never_signs_a_path_outside_the_tenant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Defensa en profundidad: aunque el mensaje apuntara a otro tenant, no se firma."""
        other = f"99999999-9999-9999-9999-999999999999/{CONVERSATION_ID}/m/0.jpg"
        resp, signer = self._get(monkeypatch, self._message(other))
        assert resp.status_code == 404
        signer.assert_not_awaited()

    def test_negative_index_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp, signer = self._get(monkeypatch, self._message(self.PATH), index=-1)
        assert resp.status_code == 422
        signer.assert_not_awaited()


class TestReply:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        msg = make_message(
            id=OUTBOUND_MSG_ID, role="agent_human", direction="outbound", content="hola agente"
        )

        async def _fake_reply(
            conn: Any, tenant_id: UUID, conversation_id: UUID, author_user_id: UUID, content: str
        ) -> Any:
            return msg

        monkeypatch.setattr("apps.api.routers.conversations.reply_to_conversation", _fake_reply)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/conversations/{CONVERSATION_ID}/reply",
            json={"content": "hola agente"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "agent_human"

    def test_conversation_closed_returns_409(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_reply(
            conn: Any, tenant_id: UUID, conversation_id: UUID, author_user_id: UUID, content: str
        ) -> Any:
            raise ConflictError("closed", code="conversation_closed")

        monkeypatch.setattr("apps.api.routers.conversations.reply_to_conversation", _fake_reply)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/conversations/{CONVERSATION_ID}/reply",
            json={"content": "x"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"] == "conversation_closed"

    def test_empty_content_returns_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/conversations/{CONVERSATION_ID}/reply",
            json={"content": ""},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 422


class TestEscalate:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        escalation = make_escalation()

        async def _fake_escalate(
            conn: Any, tenant_id: UUID, conversation_id: UUID, reason: str
        ) -> Any:
            return escalation

        monkeypatch.setattr("apps.api.routers.conversations.escalate_conversation", _fake_escalate)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/conversations/{CONVERSATION_ID}/escalate",
            json={"reason": "cliente muy molesto"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 201
        assert resp.json()["id"] == str(ESCALATION_ID)

    def test_already_escalated_returns_409(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_escalate(
            conn: Any, tenant_id: UUID, conversation_id: UUID, reason: str
        ) -> Any:
            raise ConflictError("already escalated", code="already_escalated")

        monkeypatch.setattr("apps.api.routers.conversations.escalate_conversation", _fake_escalate)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/conversations/{CONVERSATION_ID}/escalate",
            json={"reason": "x"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"] == "already_escalated"


class TestClose:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_close(conn: Any, tenant_id: UUID, conversation_id: UUID) -> None:
            return None

        external_close = AsyncMock(return_value=False)
        monkeypatch.setattr(
            "apps.api.routers.conversations.get_closable_conversation",
            AsyncMock(return_value=make_conversation()),
        )
        monkeypatch.setattr(
            "apps.api.routers.conversations.close_external_helpdesk_ticket",
            external_close,
        )
        monkeypatch.setattr("apps.api.routers.conversations.close_conversation", _fake_close)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/conversations/{CONVERSATION_ID}/close",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 204
        external_close.assert_awaited_once()

    def test_already_closed_returns_409(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_get_closable(conn: Any, tenant_id: UUID, conversation_id: UUID) -> None:
            raise ConflictError("already closed", code="already_closed")

        monkeypatch.setattr(
            "apps.api.routers.conversations.get_closable_conversation",
            _fake_get_closable,
        )
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/conversations/{CONVERSATION_ID}/close",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"] == "already_closed"

    def test_external_failure_returns_502_before_internal_close(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        close_internal = AsyncMock()
        monkeypatch.setattr(
            "apps.api.routers.conversations.get_closable_conversation",
            AsyncMock(
                return_value=make_conversation(
                    channel="zendesk",
                    external_id="123",
                )
            ),
        )
        monkeypatch.setattr(
            "apps.api.routers.conversations.close_external_helpdesk_ticket",
            AsyncMock(
                side_effect=ExternalIntegrationError(
                    "zendesk failed",
                    code="external_helpdesk_close_failed",
                )
            ),
        )
        monkeypatch.setattr(
            "apps.api.routers.conversations.close_conversation",
            close_internal,
        )
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/conversations/{CONVERSATION_ID}/close",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 502
        assert resp.json()["error"] == "external_helpdesk_close_failed"
        close_internal.assert_not_awaited()


# ============================================================
# reopen_if_resolved — reactivar al volver a escribir el cliente
# ============================================================


@pytest.mark.asyncio
async def test_reopen_if_resolved_reopens_resolved_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.services import conversations as conv_service

    conv = make_conversation(status="resolved")
    reopened = AsyncMock(return_value=True)
    monkeypatch.setattr(conv_service, "reopen_conversation", reopened)
    reverted = AsyncMock(return_value=True)
    monkeypatch.setattr(conv_service, "mark_resolution_event_reverted", reverted)

    result = await conv_service.reopen_if_resolved(AsyncMock(), TENANT_ID, conv)

    assert result.status == "open"
    assert result.resolved_at is None
    reopened.assert_awaited_once()
    # Billing: la reapertura del mismo thread anota la reversión en el evento.
    reverted.assert_awaited_once()


@pytest.mark.asyncio
async def test_reopen_if_resolved_noop_when_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.services import conversations as conv_service

    conv = make_conversation(status="open")
    reopened = AsyncMock()
    monkeypatch.setattr(conv_service, "reopen_conversation", reopened)

    result = await conv_service.reopen_if_resolved(AsyncMock(), TENANT_ID, conv)

    assert result.status == "open"
    reopened.assert_not_awaited()
