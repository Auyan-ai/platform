"""Doctor contra un Postgres REAL: todas las migraciones aplican en limpio y el doctor lo ve.

Solo corre con `AUYAN_TEST_DATABASE_URL` (Postgres desechable con pgvector; se crea y borra
una base propia). Supabase se simula con stubs mínimos (roles, `auth`, `storage`). Cubre lo
que los mocks no ven: el SQL del catálogo y de la foto del tenant, y que el parser de
migraciones coincide con lo que Postgres crea de verdad.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from apps.api.services.doctor import platform_checks
from apps.api.services.doctor.schema import MIGRATIONS_DIR
from apps.api.services.doctor.snapshot import load_tenant_snapshot
from apps.api.services.integrations_crypto import encrypt_credentials

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

DSN = os.environ.get("AUYAN_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="AUYAN_TEST_DATABASE_URL no configurada")

KEY = bytes(32)

_SUPABASE_STUBS = """
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin; end if;
end $$;
create schema auth;
create table auth.users (id uuid primary key, email text, raw_user_meta_data jsonb);
create function auth.uid() returns uuid language sql stable as $$ select null::uuid $$;
create function auth.jwt() returns jsonb language sql stable as $$ select '{}'::jsonb $$;
create function auth.role() returns text language sql stable as $$ select 'service_role' $$;
create schema storage;
create table storage.buckets (
  id text primary key, name text, public boolean, file_size_limit bigint,
  allowed_mime_types text[], owner uuid,
  created_at timestamptz default now(), updated_at timestamptz default now()
);
create table storage.objects (
  id uuid primary key default gen_random_uuid(), bucket_id text, name text, owner uuid,
  metadata jsonb
);
alter table storage.objects enable row level security;
"""

# pgcrypto no está en todos los Postgres de prueba y en PG ≥ 13 gen_random_uuid es nativo.
_PGCRYPTO = re.compile(r"create extension if not exists pgcrypto[^;]*;", re.I)


@pytest.fixture
async def conn() -> AsyncIterator[asyncpg.Connection]:
    import asyncpg

    database = f"doctor_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(DSN)
    await admin.execute(f"create database {database}")
    connection = await asyncpg.connect(DSN, database=database)
    for codec in ("jsonb", "json"):
        await connection.set_type_codec(
            codec, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )
    try:
        await connection.execute(_SUPABASE_STUBS)
        for path in sorted(Path(MIGRATIONS_DIR).glob("*.sql")):
            await connection.execute(_PGCRYPTO.sub("", path.read_text(encoding="utf-8")))
        yield connection
    finally:
        await connection.close()
        await admin.execute(f"drop database {database} with (force)")
        await admin.close()


async def test_clean_database_has_every_migration_applied(conn: asyncpg.Connection) -> None:
    [check] = await platform_checks(conn)
    assert check.status == "ok", check.detail
    assert "todas aplicadas" in check.detail


async def test_detects_what_is_missing(conn: asyncpg.Connection) -> None:
    await conn.execute("drop table conversation_handoffs cascade")
    await conn.execute("delete from storage.buckets where id = 'conversation-media'")

    [check] = await platform_checks(conn)

    assert check.status == "fail"
    assert "20261001000002_add_conversation_handoffs.sql: falta table conversation_handoffs" in (
        check.detail
    )
    assert "20261001000004_add_conversation_media_bucket.sql" in check.detail


async def test_snapshot_reads_integrations_and_activity(conn: asyncpg.Connection) -> None:
    tenant = uuid.uuid4()
    await conn.execute("insert into tenants (id, slug, name) values ($1, 'acme', 'Acme')", tenant)
    customer = await conn.fetchval(
        "insert into end_customers (tenant_id) values ($1) returning id", tenant
    )
    real, simulated = [
        await conn.fetchval(
            "insert into conversations (tenant_id, end_customer_id, channel, is_simulation) "
            "values ($1, $2, $3, $4) returning id",
            tenant,
            customer,
            channel,
            is_simulation,
        )
        for channel, is_simulation in (("whatsapp", False), ("zendesk", True))
    ]
    messages = []
    for conversation in (real, real, real, simulated):
        messages.append(
            await conn.fetchval(
                "insert into messages (tenant_id, conversation_id, role, direction, content) "
                "values ($1, $2, 'customer', 'inbound', 'hola') returning id",
                tenant,
                conversation,
            )
        )
    for message, status, extra in (
        (messages[0], "failed", "finished_at = now() - interval '1 hour', last_error = 'boom'"),
        (messages[1], "pending", "run_after = now() - interval '30 minutes'"),
        (messages[2], "pending", "run_after = now()"),
    ):
        job = await conn.fetchval(
            "insert into inbound_jobs (tenant_id, conversation_id, inbound_message_id, "
            "end_customer_id, channel, status) values ($1, $2, $3, $4, 'whatsapp', $5) "
            "returning id",
            tenant,
            real,
            message,
            customer,
            status,
        )
        await conn.execute(f"update inbound_jobs set {extra} where id = $1", job)  # noqa: S608
    await conn.execute(
        "insert into tenant_integrations (tenant_id, kind, provider, credentials_encrypted, "
        "config, is_active, is_primary_for_kind) values ($1, 'channel', 'zernio', $2, $3, "
        "true, true), ($1, 'helpdesk', 'chatwoot', $4, '{}', true, true)",
        tenant,
        encrypt_credentials(json.dumps({"api_key": "k"}).encode(), KEY),
        {"account_id": "acc"},
        b"no-cifrado",
    )

    async with conn.transaction():
        await conn.execute("select set_config('app.tenant_id', $1, true)", str(tenant))
        snapshot = await load_tenant_snapshot(conn, tenant, KEY)

    assert snapshot.slug == "acme"
    assert set(snapshot.activity.last_inbound_by_channel) == {"whatsapp"}  # sin simulaciones
    assert snapshot.activity.failed_jobs_24h == 1
    assert snapshot.activity.last_job_error == "boom"
    assert snapshot.activity.stuck_jobs == 1
    zernio = snapshot.find("channel", "zernio")
    assert zernio is not None and zernio.credentials == {"api_key": "k"}
    chatwoot = snapshot.find("helpdesk", "chatwoot")
    assert chatwoot is not None and chatwoot.credentials_error
