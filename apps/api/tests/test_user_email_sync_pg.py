"""El email de `auth.users` llega a `public.users` y a `GET /users/me` (#307), en Postgres REAL.

Solo corre con `AUYAN_TEST_DATABASE_URL`. Reusa la base del doctor: todas las migraciones
aplicadas sobre stubs mínimos de Supabase (incluida `auth.users`).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
import pytest
from apps.api.core.config import get_settings
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import reset_user_cache
from apps.api.routers.users import router as users_router
from apps.api.services.doctor.schema import MIGRATIONS_DIR
from apps.api.tests.test_doctor_pg import DSN, migrated_database
from apps.api.tests.test_users import USER_ID, FakeAuthSettings, _make_jwt
from fastapi import FastAPI

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

pytestmark = pytest.mark.skipif(not DSN, reason="AUYAN_TEST_DATABASE_URL no configurada")

MIGRATION = MIGRATIONS_DIR / "20261002000002_sync_user_email_from_auth.sql"


@pytest.fixture
async def conn() -> AsyncIterator[asyncpg.Connection]:
    async with migrated_database() as connection:
        yield connection


async def _seed_user(conn: asyncpg.Connection, user_id: uuid.UUID, email: str) -> None:
    tenant = uuid.uuid4()
    await conn.execute(
        "insert into tenants (id, slug, name) values ($1, $2, 'Acme')", tenant, tenant.hex
    )
    await conn.execute("insert into auth.users (id, email) values ($1, $2)", user_id, email)
    await conn.execute(
        "insert into users (id, tenant_id, email, role) values ($1, $2, $3, 'tenant_admin')",
        user_id,
        tenant,
        email,
    )


async def test_email_change_in_auth_reaches_users_me(
    conn: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_user(conn, USER_ID, "viejo@acme.test")
    before = await conn.fetchval("select updated_at from users where id = $1", USER_ID)

    await conn.execute("update auth.users set email = 'nuevo@acme.test' where id = $1", USER_ID)

    row = await conn.fetchrow("select email, updated_at from users where id = $1", USER_ID)
    assert row["email"] == "nuevo@acme.test"
    assert row["updated_at"] > before

    @asynccontextmanager
    async def _bootstrap() -> AsyncIterator[asyncpg.Connection]:
        yield conn

    monkeypatch.setattr("apps.api.core.security.bootstrap_connection", _bootstrap)
    reset_user_cache()
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(users_router)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/users/me", headers={"Authorization": f"Bearer {_make_jwt()}"})
    finally:
        reset_user_cache()

    assert resp.status_code == 200
    assert resp.json()["email"] == "nuevo@acme.test"


async def test_auth_user_without_email_does_not_touch_users(conn: asyncpg.Connection) -> None:
    user_id = uuid.uuid4()
    await _seed_user(conn, user_id, "fijo@acme.test")

    await conn.execute("update auth.users set email = null where id = $1", user_id)

    assert await conn.fetchval("select email from users where id = $1", user_id) == (
        "fijo@acme.test"
    )


async def test_migration_backfills_drift_and_is_idempotent(conn: asyncpg.Connection) -> None:
    user_id = uuid.uuid4()
    await _seed_user(conn, user_id, "inventado@acme.test")
    await conn.execute("alter table auth.users disable trigger trg_auth_users_sync_email")
    await conn.execute("update auth.users set email = 'real@acme.test' where id = $1", user_id)
    await conn.execute("alter table auth.users enable trigger trg_auth_users_sync_email")
    assert await conn.fetchval("select email from users where id = $1", user_id) == (
        "inventado@acme.test"
    )

    await conn.execute(MIGRATION.read_text(encoding="utf-8"))

    assert await conn.fetchval("select email from users where id = $1", user_id) == (
        "real@acme.test"
    )
