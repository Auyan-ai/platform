"""`conversation_handoffs` + `messages_human_has_author` contra un Postgres REAL.

Solo corre con `AUYAN_TEST_DATABASE_URL` (Postgres desechable; se crea y borra un schema
propio). Cubre lo que los mocks no ven: RLS por tenant, un solo handoff activo por
conversación, lookup por ticket y el autor externo de `agent_human`.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from apps.api.db import queries

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

DSN = os.environ.get("AUYAN_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="AUYAN_TEST_DATABASE_URL no configurada")

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
RLS_ROLE = "auyan_rls_test"

_STUB_SCHEMA = """
create or replace function set_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
create or replace function current_tenant_id() returns uuid language sql stable as $$
  select nullif(current_setting('app.tenant_id', true), '')::uuid $$;
create or replace function is_super_admin() returns boolean language sql stable as $$
  select false $$;
create table tenants (id uuid primary key);
create table conversations (
  id uuid primary key, tenant_id uuid not null references tenants(id), unique (id, tenant_id)
);
create table messages (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
  conversation_id uuid not null, role text not null, direction text not null default 'outbound',
  author_user_id uuid, content text not null default '', attachments jsonb not null default '[]',
  metadata jsonb not null default '{}', created_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint messages_human_has_author check (role <> 'agent_human' or author_user_id is not null)
);
"""


@pytest.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    import json

    import asyncpg

    schema = f"test_handoffs_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(DSN)
    await admin.execute(f"create schema {schema}")
    exists = await admin.fetchval("select 1 from pg_roles where rolname = $1", RLS_ROLE)
    if not exists:
        await admin.execute(f"create role {RLS_ROLE} nologin")
    await admin.close()

    async def _init(conn: asyncpg.Connection) -> None:
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    p = await asyncpg.create_pool(
        DSN,
        min_size=1,
        max_size=3,
        init=_init,
        server_settings={"search_path": f"{schema}, public"},
    )
    async with p.acquire() as conn:
        await conn.execute(_STUB_SCHEMA)
        for name in (
            "20261001000002_add_conversation_handoffs.sql",
            "20261001000003_relax_agent_human_author.sql",
        ):
            await conn.execute((MIGRATIONS / name).read_text())
        await conn.execute(f"grant usage on schema {schema} to {RLS_ROLE}")
        await conn.execute(f"grant select on conversation_handoffs to {RLS_ROLE}")
    try:
        yield p
    finally:
        await p.close()
        admin = await asyncpg.connect(DSN)
        await admin.execute(f"drop schema {schema} cascade")
        await admin.close()


async def _seed(conn: asyncpg.Connection) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, conversation_id = uuid.uuid4(), uuid.uuid4()
    await conn.execute("insert into tenants values ($1)", tenant_id)
    await conn.execute("insert into conversations values ($1, $2)", conversation_id, tenant_id)
    return tenant_id, conversation_id


async def test_one_active_handoff_per_conversation(pool: asyncpg.Pool) -> None:
    import asyncpg

    async with pool.acquire() as conn:
        tenant_id, conv = await _seed(conn)
        first = await queries.insert_handoff(
            conn,
            tenant_id=tenant_id,
            conversation_id=conv,
            target="helpdesk",
            reason="quiere hablar con una persona",
            helpdesk_provider="zendesk",
            external_ticket_id="101",
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await queries.insert_handoff(
                conn,
                tenant_id=tenant_id,
                conversation_id=conv,
                target="helpdesk",
                reason="otra vez",
                helpdesk_provider="zendesk",
                external_ticket_id="102",
            )
        active = await queries.get_active_handoff(conn, tenant_id, conv)
        assert active is not None and active.id == first.id
        by_ticket = await queries.get_handoff_by_ticket(conn, tenant_id, "zendesk", "101")
        assert by_ticket is not None and by_ticket.id == first.id

        assert await queries.close_handoff_row(conn, tenant_id, first.id, "helpdesk_solved")
        assert not await queries.close_handoff_row(conn, tenant_id, first.id, "again")
        assert await queries.get_active_handoff(conn, tenant_id, conv) is None
        # Cerrado el anterior, se puede abrir otro (p. ej. un hold desde el móvil).
        from datetime import UTC, datetime, timedelta

        device = await queries.insert_handoff(
            conn,
            tenant_id=tenant_id,
            conversation_id=conv,
            target="device",
            reason="whatsapp_business_app",
            expires_at=datetime.now(UTC) + timedelta(hours=12),
        )
        assert device.target == "device"


async def test_helpdesk_handoff_requires_ticket_and_device_requires_expiry(
    pool: asyncpg.Pool,
) -> None:
    import asyncpg

    async with pool.acquire() as conn:
        tenant_id, conv = await _seed(conn)
        with pytest.raises(asyncpg.CheckViolationError):
            await queries.insert_handoff(
                conn, tenant_id=tenant_id, conversation_id=conv, target="helpdesk", reason="x"
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await queries.insert_handoff(
                conn, tenant_id=tenant_id, conversation_id=conv, target="device", reason="x"
            )


async def test_rls_isolates_tenants(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        tenant_a, conv_a = await _seed(conn)
        tenant_b, _ = await _seed(conn)
        await queries.insert_handoff(
            conn,
            tenant_id=tenant_a,
            conversation_id=conv_a,
            target="helpdesk",
            reason="x",
            helpdesk_provider="zendesk",
            external_ticket_id="7",
        )
        async with conn.transaction():
            await conn.execute(f"set local role {RLS_ROLE}")
            await conn.execute("select set_config('app.tenant_id', $1, true)", str(tenant_b))
            assert await conn.fetchval("select count(*) from conversation_handoffs") == 0
            await conn.execute("select set_config('app.tenant_id', $1, true)", str(tenant_a))
            assert await conn.fetchval("select count(*) from conversation_handoffs") == 1


async def test_agent_human_needs_author_or_external_author(pool: asyncpg.Pool) -> None:
    import asyncpg

    async with pool.acquire() as conn:
        tenant_id, conv = await _seed(conn)
        insert = (
            "insert into messages (tenant_id, conversation_id, role, content, metadata)"
            " values ($1, $2, 'agent_human', 'hola', $3)"
        )
        await conn.execute(
            insert, tenant_id, conv, {"external_author": {"provider": "zendesk", "id": "9"}}
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(insert, tenant_id, conv, {})
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(insert, tenant_id, conv, {"external_author": "zendesk"})
