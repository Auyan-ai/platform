from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import jwt
import pytest
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.db.models import UserRole
from apps.api.db.site_ingestions import IngestionSubmission, SiteIngestion
from apps.api.routers.site_ingestions import router
from apps.api.services.site_ingestion.models import IngestionStatus, Platform
from apps.api.tests.conftest import TENANT_ID
from apps.api.tests.test_tenants import JWT_ALG, JWT_AUD, JWT_SECRET, USER_ID, FakeAuthSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient

INGESTION_ID = UUID("99999999-9999-9999-9999-999999999999")
MODULE = "apps.api.routers.site_ingestions"
NOW = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)


class FakeWorker:
    def __init__(self) -> None:
        self.notified = 0

    def notify(self) -> None:
        self.notified += 1


def _jwt() -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"aud": JWT_AUD, "sub": str(USER_ID), "exp": now + timedelta(hours=1), "iat": now},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_jwt()}", "X-Tenant-Id": str(TENANT_ID)}


def _client(monkeypatch: pytest.MonkeyPatch, role: UserRole, worker: FakeWorker) -> TestClient:
    reset_user_cache()

    async def _lookup(user_id: UUID, settings: Any) -> UserRecord:
        return UserRecord(tenant_id=TENANT_ID, role=role, email="kenny@auyan.es")

    @asynccontextmanager
    async def _scope(tid: UUID) -> AsyncIterator[Any]:
        assert tid == TENANT_ID
        yield AsyncMock()

    monkeypatch.setattr("apps.api.core.security._lookup_user", _lookup)
    monkeypatch.setattr(f"{MODULE}.tenant_scope", _scope)
    from apps.api.core.config import get_settings

    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(router)
    app.state.site_ingestion_worker = worker
    return TestClient(app)


def _ingestion(status: IngestionStatus) -> SiteIngestion:
    return SiteIngestion(
        id=INGESTION_ID,
        tenant_id=TENANT_ID,
        root_url="https://thinkingmu.com",
        platform=Platform.SHOPIFY,
        status=status,
        attempts=1,
        failure_reason=None,
        stats={"docs": 7, "created": 7},
        cost_usd=0.0,
        created_at=NOW,
        started_at=NOW,
        finished_at=None,
    )


def test_super_admin_queues_an_ingestion_and_wakes_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueue = AsyncMock(return_value=INGESTION_ID)
    monkeypatch.setattr(f"{MODULE}.enqueue_site_ingestion", enqueue)
    worker = FakeWorker()

    resp = _client(monkeypatch, "super_admin", worker).post(
        "/tenants/me/site-ingestions",
        json={"url": "https://www.ThinkingMU.com/es/pages/faq?x=1"},
        headers=_headers(),
    )

    assert resp.status_code == 202
    assert resp.json() == {
        "id": str(INGESTION_ID),
        "status": "queued",
        "root_url": "https://www.thinkingmu.com",
    }
    assert enqueue.await_args.kwargs == {
        "tenant_id": TENANT_ID,
        "root_url": "https://www.thinkingmu.com",
        "requested_by": USER_ID,
    }
    assert worker.notified == 1


def test_a_second_ingestion_while_one_runs_is_a_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{MODULE}.enqueue_site_ingestion", AsyncMock(return_value=None))
    monkeypatch.setattr(
        f"{MODULE}.get_active_site_ingestion",
        AsyncMock(return_value=_ingestion(IngestionStatus.FETCHING)),
    )
    worker = FakeWorker()

    resp = _client(monkeypatch, "super_admin", worker).post(
        "/tenants/me/site-ingestions", json={"url": "thinkingmu.com"}, headers=_headers()
    )

    assert resp.status_code == 409
    assert resp.json()["error"] == "site_ingestion_running"
    assert str(INGESTION_ID) in resp.json()["detail"]
    assert worker.notified == 0


def test_an_invalid_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    enqueue = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.enqueue_site_ingestion", enqueue)

    resp = _client(monkeypatch, "super_admin", FakeWorker()).post(
        "/tenants/me/site-ingestions", json={"url": "no es una url"}, headers=_headers()
    )

    assert resp.status_code == 422
    enqueue.assert_not_awaited()


def test_the_store_cannot_launch_an_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    enqueue = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.enqueue_site_ingestion", enqueue)

    resp = _client(monkeypatch, "tenant_admin", FakeWorker()).post(
        "/tenants/me/site-ingestions", json={"url": "thinkingmu.com"}, headers=_headers()
    )

    assert resp.status_code == 403
    enqueue.assert_not_awaited()


def test_the_store_reads_status_and_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        f"{MODULE}.get_site_ingestion", AsyncMock(return_value=_ingestion(IngestionStatus.READY))
    )

    resp = _client(monkeypatch, "tenant_admin", FakeWorker()).get(
        f"/tenants/me/site-ingestions/{INGESTION_ID}", headers=_headers()
    )

    assert resp.status_code == 200
    body = resp.json()
    assert (body["status"], body["platform"], body["stats"]) == (
        "ready",
        "shopify",
        {"docs": 7, "created": 7},
    )


def test_an_unknown_ingestion_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{MODULE}.get_site_ingestion", AsyncMock(return_value=None))

    resp = _client(monkeypatch, "super_admin", FakeWorker()).get(
        f"/tenants/me/site-ingestions/{INGESTION_ID}", headers=_headers()
    )

    assert resp.status_code == 404


def _submission(status: str = "pending_review", **meta: object) -> IngestionSubmission:
    return IngestionSubmission(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        title="Política de devoluciones",
        source_url="https://thinkingmu.com/policies/refund-policy",
        source_key="thinkingmu.com/policies/refund-policy",
        status=status,
        metadata={"kind": "shop_policy", "priority": "normal", "words": 310, **meta},
        review_note=None,
        reviewed_at=None,
    )


def test_both_roles_list_the_submissions_of_an_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        f"{MODULE}.get_site_ingestion", AsyncMock(return_value=_ingestion(IngestionStatus.READY))
    )
    monkeypatch.setattr(
        f"{MODULE}.list_ingestion_submissions", AsyncMock(return_value=[_submission()])
    )

    for role in ("tenant_admin", "super_admin"):
        resp = _client(monkeypatch, role, FakeWorker()).get(
            f"/tenants/me/site-ingestions/{INGESTION_ID}/submissions", headers=_headers()
        )

        assert resp.status_code == 200
        assert resp.json() == [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "title": "Política de devoluciones",
                "source_url": "https://thinkingmu.com/policies/refund-policy",
                "source_key": "thinkingmu.com/policies/refund-policy",
                "status": "pending_review",
                "kind": "shop_policy",
                "priority": "normal",
                "source": None,
                "words": 310,
                "review_note": None,
            }
        ]


def test_the_store_cannot_approve_a_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    batch = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.approve_submissions_batch", batch)

    resp = _client(monkeypatch, "tenant_admin", FakeWorker()).post(
        f"/tenants/me/site-ingestions/{INGESTION_ID}/approve",
        json={"exclude_submission_ids": []},
        headers=_headers(),
    )

    assert resp.status_code == 403
    batch.assert_not_awaited()


def test_a_batch_cannot_be_approved_while_the_ingestion_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{MODULE}.get_site_ingestion",
        AsyncMock(return_value=_ingestion(IngestionStatus.EXTRACTING)),
    )
    monkeypatch.setattr(f"{MODULE}.list_ingestion_submissions", AsyncMock(return_value=[]))
    batch = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.approve_submissions_batch", batch)
    client = _client(monkeypatch, "super_admin", FakeWorker())
    client.app.state.agent_deps = SimpleNamespace(openai=object())

    resp = client.post(
        f"/tenants/me/site-ingestions/{INGESTION_ID}/approve", json={}, headers=_headers()
    )

    assert resp.status_code == 409
    assert resp.json()["error"] == "site_ingestion_not_ready"
    batch.assert_not_awaited()


def test_latest_returns_the_most_recent_ingestion_or_null(monkeypatch: pytest.MonkeyPatch) -> None:
    latest = AsyncMock(side_effect=[_ingestion(IngestionStatus.READY), None])
    monkeypatch.setattr(f"{MODULE}.get_latest_site_ingestion", latest)
    client = _client(monkeypatch, "super_admin", FakeWorker())

    first = client.get("/tenants/me/site-ingestions/latest", headers=_headers())
    second = client.get("/tenants/me/site-ingestions/latest", headers=_headers())

    assert (first.status_code, first.json()["id"]) == (200, str(INGESTION_ID))
    assert (second.status_code, second.json()) == (200, None)
