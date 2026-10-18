"""Aprobar y rechazar L3 contra un Postgres REAL, con peticiones concurrentes (#376).

Los mocks no ven dos transacciones a la vez. Aquí cada test crea una base desechable
con todas las migraciones de `supabase/migrations/`, levanta el router de aprobaciones
sobre ella y aprueba con una skill falsa que cuenta sus mutaciones. Solo corren si
`AUYAN_TEST_DATABASE_URL` apunta a un Postgres desechable con pgvector, cuyo usuario
pueda crear bases. En CI (sin la variable) se saltan.

    AUYAN_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/postgres \\
        .venv/bin/pytest tests/test_approvals_pg.py
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
import pytest
from apps.api.core.config import get_settings
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id
from apps.api.db import client as db_client
from apps.api.routers.approvals import router as approvals_router
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from fastapi import FastAPI

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

DSN = os.environ.get("AUYAN_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="AUYAN_TEST_DATABASE_URL no configurada")

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"

# Lo que Supabase trae de serie y las migraciones dan por hecho.
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


class FakeL3Input(SkillInput):
    order_id: int


class FakeL3Output(SkillOutput):
    order_id: int
    mutations: int


class FakeL3(Skill):
    """L3 cuya mutación es un contador. `gate` la retiene a mitad para forzar solapes."""

    slug = "test.fake_l3"
    description = "L3 de prueba"
    tier: SkillTier = "L3"
    input_schema = FakeL3Input
    output_schema = FakeL3Output
    requires_idempotency = True
    default_threshold = 0.95

    mutations: ClassVar[int] = 0
    entered: ClassVar[asyncio.Event]
    gate: ClassVar[asyncio.Event]
    die_after_mutation: ClassVar[bool] = False

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, FakeL3Input)
        type(self).entered.set()
        await type(self).gate.wait()
        type(self).mutations += 1
        if type(self).die_after_mutation:
            raise ProcessDied
        return FakeL3Output(order_id=inputs.order_id, mutations=type(self).mutations)


class ProcessDied(BaseException):
    """La instancia muere a mitad de la petición: ningún `except Exception` lo ve."""


@pytest.fixture
def fake_skill(monkeypatch: pytest.MonkeyPatch) -> type[FakeL3]:
    monkeypatch.setitem(SkillRegistry._by_slug, FakeL3.slug, FakeL3)
    FakeL3.mutations = 0
    FakeL3.entered = asyncio.Event()
    FakeL3.gate = asyncio.Event()
    FakeL3.die_after_mutation = False
    return FakeL3


async def _apply_migrations(conn: asyncpg.Connection) -> None:
    has_pgcrypto = await conn.fetchval(
        "select exists(select 1 from pg_available_extensions where name = 'pgcrypto')"
    )
    await conn.execute(_SUPABASE_PRELUDE)
    for path in sorted(MIGRATIONS.glob("*.sql")):
        sql = path.read_text()
        if not has_pgcrypto:
            # Solo se usa gen_random_uuid(), nativo desde Postgres 13.
            sql = sql.replace("create extension if not exists pgcrypto;", "")
        await conn.execute(sql)


@pytest.fixture
async def pool(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[asyncpg.Pool]:
    import asyncpg

    admin = await asyncpg.connect(DSN)
    if not await admin.fetchval(
        "select exists(select 1 from pg_available_extensions where name = 'vector')"
    ):
        await admin.close()
        pytest.skip("el Postgres de pruebas no tiene pgvector")
    db = f"auyan_approvals_{uuid.uuid4().hex[:8]}"
    await admin.execute(f"create database {db}")
    await admin.close()

    dsn = str(httpx.URL(DSN).copy_with(path=f"/{db}"))
    setup = await asyncpg.connect(dsn)
    await _apply_migrations(setup)
    await setup.close()

    p = await asyncpg.create_pool(dsn, min_size=2, max_size=8, init=db_client._init_connection)
    monkeypatch.setattr(db_client, "_pool", p)
    monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
    for name in (
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_ANON_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "WEBHOOK_SECRET",
    ):
        monkeypatch.setenv(name, "test-not-used")
    monkeypatch.setenv("DATABASE_URL", dsn)
    get_settings.cache_clear()
    try:
        yield p
    finally:
        await p.close()
        get_settings.cache_clear()
        admin = await asyncpg.connect(DSN)
        await admin.execute(f"drop database {db} with (force)")
        await admin.close()


class Seeded:
    def __init__(self) -> None:
        self.tenant_id = uuid.uuid4()
        self.user_id = uuid.uuid4()
        self.conversation_id = uuid.uuid4()
        self.approval_id = uuid.uuid4()


async def _seed(pool: asyncpg.Pool) -> Seeded:
    s = Seeded()
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into tenants (id, slug, name) values ($1, $2, 'Tienda')",
            s.tenant_id,
            f"t-{s.tenant_id.hex[:8]}",
        )
        await conn.execute("insert into auth.users (id) values ($1)", s.user_id)
        await conn.execute(
            "insert into users (id, tenant_id, email, role)"
            " values ($1, $2, 'op@tienda.test', 'tenant_admin')",
            s.user_id,
            s.tenant_id,
        )
        customer_id = await conn.fetchval(
            "insert into end_customers (tenant_id) values ($1) returning id", s.tenant_id
        )
        await conn.execute(
            "insert into conversations (id, tenant_id, end_customer_id, channel, status)"
            " values ($1, $2, $3, 'chat', 'escalated')",
            s.conversation_id,
            s.tenant_id,
            customer_id,
        )
        await conn.execute(
            "insert into pending_approvals (id, tenant_id, conversation_id, skill_slug,"
            " skill_tier, inputs_raw, inputs_redacted, aop_slug, aop_version)"
            " values ($1, $2, $3, $4, 'L3', $5, $5, 'pruebas', 1)",
            s.approval_id,
            s.tenant_id,
            s.conversation_id,
            FakeL3.slug,
            {"order_id": 1001},
        )
        await conn.execute(
            "insert into escalations (tenant_id, conversation_id, reason) values ($1, $2, $3)",
            s.tenant_id,
            s.conversation_id,
            f"awaiting_human_approval:{s.approval_id}",
        )
    return s


def _client(s: Seeded) -> httpx.AsyncClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(approvals_router)
    auth = AuthContext(
        user_id=s.user_id, tenant_id=s.tenant_id, role="tenant_admin", email="op@tienda.test"
    )
    app.dependency_overrides[get_auth_context] = lambda: auth
    app.dependency_overrides[get_tenant_id] = lambda: s.tenant_id
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _approve(c: httpx.AsyncClient, s: Seeded) -> httpx.Response:
    return await c.post(f"/approvals/{s.approval_id}/approve", json={})


async def _reject(c: httpx.AsyncClient, s: Seeded) -> httpx.Response:
    return await c.post(f"/approvals/{s.approval_id}/reject", json={"comment": "no procede"})


async def _status(pool: asyncpg.Pool, s: Seeded) -> str:
    async with pool.acquire() as conn:
        return str(
            await conn.fetchval("select status from pending_approvals where id = $1", s.approval_id)
        )


async def _outcome_messages(pool: asyncpg.Pool, s: Seeded) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select metadata->>'execution_status' as status from messages"
            " where conversation_id = $1 and metadata ? 'approval_id' order by created_at",
            s.conversation_id,
        )
    return [r["status"] for r in rows]


async def _overlap(first: asyncio.Task[Any], skill: type[FakeL3]) -> None:
    """Espera a que la primera petición esté dentro de la mutación."""
    await asyncio.wait_for(skill.entered.wait(), timeout=5)
    assert not first.done()


async def test_two_concurrent_approvals_execute_the_skill_once(
    pool: asyncpg.Pool, fake_skill: type[FakeL3]
) -> None:
    s = await _seed(pool)
    async with _client(s) as c:
        first = asyncio.create_task(_approve(c, s))
        await _overlap(first, fake_skill)
        second = asyncio.create_task(_approve(c, s))
        await asyncio.sleep(0.3)
        fake_skill.gate.set()
        responses = await asyncio.gather(first, second)

    assert fake_skill.mutations == 1, "la L3 se ejecutó dos veces (doble reembolso)"
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert await _status(pool, s) == "approved"
    assert await _outcome_messages(pool, s) == ["success"]


async def test_reject_while_executing_is_refused_and_the_outcome_stays_truthful(
    pool: asyncpg.Pool, fake_skill: type[FakeL3]
) -> None:
    s = await _seed(pool)
    async with _client(s) as c:
        approve = asyncio.create_task(_approve(c, s))
        await _overlap(approve, fake_skill)
        rejected = await _reject(c, s)
        fake_skill.gate.set()
        approved = await approve

    assert rejected.status_code == 409
    assert approved.status_code == 200
    assert fake_skill.mutations == 1
    assert await _status(pool, s) == "approved"
    assert await _outcome_messages(pool, s) == ["success"]


async def test_approve_after_reject_never_executes(
    pool: asyncpg.Pool, fake_skill: type[FakeL3]
) -> None:
    s = await _seed(pool)
    fake_skill.gate.set()
    async with _client(s) as c:
        rejected, approved = await asyncio.gather(_reject(c, s), _approve(c, s))

    assert sorted([rejected.status_code, approved.status_code]) == [200, 409]
    status = await _status(pool, s)
    if status == "rejected":
        assert fake_skill.mutations == 0
        assert await _outcome_messages(pool, s) == ["rejected"]
    else:
        assert status == "approved"
        assert fake_skill.mutations == 1
        assert await _outcome_messages(pool, s) == ["success"]


async def test_death_after_the_mutation_does_not_allow_a_second_execution(
    pool: asyncpg.Pool, fake_skill: type[FakeL3]
) -> None:
    s = await _seed(pool)
    fake_skill.gate.set()
    fake_skill.die_after_mutation = True
    async with _client(s) as c:
        with pytest.raises(ProcessDied):
            await _approve(c, s)
        fake_skill.die_after_mutation = False
        retry = await _approve(c, s)

    assert fake_skill.mutations == 1, "el segundo clic volvió a ejecutar la L3"
    assert retry.status_code == 409
    assert await _status(pool, s) == "executing"
    assert await _outcome_messages(pool, s) == []
