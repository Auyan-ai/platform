"""Tests para routers/tenants.py + services/tenants.py."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
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
    budget_usd_daily: float = 10.0

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

    monkeypatch.setattr("apps.api.routers.tenants.tenant_scope", _fake_tenant_scope)

    from apps.api.core.config import get_settings
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(tenants_router)
    return app


def _make_super_admin_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord:
        return UserRecord(tenant_id=TENANT_ID, role="super_admin", email="kenny@auyan.ai")

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


# ----------------------------------------------------------------
# GET /tenants/me/usage
# ----------------------------------------------------------------


def _make_app_with_bootstrap(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """App con tenant_scope Y bootstrap_connection mockeados (para endpoints que usan ambos)."""
    from contextlib import asynccontextmanager

    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord:
        return UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="admin@acme.io")

    monkeypatch.setattr("apps.api.core.security._lookup_user", _fake_lookup)

    @asynccontextmanager
    async def _fake_tenant_scope(tid: UUID) -> AsyncIterator[Any]:
        yield AsyncMock()

    @asynccontextmanager
    async def _fake_bootstrap() -> AsyncIterator[Any]:
        yield AsyncMock()

    monkeypatch.setattr("apps.api.routers.tenants.tenant_scope", _fake_tenant_scope)
    monkeypatch.setattr("apps.api.routers.tenants.bootstrap_connection", _fake_bootstrap)

    from apps.api.core.config import get_settings
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(tenants_router)
    return app


def _make_usage_row(date: str = "2026-05-19", cost: float = 2.5) -> Any:
    from apps.api.db.models import TenantUsageDaily
    return TenantUsageDaily(
        id=UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
        tenant_id=TENANT_ID,
        date=date,
        tokens_in=1000,
        tokens_out=500,
        cost_usd=cost,
        request_count=10,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestGetMyTenantUsage:
    def test_happy_path_with_activity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app_with_bootstrap(monkeypatch)
        import datetime as dt
        today = dt.date.today().isoformat()
        row = _make_usage_row(date=today, cost=2.5)
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_tenant_configuration",
            AsyncMock(return_value=make_tenant_configuration()),
        )
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_tenant_usage_range",
            AsyncMock(return_value=[row]),
        )
        token = _make_jwt()
        with TestClient(app) as client:
            resp = client.get(
                "/tenants/me/usage",
                headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": str(TENANT_ID)},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["today"] is not None
        assert data["today"]["cost_usd"] == 2.5
        assert data["budget_usd_daily"] == 10.0
        assert data["budget_used_pct"] == 25.0
        assert data["days"] == 7
        assert len(data["history"]) == 1

    def test_no_activity_returns_null_today(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app_with_bootstrap(monkeypatch)
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_tenant_configuration",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_tenant_usage_range",
            AsyncMock(return_value=[]),
        )
        token = _make_jwt()
        with TestClient(app) as client:
            resp = client.get(
                "/tenants/me/usage",
                headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": str(TENANT_ID)},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["today"] is None
        assert data["budget_used_pct"] == 0.0
        assert data["history"] == []

    def test_custom_days_param(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app_with_bootstrap(monkeypatch)
        mock_range = AsyncMock(return_value=[])
        monkeypatch.setattr("apps.api.routers.tenants.get_tenant_configuration", AsyncMock(return_value=None))
        monkeypatch.setattr("apps.api.routers.tenants.get_tenant_usage_range", mock_range)
        token = _make_jwt()
        with TestClient(app) as client:
            client.get(
                "/tenants/me/usage?days=30",
                headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": str(TENANT_ID)},
            )
        _, kwargs = mock_range.call_args
        assert kwargs["days"] == 30

    def test_tenant_budget_override_reflected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app_with_bootstrap(monkeypatch)
        import datetime as dt
        today = dt.date.today().isoformat()
        row = _make_usage_row(date=today, cost=3.0)
        # Override budget a $5/día
        cfg = make_tenant_configuration(extra={"budget_usd_daily": 5.0})
        monkeypatch.setattr("apps.api.routers.tenants.get_tenant_configuration", AsyncMock(return_value=cfg))
        monkeypatch.setattr("apps.api.routers.tenants.get_tenant_usage_range", AsyncMock(return_value=[row]))
        token = _make_jwt()
        with TestClient(app) as client:
            resp = client.get(
                "/tenants/me/usage",
                headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": str(TENANT_ID)},
            )
        data = resp.json()
        assert data["budget_usd_daily"] == 5.0
        assert data["budget_used_pct"] == 60.0  # 3.0 / 5.0 * 100

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app_with_bootstrap(monkeypatch)
        with TestClient(app) as client:
            resp = client.get("/tenants/me/usage")
        assert resp.status_code == 401


class TestTenantPlaybookEndpoints:
    def test_get_playbook_returns_existing_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.db.models import TenantPlaybook

        playbook = TenantPlaybook(
            tenant_id=TENANT_ID,
            brand_voice="Cercana, clara, sin prometer de más.",
            product_overview="Ecommerce de cosmética.",
            policies="Devoluciones en 30 días.",
            escalation_notes="Escalar VIPs.",
            agent_instructions="Usar castellano de España.",
            version=3,
            last_edited_by=USER_ID,
            updated_at=datetime.now(UTC),
        )
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_tenant_playbook",
            AsyncMock(return_value=playbook),
        )
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.get("/tenants/me/playbook", headers={"Authorization": f"Bearer {_make_jwt()}"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == str(TENANT_ID)
        assert body["brand_voice"] == "Cercana, clara, sin prometer de más."
        assert body["version"] == 3

    def test_get_playbook_returns_empty_default_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_tenant_playbook",
            AsyncMock(return_value=None),
        )
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.get("/tenants/me/playbook", headers={"Authorization": f"Bearer {_make_jwt()}"})

        assert resp.status_code == 200
        assert resp.json()["brand_voice"] == ""

    def test_update_playbook_upserts_all_sections(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.db.models import TenantPlaybook

        saved = TenantPlaybook(
            tenant_id=TENANT_ID,
            brand_voice="Precisa",
            product_overview="Moda premium",
            policies="Cambios 14 días",
            escalation_notes="Escalar fraude",
            agent_instructions="No inventar stock",
            version=2,
            last_edited_by=USER_ID,
            updated_at=datetime.now(UTC),
        )
        upsert_mock = AsyncMock(return_value=saved)
        monkeypatch.setattr("apps.api.routers.tenants.upsert_tenant_playbook", upsert_mock)
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.put(
            "/tenants/me/playbook",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
            json={
                "brand_voice": "Precisa",
                "product_overview": "Moda premium",
                "policies": "Cambios 14 días",
                "escalation_notes": "Escalar fraude",
                "agent_instructions": "No inventar stock",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["version"] == 2
        assert upsert_mock.await_args.kwargs["edited_by"] == USER_ID


class TestTenantFactsEndpoints:
    def test_get_facts_returns_existing_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.db.models import TenantFacts

        facts = TenantFacts(
            tenant_id=TENANT_ID,
            data={"support_email": "hola@acme.test", "return_window_days": 30},
            version=4,
            last_edited_by=USER_ID,
            updated_at=datetime.now(UTC),
        )
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_tenant_facts",
            AsyncMock(return_value=facts),
        )
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.get("/tenants/me/facts", headers={"Authorization": f"Bearer {_make_jwt()}"})

        assert resp.status_code == 200
        assert resp.json()["data"]["support_email"] == "hola@acme.test"
        assert resp.json()["version"] == 4

    def test_get_facts_returns_empty_default_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_tenant_facts",
            AsyncMock(return_value=None),
        )
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.get("/tenants/me/facts", headers={"Authorization": f"Bearer {_make_jwt()}"})

        assert resp.status_code == 200
        assert resp.json()["data"] == {}

    def test_update_facts_upserts_json_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.db.models import TenantFacts

        saved = TenantFacts(
            tenant_id=TENANT_ID,
            data={"support_phone": "+34 910 123 456"},
            version=2,
            last_edited_by=USER_ID,
            updated_at=datetime.now(UTC),
        )
        upsert_mock = AsyncMock(return_value=saved)
        monkeypatch.setattr("apps.api.routers.tenants.upsert_tenant_facts", upsert_mock)
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.put(
            "/tenants/me/facts",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
            json={"data": {"support_phone": "+34 910 123 456"}},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["support_phone"] == "+34 910 123 456"
        assert upsert_mock.await_args.kwargs["edited_by"] == USER_ID


class TestTenantOnboardingEndpoints:
    def test_get_onboarding_returns_existing_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.db.models import TenantOnboarding

        onboarding = TenantOnboarding(
            tenant_id=TENANT_ID,
            current_step=3,
            completed_steps=[1, 2],
            step_data={"1": {"company_name": "Acme"}},
            updated_at=datetime.now(UTC),
        )
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_tenant_onboarding",
            AsyncMock(return_value=onboarding),
        )
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.get("/tenants/me/onboarding", headers={"Authorization": f"Bearer {_make_jwt()}"})

        assert resp.status_code == 200
        assert resp.json()["current_step"] == 3
        assert resp.json()["completed_steps"] == [1, 2]

    def test_update_onboarding_sanitizes_completed_steps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.api.db.models import TenantOnboarding

        saved = TenantOnboarding(
            tenant_id=TENANT_ID,
            current_step=4,
            completed_steps=[1, 2, 9],
            step_data={"1": {"company_name": "Acme"}},
            last_edited_by=USER_ID,
        )
        upsert_mock = AsyncMock(return_value=saved)
        monkeypatch.setattr("apps.api.routers.tenants.upsert_tenant_onboarding", upsert_mock)
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.put(
            "/tenants/me/onboarding",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
            json={
                "current_step": 4,
                "completed_steps": [2, 1, 99, 2, 9],
                "step_data": {"1": {"company_name": "Acme"}},
            },
        )

        assert resp.status_code == 200
        assert upsert_mock.await_args.kwargs["completed_steps"] == [1, 2, 9]
        assert upsert_mock.await_args.kwargs["edited_by"] == USER_ID

    def test_submit_onboarding_moves_to_building_and_sends_email(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.api.db.models import TenantOnboarding

        onboarding = TenantOnboarding(
            tenant_id=TENANT_ID,
            current_step=9,
            completed_steps=[1, 2, 3, 4, 5, 6, 7, 8, 9],
            submitted_at=datetime.now(UTC),
        )
        submit_mock = AsyncMock(return_value=onboarding)
        monkeypatch.setattr("apps.api.routers.tenants.get_tenant", AsyncMock(return_value=make_tenant()))
        monkeypatch.setattr("apps.api.routers.tenants.submit_tenant_onboarding", submit_mock)
        app = _make_app(monkeypatch)
        app.state.email_sender = MagicMock()
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/onboarding/submit",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        assert resp.json()["submitted_at"] is not None
        assert submit_mock.await_args.kwargs["edited_by"] == USER_ID
        app.state.email_sender.send_email.assert_called_once()
