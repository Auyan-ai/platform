"""Tests para GET /tenants/me/metrics."""

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
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.routers.tenants import router as tenants_router
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


def _make_app(
    monkeypatch: pytest.MonkeyPatch,
    role: str = "tenant_admin",
) -> FastAPI:
    record = UserRecord(tenant_id=TENANT_ID, role=role, email="admin@lunaria.io")  # type: ignore[arg-type]

    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord:
        return record

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


_SAMPLE_METRICS = {
    "total": 100,
    "by_status": {"open": 20, "pending": 10, "escalated": 5, "resolved": 50, "closed": 15},
    "resolution_rate": 0.65,
    "escalation_rate": 0.05,
}


class TestGetMyTenantMetrics:
    def test_tenant_admin_gets_metrics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_get_metrics(conn: Any, tenant_id: UUID) -> Any:
            return _SAMPLE_METRICS

        monkeypatch.setattr("apps.api.routers.tenants.get_tenant_metrics", _fake_get_metrics)
        app = _make_app(monkeypatch, role="tenant_admin")
        client = TestClient(app)
        resp = client.get(
            "/tenants/me/metrics",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 100
        assert body["by_status"]["open"] == 20
        assert body["by_status"]["escalated"] == 5
        assert body["resolution_rate"] == 0.65
        assert body["escalation_rate"] == 0.05

    def test_tenant_agent_gets_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch, role="tenant_agent")
        client = TestClient(app)
        resp = client.get(
            "/tenants/me/metrics",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"] == "insufficient_role"

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get("/tenants/me/metrics")
        assert resp.status_code == 401

    def test_get_tenant_metrics_service_calculates_rates(self) -> None:
        """get_tenant_metrics en services calcula rates correctamente."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        counts = {
            "total": 10,
            "open_count": 2,
            "pending_count": 1,
            "escalated_count": 1,
            "resolved_count": 4,
            "closed_count": 2,
        }

        async def _run() -> None:
            with patch(
                "apps.api.services.tenants._get_tenant_metrics",
                new=AsyncMock(return_value=counts),
            ):
                from apps.api.services.tenants import get_tenant_metrics

                result = await get_tenant_metrics(AsyncMock(), TENANT_ID)

            assert result["total"] == 10
            assert result["by_status"]["escalated"] == 1  # type: ignore[index]
            # resolved + closed = 4+2=6 → 6/10 = 0.6
            assert result["resolution_rate"] == 0.6
            # escalated = 1 → 1/10 = 0.1
            assert result["escalation_rate"] == 0.1

        asyncio.run(_run())
