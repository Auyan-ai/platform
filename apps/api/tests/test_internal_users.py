"""Tests para internal_users: queries CRUD + user_has_permission + InternalAuthContext."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import jwt
import pytest
from apps.api.core.config import get_settings
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import (
    InternalAuthContext,
    get_internal_auth_context,
    require_internal_permission,
    reset_jwks_cache,
    reset_user_cache,
)
from apps.api.db.models import InternalUser, RolePermission
from apps.api.db.queries import (
    create_internal_user,
    get_internal_user_by_auth_id,
    get_permissions_for_user,
    list_internal_users,
    list_role_permissions,
    soft_delete_internal_user,
    update_internal_user_role,
    user_has_permission,
)
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

# ----------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------

JWT_SECRET = "test-jwt-secret-for-internal-users-42b!"
JWT_ALG = "HS256"
JWT_AUD = "authenticated"

AUTH_USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
INTERNAL_USER_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


# ----------------------------------------------------------------
# Factories
# ----------------------------------------------------------------


def make_internal_user(
    *,
    id: UUID = INTERNAL_USER_ID,
    auth_user_id: UUID = AUTH_USER_ID,
    role: str = "super_admin",
    is_active: bool = True,
) -> InternalUser:
    return InternalUser(
        id=id,
        auth_user_id=auth_user_id,
        name="Kenny Medina",
        email="kenny@auyan.io",
        role=role,  # type: ignore[arg-type]
        is_active=is_active,
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )


def make_conn_mock(**fetchrow_return: Any) -> AsyncMock:
    """Crea un mock de asyncpg.Connection con fetchrow/fetch/execute pre-configurados."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return.get("fetchrow"))
    conn.fetch = AsyncMock(return_value=fetchrow_return.get("fetch", []))
    conn.execute = AsyncMock(return_value=fetchrow_return.get("execute", "UPDATE 1"))
    return conn


# ----------------------------------------------------------------
# Tests: get_internal_user_by_auth_id
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_internal_user_by_auth_id_found() -> None:
    user = make_internal_user()
    row = {
        "id": user.id,
        "auth_user_id": user.auth_user_id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "deleted_at": user.deleted_at,
    }
    conn = make_conn_mock(fetchrow=row)
    result = await get_internal_user_by_auth_id(conn, AUTH_USER_ID)
    assert result is not None
    assert result.id == INTERNAL_USER_ID
    assert result.role == "super_admin"


@pytest.mark.asyncio
async def test_get_internal_user_by_auth_id_not_found() -> None:
    conn = make_conn_mock(fetchrow=None)
    result = await get_internal_user_by_auth_id(conn, AUTH_USER_ID)
    assert result is None


# ----------------------------------------------------------------
# Tests: create_internal_user
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_internal_user() -> None:
    user = make_internal_user()
    row = {
        "id": user.id,
        "auth_user_id": user.auth_user_id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "deleted_at": user.deleted_at,
    }
    conn = make_conn_mock(fetchrow=row)
    result = await create_internal_user(
        conn,
        auth_user_id=AUTH_USER_ID,
        name="Kenny Medina",
        email="kenny@auyan.io",
        role="super_admin",
    )
    assert result.email == "kenny@auyan.io"
    assert result.role == "super_admin"


# ----------------------------------------------------------------
# Tests: update_internal_user_role
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_internal_user_role() -> None:
    user = make_internal_user(role="aide")
    row = {
        "id": user.id,
        "auth_user_id": user.auth_user_id,
        "name": user.name,
        "email": user.email,
        "role": "aide",
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "deleted_at": user.deleted_at,
    }
    conn = make_conn_mock(fetchrow=row)
    result = await update_internal_user_role(conn, internal_user_id=INTERNAL_USER_ID, role="aide")
    assert result is not None
    assert result.role == "aide"


@pytest.mark.asyncio
async def test_update_internal_user_role_not_found() -> None:
    conn = make_conn_mock(fetchrow=None)
    result = await update_internal_user_role(conn, internal_user_id=uuid4(), role="aide")
    assert result is None


# ----------------------------------------------------------------
# Tests: soft_delete_internal_user
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_delete_internal_user_success() -> None:
    conn = make_conn_mock(execute="UPDATE 1")
    result = await soft_delete_internal_user(conn, internal_user_id=INTERNAL_USER_ID)
    assert result is True


@pytest.mark.asyncio
async def test_soft_delete_internal_user_not_found() -> None:
    conn = make_conn_mock(execute="UPDATE 0")
    result = await soft_delete_internal_user(conn, internal_user_id=uuid4())
    assert result is False


# ----------------------------------------------------------------
# Tests: user_has_permission
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_has_permission_true() -> None:
    conn = make_conn_mock(fetchrow={"1": 1})
    result = await user_has_permission(conn, internal_user_id=INTERNAL_USER_ID, permission="aop.edit")
    assert result is True


@pytest.mark.asyncio
async def test_user_has_permission_false() -> None:
    conn = make_conn_mock(fetchrow=None)
    result = await user_has_permission(conn, internal_user_id=INTERNAL_USER_ID, permission="billing.write")
    assert result is False


# ----------------------------------------------------------------
# Tests: get_permissions_for_user
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_permissions_for_user() -> None:
    rows = [{"permission": "aop.edit"}, {"permission": "kb.write"}, {"permission": "approval.l3"}]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    result = await get_permissions_for_user(conn, internal_user_id=INTERNAL_USER_ID)
    assert "aop.edit" in result
    assert "approval.l3" in result
    assert len(result) == 3


@pytest.mark.asyncio
async def test_get_permissions_for_user_empty() -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    result = await get_permissions_for_user(conn, internal_user_id=uuid4())
    assert result == []


# ----------------------------------------------------------------
# Tests: list_role_permissions
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_role_permissions_super_admin() -> None:
    rows = [
        {"role": "super_admin", "permission": "aop.edit"},
        {"role": "super_admin", "permission": "billing.write"},
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    result = await list_role_permissions(conn, "super_admin")
    assert len(result) == 2
    assert all(isinstance(r, RolePermission) for r in result)
    assert all(r.role == "super_admin" for r in result)


# ----------------------------------------------------------------
# Tests: list_internal_users
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_internal_users() -> None:
    user = make_internal_user()
    rows = [
        {
            "id": user.id,
            "auth_user_id": user.auth_user_id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "deleted_at": user.deleted_at,
        }
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    result = await list_internal_users(conn)
    assert len(result) == 1
    assert result[0].email == "kenny@auyan.io"


# ----------------------------------------------------------------
# Tests: InternalAuthContext + get_internal_auth_context (FastAPI)
# ----------------------------------------------------------------


class _SecretWrap:
    def get_secret_value(self) -> str:
        return JWT_SECRET


@dataclass
class FakeInternalAuthSettings:
    auth_user_cache_maxsize: int = 1000
    auth_user_cache_ttl_seconds: int = 60
    supabase_jwks_cache_ttl_seconds: int = 3600
    supabase_jwt_algorithm: str = JWT_ALG
    supabase_jwt_audience: str = JWT_AUD

    @property
    def supabase_jwt_secret(self) -> _SecretWrap:
        return _SecretWrap()


def _make_jwt(user_id: UUID, *, exp_delta_seconds: int = 3600) -> str:
    import time

    payload = {
        "sub": str(user_id),
        "aud": JWT_AUD,
        "exp": int(time.time()) + exp_delta_seconds,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


@pytest.fixture
def internal_auth_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeInternalAuthSettings()

    @app.get("/me")
    async def me(auth: Annotated[InternalAuthContext, Depends(get_internal_auth_context)]) -> dict:
        return {"internal_user_id": str(auth.internal_user_id), "role": auth.role}

    @app.get("/protected")
    async def protected(
        _: Annotated[None, Depends(require_internal_permission("aop.edit"))],
        auth: Annotated[InternalAuthContext, Depends(get_internal_auth_context)],
    ) -> dict:
        return {"ok": True}

    return app


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    reset_user_cache()
    reset_jwks_cache()


def test_get_internal_auth_context_success(
    internal_auth_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_internal_user()
    token = _make_jwt(AUTH_USER_ID)

    @asynccontextmanager
    async def _fake_bootstrap() -> AsyncIterator[AsyncMock]:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": user.id,
                "auth_user_id": user.auth_user_id,
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
                "created_at": user.created_at,
                "updated_at": user.updated_at,
                "deleted_at": user.deleted_at,
            }
        )
        yield conn

    monkeypatch.setattr("apps.api.core.security.bootstrap_connection", _fake_bootstrap)

    client = TestClient(internal_auth_app, raise_server_exceptions=True)
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "super_admin"
    assert data["internal_user_id"] == str(INTERNAL_USER_ID)


def test_get_internal_auth_context_not_provisioned(
    internal_auth_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = _make_jwt(AUTH_USER_ID)

    @asynccontextmanager
    async def _fake_bootstrap() -> AsyncIterator[AsyncMock]:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        yield conn

    monkeypatch.setattr("apps.api.core.security.bootstrap_connection", _fake_bootstrap)

    client = TestClient(internal_auth_app, raise_server_exceptions=False)
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "internal_user_not_provisioned"


def test_require_internal_permission_allowed(
    internal_auth_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_internal_user(role="super_admin")
    token = _make_jwt(AUTH_USER_ID)
    call_count = 0

    @asynccontextmanager
    async def _fake_bootstrap() -> AsyncIterator[AsyncMock]:
        nonlocal call_count
        call_count += 1
        conn = AsyncMock()
        # Primera llamada: get_internal_user_by_auth_id
        # Segunda llamada: user_has_permission
        if call_count == 1:
            conn.fetchrow = AsyncMock(
                return_value={
                    "id": user.id,
                    "auth_user_id": user.auth_user_id,
                    "name": user.name,
                    "email": user.email,
                    "role": user.role,
                    "is_active": user.is_active,
                    "created_at": user.created_at,
                    "updated_at": user.updated_at,
                    "deleted_at": user.deleted_at,
                }
            )
        else:
            conn.fetchrow = AsyncMock(return_value={"1": 1})
        yield conn

    monkeypatch.setattr("apps.api.core.security.bootstrap_connection", _fake_bootstrap)

    client = TestClient(internal_auth_app, raise_server_exceptions=True)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_require_internal_permission_denied(
    internal_auth_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_internal_user(role="cs_manager")
    token = _make_jwt(AUTH_USER_ID)
    call_count = 0

    @asynccontextmanager
    async def _fake_bootstrap() -> AsyncIterator[AsyncMock]:
        nonlocal call_count
        call_count += 1
        conn = AsyncMock()
        if call_count == 1:
            conn.fetchrow = AsyncMock(
                return_value={
                    "id": user.id,
                    "auth_user_id": user.auth_user_id,
                    "name": user.name,
                    "email": user.email,
                    "role": user.role,
                    "is_active": user.is_active,
                    "created_at": user.created_at,
                    "updated_at": user.updated_at,
                    "deleted_at": user.deleted_at,
                }
            )
        else:
            conn.fetchrow = AsyncMock(return_value=None)  # cs_manager no tiene aop.edit
        yield conn

    monkeypatch.setattr("apps.api.core.security.bootstrap_connection", _fake_bootstrap)

    client = TestClient(internal_auth_app, raise_server_exceptions=False)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "insufficient_permission"


def test_get_internal_auth_context_missing_token(internal_auth_app: FastAPI) -> None:
    client = TestClient(internal_auth_app, raise_server_exceptions=False)
    resp = client.get("/me")
    assert resp.status_code == 401
