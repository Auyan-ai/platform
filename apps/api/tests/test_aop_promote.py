"""Tests para PATCH /aops/{id}/promote (Sprint 7.6)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import jwt
import pytest
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.evals.harness import EvalRunResult
from apps.api.routers.aops import router as aops_router
from apps.api.tests.conftest import TENANT_ID, make_tenant_configuration
from fastapi import FastAPI
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret-for-unit-tests-32b!"
JWT_ALG = "HS256"
JWT_AUD = "authenticated"
USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
AOP_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PROD_AOP_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


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


def _admin_record() -> UserRecord:
    return UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="admin@acme.io")


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_user_cache()
    yield  # type: ignore[misc]
    reset_user_cache()


def _make_aop_with_content(
    aop_id: UUID = AOP_ID,
    slug: str = "consulta_envio",
    workspace: str = "staging",
) -> MagicMock:
    """Mock de AopWithContent para tests del router."""
    aop = MagicMock()
    aop.id = aop_id
    aop.tenant_id = TENANT_ID
    aop.slug = slug
    aop.workspace = workspace
    aop.current_version = 1
    aop.is_active = True
    aop.yaml_frontmatter = {"slug": slug, "name": "Test AOP", "allowed_skills": []}
    aop.body_markdown = "## Procedimiento\n\nTest."
    aop.raw_source = ""
    return aop


def _make_eval_result(
    *,
    meets_gate: bool,
    pass_rate: float = 1.0,
    passed: int = 8,
    total: int = 8,
    slug: str = "consulta_envio",
) -> EvalRunResult:
    return EvalRunResult(
        aop_slug=slug,
        aop_version=1,
        total_fixtures=total,
        passed_fixtures=passed,
        pass_rate=pass_rate,
        meets_gate=meets_gate,
        fixture_results=[],
    )


def _make_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord:
        return _admin_record()

    monkeypatch.setattr("apps.api.core.security._lookup_user", _fake_lookup)

    @asynccontextmanager
    async def _fake_tenant_scope(tid: UUID) -> AsyncIterator[Any]:
        yield AsyncMock()

    monkeypatch.setattr("apps.api.routers.aops.tenant_scope", _fake_tenant_scope)

    from apps.api.core.config import get_settings
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(aops_router)
    return app


AUTH_HDR = {"Authorization": f"Bearer {_make_jwt()}"}


class TestPromoteAop:
    def test_promote_passes_gate_new_production_aop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AOP pasa el eval → se crea en production, retorna 200."""
        staging_aop = _make_aop_with_content()
        prod_aop = _make_aop_with_content(aop_id=PROD_AOP_ID, workspace="production")

        tenant_config_row = make_tenant_configuration()

        monkeypatch.setattr("apps.api.routers.aops.get_aop_by_id", AsyncMock(return_value=staging_aop))
        monkeypatch.setattr("apps.api.routers.aops.get_tenant_configuration", AsyncMock(return_value=tenant_config_row))
        monkeypatch.setattr("apps.api.routers.aops.run_eval", lambda aop, tc: _make_eval_result(meets_gate=True))
        monkeypatch.setattr("apps.api.routers.aops.get_aop_by_slug", AsyncMock(return_value=None))
        monkeypatch.setattr("apps.api.routers.aops.create_aop", AsyncMock(return_value=prod_aop))

        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.patch(f"/aops/{AOP_ID}/promote", headers=AUTH_HDR)

        assert resp.status_code == 200
        body = resp.json()
        assert body["promoted_to_production"] is True
        assert body["meets_gate"] is True
        assert body["production_aop_id"] == str(PROD_AOP_ID)
        assert body["eval_pass_rate"] == 1.0

    def test_promote_passes_gate_existing_production_aop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ya existe un AOP en production → se guarda nueva versión."""
        staging_aop = _make_aop_with_content()
        existing_prod = _make_aop_with_content(aop_id=PROD_AOP_ID, workspace="production")
        updated_prod = _make_aop_with_content(aop_id=PROD_AOP_ID, workspace="production")
        updated_prod.current_version = 2

        tenant_config_row = make_tenant_configuration()

        get_aop_by_id_mock = AsyncMock(side_effect=[staging_aop, updated_prod])
        monkeypatch.setattr("apps.api.routers.aops.get_aop_by_id", get_aop_by_id_mock)
        monkeypatch.setattr("apps.api.routers.aops.get_tenant_configuration", AsyncMock(return_value=tenant_config_row))
        monkeypatch.setattr("apps.api.routers.aops.run_eval", lambda aop, tc: _make_eval_result(meets_gate=True))
        monkeypatch.setattr("apps.api.routers.aops.get_aop_by_slug", AsyncMock(return_value=existing_prod))
        monkeypatch.setattr("apps.api.routers.aops.save_aop_version", AsyncMock())

        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.patch(f"/aops/{AOP_ID}/promote", headers=AUTH_HDR)

        assert resp.status_code == 200
        body = resp.json()
        assert body["promoted_to_production"] is True
        assert body["production_aop_id"] == str(PROD_AOP_ID)

    def test_promote_fails_gate_returns_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """pass_rate < 80% → 422 con detalles del eval."""
        staging_aop = _make_aop_with_content()

        tenant_config_row = make_tenant_configuration()

        monkeypatch.setattr("apps.api.routers.aops.get_aop_by_id", AsyncMock(return_value=staging_aop))
        monkeypatch.setattr("apps.api.routers.aops.get_tenant_configuration", AsyncMock(return_value=tenant_config_row))
        monkeypatch.setattr(
            "apps.api.routers.aops.run_eval",
            lambda aop, tc: _make_eval_result(meets_gate=False, pass_rate=0.5, passed=4, total=8),
        )

        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.patch(f"/aops/{AOP_ID}/promote", headers=AUTH_HDR)

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "eval_gate_failed"
        assert detail["pass_rate"] == 0.5
        assert "50%" in detail["reason"]

    def test_promote_no_fixtures_returns_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sin fixtures para el slug → 422 con razón no_fixtures_found."""
        staging_aop = _make_aop_with_content(slug="slug_sin_fixtures_xyz")

        tenant_config_row = make_tenant_configuration()

        monkeypatch.setattr("apps.api.routers.aops.get_aop_by_id", AsyncMock(return_value=staging_aop))
        monkeypatch.setattr("apps.api.routers.aops.get_tenant_configuration", AsyncMock(return_value=tenant_config_row))
        monkeypatch.setattr(
            "apps.api.routers.aops.run_eval",
            lambda aop, tc: _make_eval_result(meets_gate=False, pass_rate=0.0, passed=0, total=0),
        )

        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.patch(f"/aops/{AOP_ID}/promote", headers=AUTH_HDR)

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["reason"] == "no_fixtures_found"

    def test_promote_aop_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("apps.api.routers.aops.get_aop_by_id", AsyncMock(return_value=None))

        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.patch(f"/aops/{AOP_ID}/promote", headers=AUTH_HDR)

        assert resp.status_code == 404

    def test_promote_requires_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """tenant_agent no tiene acceso → 403."""
        async def _agent_lookup(user_id: UUID, settings: Any) -> UserRecord:
            return UserRecord(tenant_id=TENANT_ID, role="tenant_agent", email="agent@acme.io")

        monkeypatch.setattr("apps.api.core.security._lookup_user", _agent_lookup)

        @asynccontextmanager
        async def _fake_tenant_scope(tid: UUID) -> AsyncIterator[Any]:
            yield AsyncMock()

        monkeypatch.setattr("apps.api.routers.aops.tenant_scope", _fake_tenant_scope)

        from apps.api.core.config import get_settings
        app = FastAPI()
        register_exception_handlers(app)
        app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
        app.include_router(aops_router)

        client = TestClient(app)
        resp = client.patch(f"/aops/{AOP_ID}/promote", headers=AUTH_HDR)
        assert resp.status_code == 403
