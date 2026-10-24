"""Tests para routers/tool_permissions.py — piso de seguridad L3 (PR2).

El endpoint no deja desactivar la aprobación humana de una skill L3 sin un
reconocimiento explícito del riesgo (`acknowledge_l3_autonomy=true`). Sin ese
flag responde 422 y nunca toca la DB — fail-safe. Con el flag, propaga el opt-out
reconocido al upsert para que `execute_skill` permita la autonomía.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import jwt
import pytest
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.db.models import TenantToolPermission
from apps.api.routers.tool_permissions import router as tool_perms_router
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
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


def _admin_record() -> UserRecord:
    return UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="admin@acme.io")


class _Inp(SkillInput):
    text: str = ""


class _Out(SkillOutput):
    ok: bool = True


class _L3(Skill):
    slug = "test.l3"
    description = "L3 dummy"
    tier: SkillTier = "L3"
    input_schema = _Inp
    output_schema = _Out
    default_threshold = 0.95

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        return _Out()


class _L2(Skill):
    slug = "test.l2"
    description = "L2 dummy"
    tier: SkillTier = "L2"
    input_schema = _Inp
    output_schema = _Out
    default_threshold = 0.85

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        return _Out()


@pytest.fixture(autouse=True)
def _setup() -> Generator[None, None, None]:
    reset_user_cache()
    SkillRegistry._reset()
    SkillRegistry.register(_L3)
    SkillRegistry.register(_L2)
    yield
    SkillRegistry._reset()
    reset_user_cache()


def _perm_model(**ov: Any) -> TenantToolPermission:
    base: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": TENANT_ID,
        "skill_slug": "test.l3",
        "is_enabled": True,
        "threshold_override": None,
        "human_approval_required": False,
    }
    base.update(ov)
    return TenantToolPermission(**base)


def _make_app(monkeypatch: pytest.MonkeyPatch, captured: dict) -> FastAPI:
    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord:
        return _admin_record()

    monkeypatch.setattr("apps.api.core.security._lookup_user", _fake_lookup)

    @asynccontextmanager
    async def _fake_scope(tid: UUID) -> AsyncIterator[Any]:
        yield AsyncMock()

    monkeypatch.setattr("apps.api.routers.tool_permissions.tenant_scope", _fake_scope)

    async def _fake_upsert(conn: Any, **kwargs: Any) -> TenantToolPermission:
        captured.update(kwargs)
        return _perm_model(
            skill_slug=kwargs["skill_slug"],
            is_enabled=kwargs["is_enabled"],
            human_approval_required=kwargs["human_approval_required"],
        )

    monkeypatch.setattr("apps.api.routers.tool_permissions.upsert_tool_permission", _fake_upsert)

    from apps.api.core.config import get_settings

    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(tool_perms_router)
    return app


def _put(client: TestClient, slug: str, body: dict) -> Any:
    return client.put(
        f"/tenants/me/tool-permissions/{slug}",
        json=body,
        headers={"Authorization": f"Bearer {_make_jwt()}"},
    )


class TestL3ApprovalFloor:
    def test_l3_disable_approval_without_acknowledge_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L3 + is_enabled + approval=False SIN acknowledge → 422, no toca la DB."""
        captured: dict = {}
        client = TestClient(_make_app(monkeypatch, captured))
        resp = _put(client, "test.l3", {"is_enabled": True, "human_approval_required": False})
        assert resp.status_code == 422
        assert resp.json()["error"] == "l3_autonomy_not_acknowledged"
        assert captured == {}  # fail-safe: nunca llegó al upsert

    def test_l3_disable_approval_with_acknowledge_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Con acknowledge=True el opt-out reconocido se propaga al upsert."""
        captured: dict = {}
        client = TestClient(_make_app(monkeypatch, captured))
        resp = _put(
            client,
            "test.l3",
            {
                "is_enabled": True,
                "human_approval_required": False,
                "acknowledge_l3_autonomy": True,
            },
        )
        assert resp.status_code == 200
        assert captured["l3_autonomy_acknowledged"] is True

    def test_l3_with_approval_required_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L3 con approval=True no necesita acknowledge; el opt-out queda en False."""
        captured: dict = {}
        client = TestClient(_make_app(monkeypatch, captured))
        resp = _put(client, "test.l3", {"is_enabled": True, "human_approval_required": True})
        assert resp.status_code == 200
        assert captured["l3_autonomy_acknowledged"] is False

    def test_l2_disable_approval_needs_no_acknowledge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El piso es solo para L3: una L2 sin approval pasa sin acknowledge."""
        captured: dict = {}
        client = TestClient(_make_app(monkeypatch, captured))
        resp = _put(client, "test.l2", {"is_enabled": True, "human_approval_required": False})
        assert resp.status_code == 200
        assert captured["l3_autonomy_acknowledged"] is False
