"""Tests para routers/users.py — GET /users/me."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
import pytest
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.routers.users import router as users_router
from apps.api.tests.conftest import TENANT_ID
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


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_user_cache()
    yield  # type: ignore[misc]
    reset_user_cache()


def _make_app(monkeypatch: pytest.MonkeyPatch, record: UserRecord) -> FastAPI:
    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord:
        return record

    monkeypatch.setattr("apps.api.core.security._lookup_user", _fake_lookup)

    from apps.api.core.config import get_settings

    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(users_router)
    return app


class TestGetCurrentUser:
    def test_tenant_admin_returns_role_and_tenant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        record = UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="admin@lunaria.io")
        app = _make_app(monkeypatch, record)
        client = TestClient(app)
        resp = client.get("/users/me", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == str(USER_ID)
        assert body["tenant_id"] == str(TENANT_ID)
        assert body["role"] == "tenant_admin"
        assert body["email"] == "admin@lunaria.io"

    def test_super_admin_has_null_tenant_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        record = UserRecord(tenant_id=None, role="super_admin", email="root@auyan.io")
        app = _make_app(monkeypatch, record)
        client = TestClient(app)
        resp = client.get("/users/me", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "super_admin"
        assert body["tenant_id"] is None

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        record = UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="agent@lunaria.io")
        app = _make_app(monkeypatch, record)
        client = TestClient(app)
        resp = client.get("/users/me")
        assert resp.status_code == 401
        assert resp.json()["error"] == "missing_bearer_token"
