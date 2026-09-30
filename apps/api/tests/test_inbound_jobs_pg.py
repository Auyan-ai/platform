"""Cola `inbound_jobs` contra un Postgres REAL (claim, advisory lock, ráfagas, backoff).

Los mocks no ven concurrencia ni errores de tipos del SQL. Estos tests corren solo si
`AUYAN_TEST_DATABASE_URL` apunta a un Postgres desechable (se crea y borra un schema
propio). En CI (sin la variable) se saltan.

    AUYAN_TEST_DATABASE_URL=postgresql://user@localhost/postgres .venv/bin/pytest tests/test_inbound_jobs_pg.py
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from apps.api.db.inbound_jobs import (
    claim_next_inbound_job,
    claim_webhook_idempotency_key,
    complete_inbound_job,
    enqueue_inbound_job,
    extend_inbound_job_lease,
    fail_inbound_job,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

DSN = os.environ.get("AUYAN_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="AUYAN_TEST_DATABASE_URL no configurada")

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"

# Stubs mínimos de las tablas referenciadas + helpers que la migración usa.
_STUB_SCHEMA = """
create or replace function set_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
create or replace function current_tenant_id() returns uuid language sql stable as $$
  select nullif(current_setting('app.tenant_id', true), '')::uuid $$;
create table tenants (id uuid primary key);
create table end_customers (id uuid primary key);
create table conversations (id uuid primary key);
create table messages (
  id uuid primary key, tenant_id uuid, conversation_id uuid, role text,
  direction text not null default 'inbound', author_user_id uuid,
  attachments jsonb not null default '[]',
  content text not null default '', metadata jsonb not null default '{}',
  created_at timestamptz not null default clock_timestamp(), deleted_at timestamptz
);
create table idempotency_keys (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  key text not null, request_path text not null,
  status text not null default 'pending', response_status integer, response_body jsonb,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '24 hours'),
  deleted_at timestamptz,
  unique (tenant_id, key)
);
"""


@pytest.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    import asyncpg

    schema = f"test_inbound_jobs_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(DSN)
    await admin.execute(f"create schema {schema}")
    await admin.close()

    # server_settings (no un SET): el pool hace RESET ALL al devolver conexiones.
    p = await asyncpg.create_pool(
        DSN, min_size=1, max_size=6, server_settings={"search_path": f"{schema}, public"}
    )
    async with p.acquire() as conn:
        await conn.execute(_STUB_SCHEMA.replace("public.current_tenant_id", "current_tenant_id"))
        sql = (MIGRATIONS / "20260930000000_add_inbound_jobs.sql").read_text()
        await conn.execute(sql.replace("public.current_tenant_id", "current_tenant_id"))
    try:
        yield p
    finally:
        await p.close()
        admin = await asyncpg.connect(DSN)
        await admin.execute(f"drop schema {schema} cascade")
        await admin.close()


async def _seed_conversation(conn: asyncpg.Connection) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    tenant_id, conversation_id, customer_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await conn.execute("insert into tenants values ($1) on conflict do nothing", tenant_id)
    await conn.execute("insert into conversations values ($1)", conversation_id)
    await conn.execute("insert into end_customers values ($1)", customer_id)
    return tenant_id, conversation_id, customer_id


async def _enqueue(
    conn: asyncpg.Connection,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID]:
    message_id = uuid.uuid4()
    await conn.execute(
        "insert into messages (id, tenant_id, conversation_id, role, content)"
        " values ($1, $2, $3, 'customer', $4)",
        message_id,
        tenant_id,
        conversation_id,
        f"msg {message_id}",
    )
    job_id = await enqueue_inbound_job(
        conn,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        inbound_message_id=message_id,
        end_customer_id=customer_id,
        channel="zendesk",
    )
    return job_id, message_id


async def _status(conn: asyncpg.Connection, job_id: uuid.UUID) -> str:
    return str(await conn.fetchval("select status from inbound_jobs where id = $1", job_id))


async def test_claim_marks_running_and_empty_queue_returns_none(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        t, c, cu = await _seed_conversation(conn)
        job_id, msg_id = await _enqueue(conn, t, c, cu)

        claimed = await claim_next_inbound_job(conn, lease_seconds=60)
        assert claimed is not None
        assert claimed.id == job_id
        assert claimed.inbound_message_id == msg_id
        assert claimed.attempts == 1
        assert claimed.is_retry is False
        assert claimed.absorbed_message_ids == ()
        assert await _status(conn, job_id) == "running"

        assert await claim_next_inbound_job(conn, lease_seconds=60) is None

        await complete_inbound_job(conn, job_id=job_id, decision="respond")
        row = await conn.fetchrow(
            "select status, decision, finished_at from inbound_jobs where id=$1", job_id
        )
        assert (row["status"], row["decision"]) == ("done", "respond")
        assert row["finished_at"] is not None


async def test_second_message_waits_while_conversation_turn_is_running(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        t, c, cu = await _seed_conversation(conn)
        first, _ = await _enqueue(conn, t, c, cu)
        claimed = await claim_next_inbound_job(conn, lease_seconds=60)
        assert claimed is not None and claimed.id == first

        second, _ = await _enqueue(conn, t, c, cu)
        # La conversación está ocupada: el segundo mensaje NO se reclama.
        assert await claim_next_inbound_job(conn, lease_seconds=60) is None

        await complete_inbound_job(conn, job_id=first, decision="respond")
        nxt = await claim_next_inbound_job(conn, lease_seconds=60)
        assert nxt is not None and nxt.id == second


async def test_other_conversations_are_not_blocked(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        t1, c1, cu1 = await _seed_conversation(conn)
        t2, c2, cu2 = await _seed_conversation(conn)
        a, _ = await _enqueue(conn, t1, c1, cu1)
        b, _ = await _enqueue(conn, t2, c2, cu2)
        first = await claim_next_inbound_job(conn, lease_seconds=60)
        second = await claim_next_inbound_job(conn, lease_seconds=60)
        assert first is not None and second is not None
        assert {first.id, second.id} == {a, b}


async def test_burst_is_coalesced_into_newest_message(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        t, c, cu = await _seed_conversation(conn)
        j1, m1 = await _enqueue(conn, t, c, cu)
        j2, m2 = await _enqueue(conn, t, c, cu)
        j3, m3 = await _enqueue(conn, t, c, cu)

        claimed = await claim_next_inbound_job(conn, lease_seconds=60)
        assert claimed is not None
        assert claimed.id == j3
        assert claimed.inbound_message_id == m3
        assert claimed.absorbed_message_ids == (m1, m2)
        for old in (j1, j2):
            row = await conn.fetchrow(
                "select status, superseded_by from inbound_jobs where id=$1", old
            )
            assert (row["status"], row["superseded_by"]) == ("superseded", j3)
        assert await claim_next_inbound_job(conn, lease_seconds=60) is None


async def test_expired_lease_is_reclaimed_as_retry(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        t, c, cu = await _seed_conversation(conn)
        job_id, _ = await _enqueue(conn, t, c, cu)
        assert await claim_next_inbound_job(conn, lease_seconds=60) is not None
        # Simula un crash de la instancia: el lease vence sin heartbeat.
        await conn.execute(
            "update inbound_jobs set locked_until = now() - interval '1 second' where id=$1", job_id
        )
        again = await claim_next_inbound_job(conn, lease_seconds=60)
        assert again is not None
        assert again.id == job_id
        assert again.attempts == 2
        assert again.is_retry is True


async def test_heartbeat_keeps_lease_alive(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        t, c, cu = await _seed_conversation(conn)
        job_id, _ = await _enqueue(conn, t, c, cu)
        assert await claim_next_inbound_job(conn, lease_seconds=1) is not None
        await extend_inbound_job_lease(conn, job_id=job_id, lease_seconds=60)
        await asyncio.sleep(1.2)
        assert await claim_next_inbound_job(conn, lease_seconds=60) is None


async def test_fail_retries_with_backoff_then_fails(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        t, c, cu = await _seed_conversation(conn)
        job_id, _ = await _enqueue(conn, t, c, cu)
        await conn.execute("update inbound_jobs set max_attempts = 2 where id=$1", job_id)

        assert await claim_next_inbound_job(conn, lease_seconds=60) is not None
        status = await fail_inbound_job(conn, job_id=job_id, error="boom", retry_in_seconds=3600)
        assert status == "pending"
        # En backoff: no se reclama todavía.
        assert await claim_next_inbound_job(conn, lease_seconds=60) is None

        await conn.execute("update inbound_jobs set run_after = now() where id=$1", job_id)
        again = await claim_next_inbound_job(conn, lease_seconds=60)
        assert again is not None and again.attempts == 2
        status = await fail_inbound_job(
            conn, job_id=job_id, error="boom again", retry_in_seconds=60
        )
        assert status == "failed"
        row = await conn.fetchrow(
            "select last_error, finished_at from inbound_jobs where id=$1", job_id
        )
        assert row["last_error"] == "boom again"
        assert row["finished_at"] is not None


async def test_fail_without_retry_is_terminal(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        t, c, cu = await _seed_conversation(conn)
        job_id, _ = await _enqueue(conn, t, c, cu)
        assert await claim_next_inbound_job(conn, lease_seconds=60) is not None
        assert (
            await fail_inbound_job(conn, job_id=job_id, error="x", retry_in_seconds=None)
            == "failed"
        )


async def test_concurrent_claimers_never_run_same_conversation_twice(pool: asyncpg.Pool) -> None:
    """6 workers compiten por 2 conversaciones con 5 mensajes cada una: como mucho un
    turno por conversación, y cada conversación queda reclamada una sola vez."""
    async with pool.acquire() as conn:
        convs = [await _seed_conversation(conn) for _ in range(2)]
        for _ in range(5):
            for t, c, cu in convs:
                await _enqueue(conn, t, c, cu)

    async def _claimer() -> object:
        async with pool.acquire() as conn:
            return await claim_next_inbound_job(conn, lease_seconds=60)

    results = await asyncio.gather(*(_claimer() for _ in range(6)))
    claimed = [r for r in results if r is not None]
    per_conv = [r.conversation_id for r in claimed]  # type: ignore[attr-defined]
    assert len(per_conv) == len(set(per_conv))
    async with pool.acquire() as conn:
        running = await conn.fetch(
            "select conversation_id, count(*) from inbound_jobs where status='running' group by 1"
        )
    assert all(r["count"] == 1 for r in running)


async def test_webhook_idempotency_key_dedupes_and_rolls_back(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        t, _, _ = await _seed_conversation(conn)
        # Si la transacción del intake cae, la key no queda reclamada.
        with pytest.raises(RuntimeError):
            async with conn.transaction():
                assert await claim_webhook_idempotency_key(
                    conn, tenant_id=t, key="zendesk:1:1", request_path="/webhooks/zendesk"
                )
                raise RuntimeError("fallo al persistir")
        async with conn.transaction():
            assert await claim_webhook_idempotency_key(
                conn, tenant_id=t, key="zendesk:1:1", request_path="/webhooks/zendesk"
            )
        async with conn.transaction():
            assert not await claim_webhook_idempotency_key(
                conn, tenant_id=t, key="zendesk:1:1", request_path="/webhooks/zendesk"
            )


async def test_concurrent_duplicate_webhooks_only_one_wins(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        t, _, _ = await _seed_conversation(conn)

    async def _intake() -> bool:
        async with pool.acquire() as conn, conn.transaction():
            won = await claim_webhook_idempotency_key(
                conn, tenant_id=t, key="zendesk:9:9", request_path="/webhooks/zendesk"
            )
            await asyncio.sleep(0.05)  # simula el resto del intake
            return won

    results = await asyncio.gather(*(_intake() for _ in range(5)))
    assert results.count(True) == 1


async def test_released_job_is_reclaimed_immediately_as_retry(pool: asyncpg.Pool) -> None:
    from apps.api.db.inbound_jobs import release_inbound_job

    async with pool.acquire() as conn:
        t, c, cu = await _seed_conversation(conn)
        job_id, _ = await _enqueue(conn, t, c, cu)
        first = await claim_next_inbound_job(conn, lease_seconds=600)
        assert first is not None and first.enqueued_at is not None
        await release_inbound_job(conn, job_id=job_id)
        again = await claim_next_inbound_job(conn, lease_seconds=600)
        assert again is not None and again.id == job_id and again.is_retry is True


async def test_absorbed_contents_and_already_answered(pool: asyncpg.Pool) -> None:
    from apps.api.db.inbound_jobs import get_inbound_message_contents, inbound_already_answered

    async with pool.acquire() as conn:
        t, c, cu = await _seed_conversation(conn)
        _, m1 = await _enqueue(conn, t, c, cu)
        _, m2 = await _enqueue(conn, t, c, cu)
        contents = await get_inbound_message_contents(
            conn, tenant_id=t, conversation_id=c, message_ids=[m2, m1]
        )
        assert contents == [f"msg {m1}", f"msg {m2}"]
        # Otro tenant no ve esos mensajes.
        assert (
            await get_inbound_message_contents(
                conn, tenant_id=uuid.uuid4(), conversation_id=c, message_ids=[m1]
            )
            == []
        )

        assert not await inbound_already_answered(
            conn, tenant_id=t, conversation_id=c, inbound_message_id=m2
        )
        await conn.execute(
            "insert into messages (id, tenant_id, conversation_id, role, metadata)"
            " values ($1, $2, $3, 'agent_ai', jsonb_build_object('inbound_message_id', $4::text))",
            uuid.uuid4(),
            t,
            c,
            str(m2),
        )
        assert await inbound_already_answered(
            conn, tenant_id=t, conversation_id=c, inbound_message_id=m2
        )
        assert not await inbound_already_answered(
            conn, tenant_id=t, conversation_id=c, inbound_message_id=m1
        )


async def test_soft_deleted_or_expired_idempotency_key_can_be_reclaimed(pool: asyncpg.Pool) -> None:
    """`unique (tenant_id, key)` ignora el soft-delete: antes el reintento tras un fallo
    chocaba con la fila borrada y quedaba en 409 in_flight para siempre."""
    from apps.api.db.queries import delete_idempotency_key, try_insert_idempotency_key

    async with pool.acquire() as conn:
        t, _, _ = await _seed_conversation(conn)
        first = await try_insert_idempotency_key(conn, tenant_id=t, key="k1", request_path="/p")
        assert first is not None
        assert (
            await try_insert_idempotency_key(conn, tenant_id=t, key="k1", request_path="/p") is None
        )

        await delete_idempotency_key(conn, tenant_id=t, key="k1")
        again = await try_insert_idempotency_key(conn, tenant_id=t, key="k1", request_path="/p")
        assert again is not None and again.status == "pending"

        await conn.execute("update idempotency_keys set expires_at = now() - interval '1 s'")
        assert await try_insert_idempotency_key(conn, tenant_id=t, key="k1", request_path="/p")


async def test_history_bound_hides_later_customer_messages_only(pool: asyncpg.Pool) -> None:
    """El turno de m1 no ve m2 (lo responde su propio turno), pero sí la respuesta del
    agente que salió mientras esperaba en cola (si no, vuelve a saludar)."""
    import json

    from apps.api.db.queries import get_recent_messages

    async with pool.acquire() as conn:
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )
        t, c, cu = await _seed_conversation(conn)
        _, m0 = await _enqueue(conn, t, c, cu)
        _, m1 = await _enqueue(conn, t, c, cu)
        _, m2 = await _enqueue(conn, t, c, cu)
        await conn.execute(
            "insert into messages (id, tenant_id, conversation_id, role, direction, content)"
            " values ($1, $2, $3, 'agent_ai', 'outbound', 'reply')",
            uuid.uuid4(),
            t,
            c,
        )
        bounded = await get_recent_messages(conn, t, c, limit=20, up_to_message_id=m1)
        assert [m.content for m in bounded] == [f"msg {m0}", f"msg {m1}", "reply"]
        full = await get_recent_messages(conn, t, c, limit=20)
        assert [m.content for m in full] == [f"msg {m0}", f"msg {m1}", f"msg {m2}", "reply"]


async def test_intake_lock_serializes_same_ticket(pool: asyncpg.Pool) -> None:
    """Dos intakes del mismo ticket: el segundo espera a que el primero confirme."""
    from apps.api.db.inbound_jobs import lock_inbound_intake

    tenant_id = uuid.uuid4()
    order: list[str] = []

    async def _intake(name: str, email: str, hold: float) -> None:
        async with pool.acquire() as conn, conn.transaction():
            await lock_inbound_intake(
                conn, tenant_id=tenant_id, channel="zendesk", external_id="7", customer_email=email
            )
            order.append(f"{name}:in")
            await asyncio.sleep(hold)
            order.append(f"{name}:out")

    first = asyncio.create_task(_intake("a", "X@test.com", 0.3))
    await asyncio.sleep(0.05)
    await asyncio.gather(first, _intake("b", "x@test.com", 0))
    assert order == ["a:in", "a:out", "b:in", "b:out"]
