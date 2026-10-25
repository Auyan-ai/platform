from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from apps.api.db import client as db_client

if TYPE_CHECKING:
    import asyncpg

DSN = os.environ.get("AUYAN_TEST_DATABASE_URL")
requires_pg = pytest.mark.skipif(not DSN, reason="AUYAN_TEST_DATABASE_URL no configurada")

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"

_SUPABASE_PRELUDE = """
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key, email text);
create schema if not exists storage;
create table if not exists storage.buckets (
  id text primary key, name text, public boolean, file_size_limit bigint,
  allowed_mime_types text[]
);
do $$ begin create role authenticated nologin; exception when duplicate_object then null; end $$;
do $$ begin create role anon nologin; exception when duplicate_object then null; end $$;
do $$ begin create role service_role nologin; exception when duplicate_object then null; end $$;
do $$ begin create role supabase_auth_admin nologin;
  exception when duplicate_object then null; end $$;
"""


async def apply_migrations(conn: asyncpg.Connection, names: list[Path]) -> None:
    has_pgcrypto = await conn.fetchval(
        "select exists(select 1 from pg_available_extensions where name = 'pgcrypto')"
    )
    for path in names:
        sql = path.read_text()
        if not has_pgcrypto:
            sql = sql.replace("create extension if not exists pgcrypto;", "")
        await conn.execute(sql)


async def create_migrated_database(
    *, stop_before: str | None = None
) -> tuple[str, str, asyncpg.Connection]:
    import asyncpg

    assert DSN is not None
    admin = await asyncpg.connect(DSN)
    if not await admin.fetchval(
        "select exists(select 1 from pg_available_extensions where name = 'vector')"
    ):
        await admin.close()
        pytest.skip("el Postgres de pruebas no tiene pgvector")
    db = f"auyan_test_{uuid.uuid4().hex[:8]}"
    await admin.execute(f"create database {db}")
    await admin.close()
    dsn = str(httpx.URL(DSN).copy_with(path=f"/{db}"))
    setup = await asyncpg.connect(dsn)
    await setup.execute(_SUPABASE_PRELUDE)
    files = sorted(MIGRATIONS.glob("*.sql"))
    if stop_before is not None:
        files = [f for f in files if f.name < stop_before]
    await apply_migrations(setup, files)
    return db, dsn, setup


async def drop_database(db: str) -> None:
    import asyncpg

    assert DSN is not None
    admin = await asyncpg.connect(DSN)
    await admin.execute(f"drop database {db} with (force)")
    await admin.close()


@asynccontextmanager
async def migrated_pool(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[asyncpg.Pool]:
    import asyncpg

    db, dsn, setup = await create_migrated_database()
    await setup.close()
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=6, init=db_client._init_connection)
    monkeypatch.setattr(db_client, "_pool", pool)
    try:
        yield pool
    finally:
        await pool.close()
        await drop_database(db)
