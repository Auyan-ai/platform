"""`/tenants/me/returns-policy`: lectura, guardado validado, versiones y roles (ADR 0014 §3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import jwt
import pytest
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.db.returns_policy import PolicyVersion, StaleVersionError, StoredPolicy
from apps.api.routers.returns_policy import router
from apps.api.tests.conftest import TENANT_ID
from apps.api.tests.test_tenants import JWT_ALG, JWT_AUD, JWT_SECRET, USER_ID, FakeAuthSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient

NOW = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)

POLICY: dict[str, Any] = {
    "schema_version": 1,
    "window": {"days": 30, "starts_at": "delivery"},
    "reasons": [
        {
            "code": "defective",
            "label": "Llegó defectuoso",
            "fault": "store",
            "required_evidence": ["photo"],
            "shopify_reason": "damaged-or-defective",
        },
        {
            "code": "too_small",
            "label": "Talla pequeña",
            "fault": "customer",
            "required_evidence": [],
            "shopify_reason": "too-small",
        },
    ],
    "shipping": {
        "method": "customer_ships",
        "return_address": "Calle Mayor 1, 28013 Madrid",
        "payer": {"store_fault": "store", "customer_fault": "customer"},
        "customer_fee": None,
    },
    "refund_days": 14,
    "excluded_product_tags": [],
    "exchanges": {"enabled": False, "kinds": []},
    "returns_require_approval": True,
}


def _jwt() -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"aud": JWT_AUD, "sub": str(USER_ID), "exp": now + timedelta(hours=1), "iat": now},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


def _app(monkeypatch: pytest.MonkeyPatch, role: str = "tenant_admin") -> TestClient:
    reset_user_cache()

    async def _lookup(user_id: UUID, settings: Any) -> UserRecord:
        return UserRecord(tenant_id=TENANT_ID, role=role, email="admin@acme.io")  # type: ignore[arg-type]

    @asynccontextmanager
    async def _scope(tid: UUID) -> AsyncIterator[Any]:
        assert tid == TENANT_ID
        yield AsyncMock()

    monkeypatch.setattr("apps.api.core.security._lookup_user", _lookup)
    monkeypatch.setattr("apps.api.routers.returns_policy.tenant_scope", _scope)
    from apps.api.core.config import get_settings

    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(router)
    return TestClient(app)


def _headers(**extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_jwt()}", **extra}


def _stub_reads(
    monkeypatch: pytest.MonkeyPatch, current: StoredPolicy | None, history: list[PolicyVersion]
) -> None:
    monkeypatch.setattr(
        "apps.api.routers.returns_policy.get_current_returns_policy",
        AsyncMock(return_value=current),
    )
    monkeypatch.setattr(
        "apps.api.routers.returns_policy.list_returns_policy_versions",
        AsyncMock(return_value=history),
    )


def test_get_without_policy_says_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_reads(monkeypatch, None, [])

    resp = _app(monkeypatch).get("/tenants/me/returns-policy", headers=_headers())

    assert resp.status_code == 200
    assert resp.json() == {
        "tenant_id": str(TENANT_ID),
        "policy": None,
        "version": None,
        "updated_at": None,
        "edited_by_email": None,
        "history": [],
    }


def test_get_returns_the_current_version_and_its_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_reads(
        monkeypatch,
        StoredPolicy(version=2, policy=POLICY, edited_by_email="admin@acme.io", created_at=NOW),
        [
            PolicyVersion(version=2, edited_by_email="admin@acme.io", created_at=NOW),
            PolicyVersion(version=1, edited_by_email=None, created_at=NOW - timedelta(days=1)),
        ],
    )

    body = _app(monkeypatch).get("/tenants/me/returns-policy", headers=_headers()).json()

    assert body["version"] == 2
    assert body["policy"]["window"] == {"days": 30, "starts_at": "delivery"}
    assert body["policy"]["reasons"][0]["required_evidence"] == ["photo"]
    assert [h["version"] for h in body["history"]] == [2, 1]
    assert body["edited_by_email"] == "admin@acme.io"


def test_put_validates_and_inserts_the_next_version(monkeypatch: pytest.MonkeyPatch) -> None:
    insert = AsyncMock(return_value=3)
    monkeypatch.setattr("apps.api.routers.returns_policy.insert_returns_policy_version", insert)
    _stub_reads(
        monkeypatch,
        StoredPolicy(version=3, policy=POLICY, edited_by_email="admin@acme.io", created_at=NOW),
        [PolicyVersion(version=3, edited_by_email="admin@acme.io", created_at=NOW)],
    )

    resp = _app(monkeypatch).put(
        "/tenants/me/returns-policy",
        headers=_headers(),
        json={"policy": POLICY, "expected_version": 2},
    )

    assert resp.status_code == 200
    assert resp.json()["version"] == 3
    kwargs = insert.await_args.kwargs
    assert kwargs["expected_version"] == 2
    assert kwargs["edited_by"] == USER_ID
    assert kwargs["schema_version"] == 1
    assert kwargs["policy"]["shipping"]["return_address"] == "Calle Mayor 1, 28013 Madrid"


def test_put_rejects_an_invalid_policy_without_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    insert = AsyncMock()
    monkeypatch.setattr("apps.api.routers.returns_policy.insert_returns_policy_version", insert)
    bad = {**POLICY, "shipping": {**POLICY["shipping"], "return_address": None}}

    resp = _app(monkeypatch).put(
        "/tenants/me/returns-policy",
        headers=_headers(),
        json={"policy": bad, "expected_version": None},
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail[0]["loc"] == ["body", "policy", "shipping"]
    assert detail[0]["msg"] == "Value error, customer_ships exige return_address"
    insert.assert_not_awaited()


def test_put_over_a_newer_version_is_a_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.api.routers.returns_policy.insert_returns_policy_version",
        AsyncMock(side_effect=StaleVersionError(5)),
    )

    resp = _app(monkeypatch).put(
        "/tenants/me/returns-policy",
        headers=_headers(),
        json={"policy": POLICY, "expected_version": 4},
    )

    assert resp.status_code == 409
    assert resp.json()["error"] == "returns_policy_stale"


def test_super_admin_edits_the_tenant_named_in_the_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert = AsyncMock(return_value=1)
    monkeypatch.setattr("apps.api.routers.returns_policy.insert_returns_policy_version", insert)
    _stub_reads(
        monkeypatch,
        StoredPolicy(version=1, policy=POLICY, edited_by_email="kenny@auyan.es", created_at=NOW),
        [],
    )

    resp = _app(monkeypatch, role="super_admin").put(
        "/tenants/me/returns-policy",
        headers=_headers(**{"X-Tenant-Id": str(TENANT_ID)}),
        json={"policy": POLICY, "expected_version": None},
    )

    assert resp.status_code == 200
    assert insert.await_args.args[1] == TENANT_ID
