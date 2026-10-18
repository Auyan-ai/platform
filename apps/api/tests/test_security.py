"""Tests para `core.security`: JWT Supabase + AuthContext + dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import jwt
import pytest
from apps.api.core.config import get_settings
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import (
    AuthContext,
    UserRecord,
    _lookup_user,
    get_auth_context,
    get_tenant_id,
    require_role,
    reset_user_cache,
)
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret-for-unit-tests-32b!"  # 35 chars, sobre el mínimo HMAC
JWT_ALG = "HS256"
JWT_AUD = "authenticated"

USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")


# ----------------------------------------------------------------
# Fake Settings + JWT helper
# ----------------------------------------------------------------


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


def _make_jwt(
    *,
    sub: str | None = str(USER_ID),
    aud: str = JWT_AUD,
    secret: str = JWT_SECRET,
    alg: str = JWT_ALG,
    exp_delta_seconds: int = 3600,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "aud": aud,
        "exp": now + timedelta(seconds=exp_delta_seconds),
        "iat": now,
    }
    if sub is not None:
        payload["sub"] = sub
    return jwt.encode(payload, secret, algorithm=alg)


# ----------------------------------------------------------------
# Autouse cleanup
# ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    reset_user_cache()
    yield
    reset_user_cache()


# ----------------------------------------------------------------
# App helper
# ----------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch, user_record: UserRecord | None) -> FastAPI:
    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord | None:
        return user_record

    monkeypatch.setattr("apps.api.core.security._lookup_user", _fake_lookup)

    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()

    @app.get("/me")
    async def me(
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> dict[str, Any]:
        return {
            "user_id": str(auth.user_id),
            "tenant_id": str(auth.tenant_id) if auth.tenant_id else None,
            "role": auth.role,
            "email": auth.email,
        }

    @app.get("/scoped")
    async def scoped(
        tid: Annotated[UUID, Depends(get_tenant_id)],
    ) -> dict[str, str]:
        return {"tenant_id": str(tid)}

    @app.get("/admin", dependencies=[Depends(require_role("tenant_admin"))])
    async def admin_only() -> dict[str, bool]:
        return {"ok": True}

    return app


# ================================================================
# get_auth_context
# ================================================================


class TestGetAuthContext:
    def _tenant_admin_record(self) -> UserRecord:
        return UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="agent@acme.io")

    def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch, self._tenant_admin_record())
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == str(USER_ID)
        assert body["tenant_id"] == str(TENANT_ID)
        assert body["role"] == "tenant_admin"

    def test_missing_bearer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch, self._tenant_admin_record())
        client = TestClient(app)
        resp = client.get("/me")
        assert resp.status_code == 401
        assert resp.json()["error"] == "missing_bearer_token"

    def test_wrong_scheme(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch, self._tenant_admin_record())
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": "Basic something"})
        assert resp.status_code == 401

    def test_expired_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch, self._tenant_admin_record())
        client = TestClient(app)
        token = _make_jwt(exp_delta_seconds=-60)
        resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "token_expired"

    def test_invalid_audience(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch, self._tenant_admin_record())
        client = TestClient(app)
        token = _make_jwt(aud="wrong-aud")
        resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_audience"

    def test_invalid_signature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch, self._tenant_admin_record())
        client = TestClient(app)
        token = _make_jwt(secret="otro-secret-distinto-de-32-bytes-min!")
        resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_token"

    def test_missing_sub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch, self._tenant_admin_record())
        client = TestClient(app)
        token = _make_jwt(sub=None)
        resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "token_missing_sub"

    def test_sub_not_uuid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch, self._tenant_admin_record())
        client = TestClient(app)
        token = _make_jwt(sub="not-a-uuid")
        resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "token_sub_not_uuid"

    def test_user_not_provisioned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _make_app(monkeypatch, None)  # _lookup_user devuelve None
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "user_not_provisioned"

    def test_user_has_no_tenant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # tenant_admin SIN tenant — la DB no debería permitirlo, pero validamos defensa
        broken = UserRecord(tenant_id=None, role="tenant_admin", email="x@x.com")
        app = _make_app(monkeypatch, broken)
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "user_has_no_tenant"

    def test_super_admin_without_tenant_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sa = UserRecord(tenant_id=None, role="super_admin", email="root@auyan.ai")
        app = _make_app(monkeypatch, sa)
        client = TestClient(app)
        resp = client.get("/me", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] is None


# ================================================================
# get_tenant_id
# ================================================================


class TestGetTenantId:
    def test_tenant_admin_no_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="a@a.io")
        app = _make_app(monkeypatch, rec)
        client = TestClient(app)
        resp = client.get("/scoped", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == str(TENANT_ID)

    def test_tenant_admin_matching_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="a@a.io")
        app = _make_app(monkeypatch, rec)
        client = TestClient(app)
        resp = client.get(
            "/scoped",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(TENANT_ID),
            },
        )
        assert resp.status_code == 200

    def test_tenant_admin_cross_tenant_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="a@a.io")
        app = _make_app(monkeypatch, rec)
        client = TestClient(app)
        resp = client.get(
            "/scoped",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(OTHER_TENANT_ID),
            },
        )
        assert resp.status_code == 403
        assert resp.json()["error"] == "cross_tenant_access_denied"

    def test_super_admin_without_header_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sa = UserRecord(tenant_id=None, role="super_admin", email="root@auyan.ai")
        app = _make_app(monkeypatch, sa)
        client = TestClient(app)
        resp = client.get("/scoped", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 403
        assert resp.json()["error"] == "super_admin_requires_x_tenant_id"

    def test_super_admin_with_header_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sa = UserRecord(tenant_id=None, role="super_admin", email="root@auyan.ai")
        app = _make_app(monkeypatch, sa)
        client = TestClient(app)
        resp = client.get(
            "/scoped",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": str(OTHER_TENANT_ID),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == str(OTHER_TENANT_ID)

    def test_invalid_uuid_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sa = UserRecord(tenant_id=None, role="super_admin", email="root@auyan.ai")
        app = _make_app(monkeypatch, sa)
        client = TestClient(app)
        resp = client.get(
            "/scoped",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "X-Tenant-Id": "no-soy-un-uuid",
            },
        )
        assert resp.status_code == 403
        assert resp.json()["error"] == "invalid_x_tenant_id"


# ================================================================
# require_role
# ================================================================


class TestRequireRole:
    def test_allowed_role_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="ad@a.io")
        app = _make_app(monkeypatch, rec)
        client = TestClient(app)
        resp = client.get("/admin", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 200

    def test_disallowed_role_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = UserRecord(tenant_id=None, role="super_admin", email="root@auyan.ai")
        app = _make_app(monkeypatch, rec)
        client = TestClient(app)
        resp = client.get("/admin", headers={"Authorization": f"Bearer {_make_jwt()}"})
        assert resp.status_code == 403
        assert resp.json()["error"] == "insufficient_role"


# ================================================================
# Cache de usuarios
# ================================================================


class TestUserCache:
    """`_lookup_user` cachea por TTL — la segunda call no debe pegar a la DB."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_query = AsyncMock(return_value=(TENANT_ID, "tenant_admin", "x@x.io"))
        monkeypatch.setattr("apps.api.core.security.get_user_for_auth", fake_query)

        @asynccontextmanager
        async def _fake_bootstrap() -> AsyncIterator[Any]:
            yield AsyncMock()

        monkeypatch.setattr("apps.api.core.security.bootstrap_connection", _fake_bootstrap)

        settings = FakeAuthSettings()
        r1 = await _lookup_user(USER_ID, settings)  # type: ignore[arg-type]
        r2 = await _lookup_user(USER_ID, settings)  # type: ignore[arg-type]
        assert r1 == r2
        assert r1 is not None
        assert r1.tenant_id == TENANT_ID
        # Hit la query solo una vez.
        assert fake_query.await_count == 1

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_query = AsyncMock(return_value=None)
        monkeypatch.setattr("apps.api.core.security.get_user_for_auth", fake_query)

        @asynccontextmanager
        async def _fake_bootstrap() -> AsyncIterator[Any]:
            yield AsyncMock()

        monkeypatch.setattr("apps.api.core.security.bootstrap_connection", _fake_bootstrap)

        settings = FakeAuthSettings()
        result = await _lookup_user(uuid4(), settings)  # type: ignore[arg-type]
        assert result is None
