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
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.core.errors import ConflictError, NotFoundError, register_exception_handlers
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
    return UserRecord(tenant_id=TENANT_ID, role="tenant_agent", email="agent@acme.io")


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
        convs = [make_conversation(), make_conversation(id=UUID("aaaaaaaa-0000-0000-0000-000000000000"))]

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
        msgs = [make_message(), make_message(id=OUTBOUND_MSG_ID, role="agent_human", direction="outbound")]

        async def _fake_detail(conn: Any, tenant_id: UUID, conversation_id: UUID, **kwargs: Any) -> Any:
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

    def test_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_detail(conn: Any, tenant_id: UUID, conversation_id: UUID, **kwargs: Any) -> Any:
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


class TestReply:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        msg = make_message(id=OUTBOUND_MSG_ID, role="agent_human", direction="outbound", content="hola agente")

        async def _fake_reply(conn: Any, tenant_id: UUID, conversation_id: UUID, author_user_id: UUID, content: str) -> Any:
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
        async def _fake_reply(conn: Any, tenant_id: UUID, conversation_id: UUID, author_user_id: UUID, content: str) -> Any:
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

        async def _fake_escalate(conn: Any, tenant_id: UUID, conversation_id: UUID, reason: str) -> Any:
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
        async def _fake_escalate(conn: Any, tenant_id: UUID, conversation_id: UUID, reason: str) -> Any:
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

        monkeypatch.setattr("apps.api.routers.conversations.close_conversation", _fake_close)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/conversations/{CONVERSATION_ID}/close",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 204

    def test_already_closed_returns_409(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_close(conn: Any, tenant_id: UUID, conversation_id: UUID) -> None:
            raise ConflictError("already closed", code="already_closed")

        monkeypatch.setattr("apps.api.routers.conversations.close_conversation", _fake_close)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/conversations/{CONVERSATION_ID}/close",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"] == "already_closed"
