"""Tests para routers/tenants.py + services/tenants.py."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
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
    embedding_model: str = "text-embedding-3-small"
    llm_max_retries: int = 1

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


class TestAdminReviewQueue:
    def test_happy_path_requires_super_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = [
            {
                "tenant_id": TENANT_ID,
                "tenant_name": "Acme",
                "tenant_status": "active",
                "agent_lifecycle_state": "active",
                "kb_pending": 2,
                "weekly_reports_pending": 1,
                "approvals_pending": 3,
                "proposals_pending": 4,
                "total_pending": 10,
            }
        ]
        mock = AsyncMock(return_value=rows)
        monkeypatch.setattr("apps.api.routers.tenants.list_admin_review_queue", mock)

        @asynccontextmanager
        async def _fake_bootstrap() -> AsyncIterator[Any]:
            yield AsyncMock()

        monkeypatch.setattr("apps.api.routers.tenants.bootstrap_connection", _fake_bootstrap)
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.get(
            "/tenants/admin/review-queue",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["tenant_name"] == "Acme"
        assert body[0]["total_pending"] == 10
        mock.assert_awaited_once()


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


class TestGetMyTenantInsights:
    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        insights = {
            "days": 14,
            "timeline": [{"date": "2026-05-28", "conversations": 3}],
            "top_intents": [{"label": "returns", "count": 2}],
            "by_channel": [{"label": "email", "count": 3}],
            "by_status": [{"label": "resolved", "count": 2}],
        }
        mock = AsyncMock(return_value=insights)
        monkeypatch.setattr("apps.api.routers.tenants.get_tenant_insights", mock)
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.get(
            "/tenants/me/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["days"] == 14
        assert body["timeline"][0]["conversations"] == 3
        assert body["top_intents"][0]["label"] == "returns"

    def test_custom_days_param(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = AsyncMock(
            return_value={
                "days": 30,
                "timeline": [],
                "top_intents": [],
                "by_channel": [],
                "by_status": [],
            }
        )
        monkeypatch.setattr("apps.api.routers.tenants.get_tenant_insights", mock)
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.get(
            "/tenants/me/insights?days=30",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        mock.assert_awaited_once()
        assert mock.await_args.kwargs["days"] == 30


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


def _make_weekly_report(
    status: str = "draft",
    *,
    recipient_email: str | None = "ops@acme.test",
) -> Any:
    from apps.api.db.models import WeeklyReport

    return WeeklyReport(
        id=UUID("12121212-1212-1212-1212-121212121212"),
        tenant_id=TENANT_ID,
        week_start="2026-05-18",
        week_end="2026-05-24",
        status=status,
        subject="Reporte semanal Auyan: 2026-05-18 a 2026-05-24",
        recipient_email=recipient_email,
        metrics={
            "volume": {"conversations": 10, "messages": 44},
            "resolution_rate": 70.0,
            "escalation_rate": 20.0,
            "top_intents": [{"intent": "returns", "count": 4}],
            "escalation_drivers": [{"reason": "VIP", "count": 2}],
            "cost": {"usd": 1.25, "tokens_in": 1000, "tokens_out": 500},
        },
        narrative="Resumen editable",
        created_by=USER_ID,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestWeeklyReportEndpoints:
    def test_list_reports_allows_tenant_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        list_mock = AsyncMock(return_value=[_make_weekly_report()])
        monkeypatch.setattr("apps.api.routers.tenants.list_weekly_reports", list_mock)
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.get(
            "/tenants/me/weekly-reports?status=draft",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["status"] == "draft"
        assert body[0]["metrics"]["volume"]["conversations"] == 10
        assert list_mock.await_args.kwargs["status"] == "draft"

    def test_generate_report_requires_super_admin_and_target_tenant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create_mock = AsyncMock(return_value=_make_weekly_report())
        monkeypatch.setattr(
            "apps.api.routers.tenants.create_or_refresh_weekly_report_draft",
            create_mock,
        )
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/weekly-reports/generate",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
            json={
                "week_start": "2026-05-18",
                "week_end": "2026-05-24",
                "recipient_email": "ops@acme.test",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["subject"].startswith("Reporte semanal Auyan")
        assert create_mock.await_args.args[1] == TENANT_ID
        assert create_mock.await_args.kwargs["created_by"] == USER_ID

    def test_update_report_rejects_non_draft(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_weekly_report",
            AsyncMock(return_value=_make_weekly_report(status="approved")),
        )
        update_mock = AsyncMock()
        monkeypatch.setattr("apps.api.routers.tenants.update_weekly_report_draft", update_mock)
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.patch(
            "/tenants/me/weekly-reports/12121212-1212-1212-1212-121212121212",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
            json={
                "subject": "Reporte semanal editado",
                "narrative": "Narrativa final",
                "recipient_email": "ops@acme.test",
            },
        )

        assert resp.status_code == 409
        update_mock.assert_not_awaited()

    def test_submit_report_moves_draft_to_pending_review(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_weekly_report",
            AsyncMock(return_value=_make_weekly_report(status="draft")),
        )
        submit_mock = AsyncMock(return_value=_make_weekly_report(status="pending_review"))
        monkeypatch.setattr(
            "apps.api.routers.tenants.submit_weekly_report_for_review",
            submit_mock,
        )
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/weekly-reports/12121212-1212-1212-1212-121212121212/submit",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "pending_review"
        submit_mock.assert_awaited_once()

    def test_approve_report_requires_pending_review(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_weekly_report",
            AsyncMock(return_value=_make_weekly_report(status="pending_review")),
        )
        approve_mock = AsyncMock(return_value=_make_weekly_report(status="approved"))
        monkeypatch.setattr("apps.api.routers.tenants.approve_weekly_report", approve_mock)
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/weekly-reports/12121212-1212-1212-1212-121212121212/approve",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        assert approve_mock.await_args.kwargs["approved_by"] == USER_ID

    def test_send_report_marks_sent_after_postmark_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_weekly_report",
            AsyncMock(return_value=_make_weekly_report(status="approved")),
        )
        sent_report = _make_weekly_report(status="sent")
        mark_sent = AsyncMock(return_value=sent_report)
        monkeypatch.setattr("apps.api.routers.tenants.mark_weekly_report_sent", mark_sent)
        mark_failed = AsyncMock()
        monkeypatch.setattr(
            "apps.api.routers.tenants.mark_weekly_report_send_failed",
            mark_failed,
        )
        app = _make_super_admin_app(monkeypatch)
        email_sender = MagicMock()
        email_sender.send_email_now = AsyncMock(return_value={"MessageID": "pm-123"})
        app.state.email_sender = email_sender
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/weekly-reports/12121212-1212-1212-1212-121212121212/send",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"
        assert resp.json()["postmark_message_id"] is None
        email_sender.send_email_now.assert_awaited_once()
        assert email_sender.send_email_now.await_args.kwargs["tag"] == "weekly-report"
        assert mark_sent.await_args.kwargs["postmark_message_id"] == "pm-123"
        assert mark_sent.await_args.kwargs["sent_by"] == USER_ID
        mark_failed.assert_not_awaited()

    def test_send_report_requires_recipient_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_weekly_report",
            AsyncMock(return_value=_make_weekly_report(status="approved", recipient_email=None)),
        )
        app = _make_super_admin_app(monkeypatch)
        app.state.email_sender = MagicMock()
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/weekly-reports/12121212-1212-1212-1212-121212121212/send",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
        )

        assert resp.status_code == 400

    def test_send_report_records_postmark_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_weekly_report",
            AsyncMock(return_value=_make_weekly_report(status="approved")),
        )
        mark_failed = AsyncMock(return_value=_make_weekly_report(status="approved"))
        monkeypatch.setattr(
            "apps.api.routers.tenants.mark_weekly_report_send_failed",
            mark_failed,
        )
        monkeypatch.setattr("apps.api.routers.tenants.mark_weekly_report_sent", AsyncMock())
        app = _make_super_admin_app(monkeypatch)
        email_sender = MagicMock()
        email_sender.send_email_now = AsyncMock(side_effect=RuntimeError("Postmark down"))
        app.state.email_sender = email_sender
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/weekly-reports/12121212-1212-1212-1212-121212121212/send",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
        )

        assert resp.status_code == 503
        assert mark_failed.await_args.kwargs["send_error"] == "Postmark down"


def _make_outbound_email_template() -> Any:
    from apps.api.db.models import OutboundEmailTemplate

    return OutboundEmailTemplate(
        id=UUID("34343434-3434-3434-3434-343434343434"),
        tenant_id=TENANT_ID,
        key="lifecycle.welcome",
        name="Bienvenida lifecycle",
        subject_template="Auyan listo para {{tenant_name}}",
        text_body_template="Hola {{tenant_name}}, estamos listos.",
        html_body_template="<p>Hola {{tenant_name}}, estamos listos.</p>",
        variables=["tenant_name"],
        is_active=True,
        version=1,
        created_by=USER_ID,
        updated_by=USER_ID,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_outbound_email_job(status: str = "queued") -> Any:
    from apps.api.db.models import OutboundEmailJob

    return OutboundEmailJob(
        id=UUID("45454545-4545-4545-4545-454545454545"),
        tenant_id=TENANT_ID,
        template_id=UUID("34343434-3434-3434-3434-343434343434"),
        recipient_email="ops@acme.test",
        subject="Auyan listo",
        text_body="Hola equipo",
        html_body="<p>Hola equipo</p>",
        tag="lifecycle",
        payload={"tenant_name": "Acme"},
        status=status,
        attempts=0,
        max_attempts=3,
        next_attempt_at=datetime.now(UTC),
        requested_by=USER_ID,
        idempotency_key="welcome-acme",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestOutboundEmailEndpoints:
    def test_list_templates_requires_super_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        list_mock = AsyncMock(return_value=[_make_outbound_email_template()])
        monkeypatch.setattr("apps.api.routers.tenants.list_outbound_email_templates", list_mock)
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.get(
            "/tenants/me/outbound-email/templates?include_inactive=true",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["key"] == "lifecycle.welcome"
        assert body[0]["variables"] == ["tenant_name"]
        assert list_mock.await_args.kwargs["include_inactive"] is True

    def test_create_template_persists_editable_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create_mock = AsyncMock(return_value=_make_outbound_email_template())
        monkeypatch.setattr("apps.api.routers.tenants.create_outbound_email_template", create_mock)
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/outbound-email/templates",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
            json={
                "key": "lifecycle.welcome",
                "name": "Bienvenida lifecycle",
                "subject_template": "Auyan listo para {{tenant_name}}",
                "text_body_template": "Hola {{tenant_name}}, estamos listos.",
                "html_body_template": "<p>Hola {{tenant_name}}, estamos listos.</p>",
                "variables": ["tenant_name"],
            },
        )

        assert resp.status_code == 200
        assert resp.json()["version"] == 1
        assert create_mock.await_args.kwargs["created_by"] == USER_ID
        assert create_mock.await_args.kwargs["key"] == "lifecycle.welcome"

    def test_update_template_404_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_outbound_email_template",
            AsyncMock(return_value=None),
        )
        update_mock = AsyncMock()
        monkeypatch.setattr("apps.api.routers.tenants.update_outbound_email_template", update_mock)
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.patch(
            "/tenants/me/outbound-email/templates/34343434-3434-3434-3434-343434343434",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
            json={
                "name": "Nueva bienvenida",
                "subject_template": "Hola",
                "text_body_template": "Texto",
                "variables": [],
                "is_active": True,
            },
        )

        assert resp.status_code == 404
        update_mock.assert_not_awaited()

    def test_list_jobs_filters_by_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        list_mock = AsyncMock(return_value=[_make_outbound_email_job(status="failed")])
        monkeypatch.setattr("apps.api.routers.tenants.list_outbound_email_jobs", list_mock)
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.get(
            "/tenants/me/outbound-email/jobs?status=failed&limit=25",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
        )

        assert resp.status_code == 200
        assert resp.json()[0]["status"] == "failed"
        assert list_mock.await_args.kwargs["status"] == "failed"
        assert list_mock.await_args.kwargs["limit"] == 25

    def test_enqueue_job_validates_template_and_records_requester(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_outbound_email_template",
            AsyncMock(return_value=_make_outbound_email_template()),
        )
        enqueue_mock = AsyncMock(return_value=_make_outbound_email_job())
        monkeypatch.setattr("apps.api.routers.tenants.enqueue_outbound_email_job", enqueue_mock)
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/outbound-email/jobs",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
            json={
                "template_id": "34343434-3434-3434-3434-343434343434",
                "recipient_email": "ops@acme.test",
                "subject": "Auyan listo",
                "text_body": "Hola equipo",
                "html_body": "<p>Hola equipo</p>",
                "tag": "lifecycle",
                "payload": {"tenant_name": "Acme"},
                "idempotency_key": "welcome-acme",
                "max_attempts": 3,
            },
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        assert enqueue_mock.await_args.kwargs["requested_by"] == USER_ID
        assert enqueue_mock.await_args.kwargs["idempotency_key"] == "welcome-acme"


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


class TestTenantKnowledgeSubmissionsEndpoints:
    def test_list_kb_submissions_returns_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.db.models import TenantKnowledgeSubmission

        submission = TenantKnowledgeSubmission(
            id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            tenant_id=TENANT_ID,
            title="Política de devoluciones",
            source_type="text",
            content="El cliente puede devolver productos durante 30 días.",
            status="pending_review",
            submitted_by=USER_ID,
            created_at=datetime.now(UTC),
        )
        list_mock = AsyncMock(return_value=[submission])
        monkeypatch.setattr("apps.api.routers.tenants.list_tenant_knowledge_submissions", list_mock)
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.get(
            "/tenants/me/kb-submissions?status=pending_review",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        assert resp.json()[0]["title"] == "Política de devoluciones"
        assert list_mock.await_args.kwargs["status"] == "pending_review"

    def test_create_kb_submission_stores_pending_review(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.api.db.models import TenantKnowledgeSubmission

        submission = TenantKnowledgeSubmission(
            id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            tenant_id=TENANT_ID,
            title="FAQ envíos",
            source_type="url",
            source_url="https://acme.test/envios",
            content="Los pedidos tardan 24-48 horas hábiles.",
            status="pending_review",
            submitted_by=USER_ID,
        )
        create_mock = AsyncMock(return_value=submission)
        monkeypatch.setattr("apps.api.routers.tenants.create_tenant_knowledge_submission", create_mock)
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/kb-submissions",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
            json={
                "title": "FAQ envíos",
                "source_type": "url",
                "source_url": "https://acme.test/envios",
                "content": "Los pedidos tardan 24-48 horas hábiles.",
            },
        )

        assert resp.status_code == 201
        assert resp.json()["status"] == "pending_review"
        assert create_mock.await_args.kwargs["submitted_by"] == USER_ID

    def test_create_kb_submission_requires_content_or_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _make_app(monkeypatch)
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/kb-submissions",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
            json={"title": "Vacío", "source_type": "text", "content": ""},
        )

        assert resp.status_code == 422

    def test_reject_kb_submission_marks_reviewed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.db.models import TenantKnowledgeSubmission

        rejected = TenantKnowledgeSubmission(
            id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            tenant_id=TENANT_ID,
            title="FAQ vieja",
            source_type="text",
            content="Contenido antiguo.",
            status="rejected",
            reviewed_by=USER_ID,
            review_note="Duplicado",
        )
        reject_mock = AsyncMock(return_value=rejected)
        monkeypatch.setattr("apps.api.routers.tenants.reject_tenant_knowledge_submission", reject_mock)
        app = _make_super_admin_app(monkeypatch)
        client = TestClient(app)

        resp = client.post(
            "/tenants/me/kb-submissions/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/reject",
            headers={"Authorization": f"Bearer {_make_jwt()}", "X-Tenant-Id": str(TENANT_ID)},
            json={"review_note": "Duplicado"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        assert reject_mock.await_args.kwargs["reviewed_by"] == USER_ID

    def test_approve_kb_submission_embeds_and_indexes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.api.db.models import TenantKnowledgeSubmission

        submission_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        pending = TenantKnowledgeSubmission(
            id=submission_id,
            tenant_id=TENANT_ID,
            title="FAQ envíos",
            source_type="text",
            content="Los pedidos tardan 24-48 horas hábiles.",
            status="pending_review",
            submitted_by=USER_ID,
        )
        approved = pending.model_copy(
            update={
                "status": "approved",
                "reviewed_by": USER_ID,
                "processed_document_id": UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            }
        )
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_tenant_knowledge_submission",
            AsyncMock(return_value=pending),
        )
        approve_mock = AsyncMock(return_value=approved)
        monkeypatch.setattr(
            "apps.api.routers.tenants.approve_tenant_knowledge_submission_with_document",
            approve_mock,
        )
        monkeypatch.setattr(
            "apps.api.routers.tenants.embed_kb_chunks",
            AsyncMock(return_value=[("Los pedidos tardan 24-48 horas hábiles.", [0.1] * 1536)]),
        )
        app = _make_super_admin_app(monkeypatch)
        app.state.agent_deps = SimpleNamespace(openai=object())
        client = TestClient(app)

        resp = client.post(
            f"/tenants/me/kb-submissions/{submission_id}/approve",
            headers={"Authorization": f"Bearer {_make_jwt()}", "X-Tenant-Id": str(TENANT_ID)},
            json={"review_note": "Aprobado"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        assert approve_mock.await_args.kwargs["reviewed_by"] == USER_ID
        assert approve_mock.await_args.kwargs["chunks"][0][1] == [0.1] * 1536
