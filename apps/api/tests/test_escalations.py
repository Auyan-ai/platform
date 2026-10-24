"""Tests para routers/escalations.py + services/escalations.py."""

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
from apps.api.core.errors import ConflictError, NotFoundError, register_exception_handlers
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.routers.escalations import router as escalations_router
from apps.api.tests.conftest import (
    ESCALATION_ID,
    TENANT_ID,
    make_escalation,
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

    monkeypatch.setattr("apps.api.routers.escalations.tenant_scope", _fake_tenant_scope)

    from apps.api.core.config import get_settings

    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(escalations_router)
    return app


class TestListEscalations:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        escalations = [
            make_escalation(),
            make_escalation(id=UUID("eeeeeeee-0000-0000-0000-000000000000")),
        ]

        async def _fake_list(conn: Any, tenant_id: UUID, **kwargs: Any) -> Any:
            return escalations

        monkeypatch.setattr("apps.api.routers.escalations.list_tenant_escalations", _fake_list)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get("/escalations", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["escalations"]) == 2
        assert body["limit"] == 50

    def test_status_filter_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        received: dict = {}

        async def _fake_list(conn: Any, tenant_id: UUID, **kwargs: Any) -> list:
            received.update(kwargs)
            return []

        monkeypatch.setattr("apps.api.routers.escalations.list_tenant_escalations", _fake_list)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        client.get(
            "/escalations?status=pending&limit=20",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert received["status"] == "pending"
        assert received["limit"] == 20

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get("/escalations")
        assert resp.status_code == 401


class TestClaimEscalation:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        claimed = make_escalation(status="claimed", assigned_user_id=USER_ID)

        async def _fake_claim(
            conn: Any, tenant_id: UUID, escalation_id: UUID, agent_user_id: UUID
        ) -> Any:
            return claimed

        monkeypatch.setattr("apps.api.routers.escalations.claim_tenant_escalation", _fake_claim)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/escalations/{ESCALATION_ID}/claim",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "claimed"
        assert body["assigned_user_id"] == str(USER_ID)

    def test_not_pending_returns_409(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_claim(
            conn: Any, tenant_id: UUID, escalation_id: UUID, agent_user_id: UUID
        ) -> Any:
            raise ConflictError("not pending", code="escalation_not_pending")

        monkeypatch.setattr("apps.api.routers.escalations.claim_tenant_escalation", _fake_claim)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/escalations/{ESCALATION_ID}/claim",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"] == "escalation_not_pending"

    def test_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_claim(
            conn: Any, tenant_id: UUID, escalation_id: UUID, agent_user_id: UUID
        ) -> Any:
            raise NotFoundError("not found", code="escalation_not_found")

        monkeypatch.setattr("apps.api.routers.escalations.claim_tenant_escalation", _fake_claim)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/escalations/{ESCALATION_ID}/claim",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 404


class TestResolveEscalation:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resolved = make_escalation(status="resolved", assigned_user_id=USER_ID)

        async def _fake_resolve(conn: Any, tenant_id: UUID, escalation_id: UUID) -> Any:
            return resolved

        monkeypatch.setattr("apps.api.routers.escalations.resolve_tenant_escalation", _fake_resolve)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/escalations/{ESCALATION_ID}/resolve",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"

    def test_not_claimed_returns_409(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_resolve(conn: Any, tenant_id: UUID, escalation_id: UUID) -> Any:
            raise ConflictError("not claimed", code="escalation_not_claimed")

        monkeypatch.setattr("apps.api.routers.escalations.resolve_tenant_escalation", _fake_resolve)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.post(
            f"/escalations/{ESCALATION_ID}/resolve",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"] == "escalation_not_claimed"
