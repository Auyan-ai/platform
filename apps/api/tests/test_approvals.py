"""Tests para routers/approvals.py y routers/tool_permissions.py."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import jwt
import pytest
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.db.models import PendingApproval, TenantToolPermission
from apps.api.routers.approvals import router as approvals_router
from apps.api.routers.tool_permissions import router as tool_permissions_router
from apps.api.tests.conftest import TENANT_ID
from fastapi import FastAPI
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret-for-unit-tests-32b!"
JWT_ALG = "HS256"
JWT_AUD = "authenticated"
USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CONVERSATION_ID = UUID("22222222-2222-2222-2222-222222222222")
APPROVAL_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
NOW = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)


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
    payload = {
        "sub": str(USER_ID),
        "role": "authenticated",
        "aud": JWT_AUD,
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _sample_approval(status: str = "pending") -> PendingApproval:
    return PendingApproval(
        id=APPROVAL_ID,
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        skill_slug="shopify.cancel_order",
        skill_tier="L3",
        inputs_raw={"order_id": 1001},
        inputs_redacted={"order_id": 1001},
        aop_slug="cancelaciones",
        aop_version=1,
        langfuse_trace_id=None,
        status=status,
        created_at=NOW,
    )


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_user_cache()
    yield  # type: ignore[misc]
    reset_user_cache()


def _make_app(
    monkeypatch: pytest.MonkeyPatch,
    router_under_test=None,
) -> tuple[FastAPI, TestClient]:
    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord:
        return UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="a@b.com")

    monkeypatch.setattr("apps.api.core.security._lookup_user", _fake_lookup)

    @asynccontextmanager
    async def _fake_scope(*args: Any, **kwargs: Any) -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    monkeypatch.setattr("apps.api.routers.approvals.tenant_scope", _fake_scope)
    monkeypatch.setattr("apps.api.routers.tool_permissions.tenant_scope", _fake_scope)

    from apps.api.core.config import get_settings

    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()

    routers = [approvals_router, tool_permissions_router]
    if router_under_test:
        routers = [router_under_test]
    for r in routers:
        app.include_router(r)

    return app, TestClient(app, raise_server_exceptions=False)


# ----------------------------------------------------------------
# GET /approvals
# ----------------------------------------------------------------


class TestListApprovals:
    def test_returns_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.list_pending_approvals",
            AsyncMock(return_value=[_sample_approval()]),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.get("/approvals", headers={"Authorization": f"Bearer {_make_jwt()}"})

        assert resp.status_code == 200
        data = resp.json()
        assert "approvals" in data
        assert len(data["approvals"]) == 1

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.get("/approvals")
        assert resp.status_code == 401


# ----------------------------------------------------------------
# GET /approvals/{id}
# ----------------------------------------------------------------


class TestGetApproval:
    def test_returns_approval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval()),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.get(
            f"/approvals/{APPROVAL_ID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(APPROVAL_ID)
        assert data["status"] == "pending"

    def test_returns_404_when_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=None),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.get(
            f"/approvals/{APPROVAL_ID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 404


# ----------------------------------------------------------------
# POST /approvals/{id}/approve
# ----------------------------------------------------------------


class TestApproveAction:
    def test_approve_already_resolved_returns_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval(status="approved")),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/approve",
            json={"comment": "ok"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 403

    def test_approve_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=None),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/approve",
            json={},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 404

    def test_approve_executes_skill_and_returns_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Happy-path: arma el SkillContext con integration_ctx y ejecuta la skill.

        Regresión del 500: antes construía SkillContext con kwargs obsoletos
        (shopify_domain/shopify_token) → TypeError. Este test recorre la línea 140+.
        """
        from pydantic import BaseModel

        captured: dict[str, Any] = {}

        class _FakeInput(BaseModel):
            order_id: int

        class _FakeOutput(BaseModel):
            cancelled: bool = True

        class _FakeSkill:
            input_schema = _FakeInput

            async def execute(self, ctx: Any, inputs: Any) -> _FakeOutput:
                captured["ctx"] = ctx
                return _FakeOutput()

        class _FakeMsg:
            id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")

        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval()),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_tenant_configuration",
            AsyncMock(return_value=None),
        )
        # No hace falta Shopify real: el helper devuelve None y la fake skill lo ignora.
        monkeypatch.setattr(
            "apps.api.routers.approvals.build_commerce_integration_ctx",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.SkillRegistry.get",
            lambda slug: _FakeSkill,
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.resolve_pending_approval", AsyncMock(return_value=None)
        )
        insert_message_mock = AsyncMock(return_value=_FakeMsg())
        monkeypatch.setattr(
            "apps.api.routers.approvals.insert_message", insert_message_mock
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.update_conversation_last_message",
            AsyncMock(return_value=None),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/approve",
            json={"comment": "ok"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_status"] == "success"
        # El SkillContext se construyó bien (integration_ctx, no kwargs obsoletos).
        assert captured["ctx"].integration_ctx is None
        assert captured["ctx"].tenant_id == str(TENANT_ID)
        # El mensaje 'agent_human' lleva autor (constraint messages_human_has_author).
        assert insert_message_mock.await_args.kwargs["role"] == "agent_human"
        assert insert_message_mock.await_args.kwargs["author_user_id"] == USER_ID


# ----------------------------------------------------------------
# POST /approvals/{id}/reject
# ----------------------------------------------------------------


class TestRejectAction:
    def test_reject_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=None),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/reject",
            json={"comment": "No procede"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 404

    def test_reject_already_resolved_returns_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval(status="rejected")),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/reject",
            json={"comment": "rechazado"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 403

    def test_reject_inserts_message_with_author(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """El mensaje 'agent_human' de rechazo lleva autor (constraint messages_human_has_author)."""

        class _FakeMsg:
            id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")

        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval()),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.resolve_pending_approval", AsyncMock(return_value=None)
        )
        insert_message_mock = AsyncMock(return_value=_FakeMsg())
        monkeypatch.setattr("apps.api.routers.approvals.insert_message", insert_message_mock)
        monkeypatch.setattr(
            "apps.api.routers.approvals.update_conversation_last_message",
            AsyncMock(return_value=None),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/reject",
            json={"comment": "No procede"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        assert resp.json()["execution_status"] == "rejected"
        assert insert_message_mock.await_args.kwargs["author_user_id"] == USER_ID


# ----------------------------------------------------------------
# GET /tenants/me/tool-permissions
# ----------------------------------------------------------------


class TestListToolPermissions:
    def test_returns_permissions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        perm = TenantToolPermission(
            id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            tenant_id=TENANT_ID,
            skill_slug="shopify.get_order",
            is_enabled=True,
            human_approval_required=False,
            threshold_override=None,
        )
        monkeypatch.setattr(
            "apps.api.routers.tool_permissions.list_tool_permissions",
            AsyncMock(return_value=[perm]),
        )

        app, client = _make_app(monkeypatch, tool_permissions_router)
        resp = client.get(
            "/tenants/me/tool-permissions",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "permissions" in data
        assert data["permissions"][0]["skill_slug"] == "shopify.get_order"

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app, client = _make_app(monkeypatch, tool_permissions_router)
        resp = client.get("/tenants/me/tool-permissions")
        assert resp.status_code == 401


# ----------------------------------------------------------------
# PUT /tenants/me/tool-permissions/{slug}
# ----------------------------------------------------------------


class TestUpdateToolPermission:
    def test_skill_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app, client = _make_app(monkeypatch, tool_permissions_router)
        resp = client.put(
            "/tenants/me/tool-permissions/skill.no_existe",
            json={"is_enabled": True, "human_approval_required": False},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 404
