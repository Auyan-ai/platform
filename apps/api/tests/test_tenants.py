"""Tests para routers/tenants.py + services/tenants.py."""

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
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import (
    UserRecord,
    reset_user_cache,
)
from apps.api.routers.tenants import router as tenants_router
from apps.api.tests.conftest import (
    TENANT_ID,
    make_tenant,
    make_tenant_configuration,
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

    monkeypatch.setattr("apps.api.routers.tenants.tenant_scope", _fake_tenant_scope)

    from apps.api.core.config import get_settings
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(tenants_router)
    return app


class TestGetMyTenant:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tenant = make_tenant()

        async def _fake_get_tenant(conn: Any, tenant_id: UUID) -> Any:
            return tenant

        monkeypatch.setattr("apps.api.routers.tenants.get_tenant", _fake_get_tenant)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get("/tenants/me", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(TENANT_ID)
        assert body["slug"] == "acme"
        assert body["status"] == "active"

    def test_tenant_not_found_raises_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.core.errors import NotFoundError

        async def _fake_get_tenant(conn: Any, tenant_id: UUID) -> None:
            raise NotFoundError("tenant not found", code="tenant_not_found")

        monkeypatch.setattr("apps.api.routers.tenants.get_tenant", _fake_get_tenant)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get("/tenants/me", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 404
        assert resp.json()["error"] == "tenant_not_found"

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get("/tenants/me")
        assert resp.status_code == 401


class TestGetMyTenantConfig:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = make_tenant_configuration()

        async def _fake_get_config(conn: Any, tenant_id: UUID) -> Any:
            return config

        monkeypatch.setattr("apps.api.routers.tenants.get_tenant_config", _fake_get_config)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get("/tenants/me/config", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent_model"] == "claude-sonnet-4-6"
        assert body["escalation_threshold"] == 0.70

    def test_config_not_found_raises_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.core.errors import NotFoundError

        async def _fake_get_config(conn: Any, tenant_id: UUID) -> None:
            raise NotFoundError("no config", code="tenant_config_not_found")

        monkeypatch.setattr("apps.api.routers.tenants.get_tenant_config", _fake_get_config)
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get("/tenants/me/config", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 404
        assert resp.json()["error"] == "tenant_config_not_found"
