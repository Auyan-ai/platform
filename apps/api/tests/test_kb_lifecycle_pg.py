"""Ciclo de vida de la KB contra un Postgres REAL (ADR 0015 §3, PR 1).

Sustituir una fuente, borrar un documento, buscar y el gate `has_knowledge` dependen de SQL
(índice único parcial, `FOR UPDATE`, filtros del escaneo vectorial), que los mocks no ven.
Solo corren si `AUYAN_TEST_DATABASE_URL` apunta a un Postgres desechable con pgvector cuyo
usuario pueda crear bases. En CI (sin la variable) se saltan.

    AUYAN_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/postgres \\
        .venv/bin/pytest tests/test_kb_lifecycle_pg.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    approve_tenant_knowledge_submission_with_document,
    compute_onboarding_checklist,
    create_tenant_knowledge_submission,
    list_knowledge_documents,
    reject_tenant_knowledge_submission,
    search_knowledge_chunks,
    soft_delete_knowledge_document,
)
from apps.api.services.kb_source_key import canonical_source_key
from apps.api.tests.pg_support import (
    MIGRATIONS,
    apply_migrations,
    create_migrated_database,
    drop_database,
    migrated_pool,
    requires_pg,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

pytestmark = requires_pg

LIFECYCLE_MIGRATION = "20261025000001_kb_document_lifecycle.sql"

DIM = 1536
REVIEWER = uuid.uuid4()


def _vec(axis: int) -> list[float]:
    v = [0.0] * DIM
    v[axis] = 1.0
    return v


@pytest.fixture
async def pool(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[asyncpg.Pool]:
    async with migrated_pool(monkeypatch) as p:
        yield p


async def _tenant(pool: asyncpg.Pool) -> uuid.UUID:
    tid = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into tenants (id, slug, name) values ($1, $2, 'Tienda')",
            tid,
            f"t-{tid.hex[:8]}",
        )
        await conn.execute(
            "insert into auth.users (id) values ($1) on conflict do nothing", REVIEWER
        )
    return tid


async def _submit_and_approve(
    tid: uuid.UUID,
    *,
    url: str | None,
    content: str,
    axis: int,
) -> uuid.UUID:
    async with tenant_scope(tid) as conn:
        sub = await create_tenant_knowledge_submission(
            conn,
            tid,
            title=f"Doc {axis}",
            source_type="url" if url else "text",
            source_url=url,
            content=content,
        )
        approved = await approve_tenant_knowledge_submission_with_document(
            conn,
            tid,
            sub.id,
            reviewed_by=REVIEWER,
            review_note=None,
            chunks=[(content, _vec(axis))],
        )
    assert approved is not None
    assert approved.processed_document_id is not None
    return approved.processed_document_id


async def _live_docs(pool: asyncpg.Pool, tid: uuid.UUID) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "select id, source_key from knowledge_base_documents"
            " where tenant_id = $1 and deleted_at is null",
            tid,
        )


async def test_two_approvals_of_the_same_source_leave_one_live_document(
    pool: asyncpg.Pool,
) -> None:
    tid = await _tenant(pool)

    first = await _submit_and_approve(
        tid, url="https://www.tienda.com/envios/", content="envíos en 3 días", axis=0
    )
    second = await _submit_and_approve(
        tid, url="http://tienda.com/envios?utm=x", content="envíos en 5 días", axis=1
    )

    live = await _live_docs(pool, tid)
    assert [r["id"] for r in live] == [second]
    assert live[0]["source_key"] == "tienda.com/envios"
    async with pool.acquire() as conn:
        old_live_chunks = await conn.fetchval(
            "select count(*) from knowledge_base_chunks"
            " where document_id = $1 and deleted_at is null",
            first,
        )
    assert old_live_chunks == 0


async def test_text_submissions_without_url_never_replace_each_other(
    pool: asyncpg.Pool,
) -> None:
    tid = await _tenant(pool)

    await _submit_and_approve(tid, url=None, content="política A", axis=0)
    await _submit_and_approve(tid, url=None, content="política B", axis=1)

    assert len(await _live_docs(pool, tid)) == 2


async def test_unique_index_refuses_two_live_documents_with_the_same_key(
    pool: asyncpg.Pool,
) -> None:
    import asyncpg

    tid = await _tenant(pool)
    await _submit_and_approve(tid, url="https://tienda.com/a", content="uno", axis=0)

    with pytest.raises(asyncpg.UniqueViolationError):
        async with pool.acquire() as conn:
            await conn.execute(
                "insert into knowledge_base_documents (tenant_id, title, content, source_key)"
                " values ($1, 'dup', 'x', 'tienda.com/a')",
                tid,
            )


async def test_a_newer_pending_submission_supersedes_the_older_pending_one(
    pool: asyncpg.Pool,
) -> None:
    tid = await _tenant(pool)
    async with tenant_scope(tid) as conn:
        old = await create_tenant_knowledge_submission(
            conn, tid, title="v1", source_type="url", source_url="https://tienda.com/faq"
        )
        new = await create_tenant_knowledge_submission(
            conn, tid, title="v2", source_type="url", source_url="https://www.tienda.com/faq/"
        )
        other = await create_tenant_knowledge_submission(
            conn, tid, title="otra", source_type="url", source_url="https://tienda.com/otra"
        )
        approved_old = await approve_tenant_knowledge_submission_with_document(
            conn, tid, old.id, reviewed_by=REVIEWER, review_note=None, chunks=[("x", _vec(0))]
        )
        statuses = {
            r["id"]: r["status"]
            for r in await conn.fetch(
                "select id, status::text from tenant_knowledge_submissions where tenant_id = $1",
                tid,
            )
        }

    assert approved_old is None
    assert statuses[old.id] == "superseded"
    assert statuses[new.id] == "pending_review"
    assert statuses[other.id] == "pending_review"


async def test_chunks_of_a_deleted_document_never_come_back_from_search(
    pool: asyncpg.Pool,
) -> None:
    tid = await _tenant(pool)
    doomed = await _submit_and_approve(tid, url=None, content="plazo de 30 días", axis=0)
    survivor = await _submit_and_approve(tid, url=None, content="plazo de 10 días", axis=1)

    async with tenant_scope(tid) as conn:
        before = await search_knowledge_chunks(conn, tid, _vec(0), top_k=1, min_similarity=-1.0)
        assert [c.document_id for c in before] == [doomed]
        assert await soft_delete_knowledge_document(conn, tid, doomed) is True
        after = await search_knowledge_chunks(conn, tid, _vec(0), top_k=1, min_similarity=-1.0)
        again = await soft_delete_knowledge_document(conn, tid, doomed)

    assert [c.document_id for c in after] == [survivor]
    assert again is False


async def test_search_keeps_the_min_similarity_cutoff(pool: asyncpg.Pool) -> None:
    tid = await _tenant(pool)
    await _submit_and_approve(tid, url=None, content="algo", axis=1)

    async with tenant_scope(tid) as conn:
        found = await search_knowledge_chunks(conn, tid, _vec(0), top_k=5, min_similarity=0.6)

    assert found == []


async def test_deleting_one_tenants_document_id_from_another_tenant_does_nothing(
    pool: asyncpg.Pool,
) -> None:
    mine = await _tenant(pool)
    other = await _tenant(pool)
    doc = await _submit_and_approve(mine, url=None, content="mío", axis=0)

    async with tenant_scope(other) as conn:
        deleted = await soft_delete_knowledge_document(conn, other, doc)
    async with tenant_scope(mine) as conn:
        docs = await list_knowledge_documents(conn, mine)

    assert deleted is False
    assert [(d.id, d.chunk_count) for d in docs] == [(doc, 1)]


async def test_only_an_approved_submission_satisfies_has_knowledge(pool: asyncpg.Pool) -> None:
    tid = await _tenant(pool)
    async with tenant_scope(tid) as conn:
        sub = await create_tenant_knowledge_submission(
            conn, tid, title="FAQ", source_type="text", content="algo"
        )
        pending = (await compute_onboarding_checklist(conn, tid)).has_knowledge
        rejected = await reject_tenant_knowledge_submission(conn, tid, sub.id, reviewed_by=REVIEWER)
        after_reject = (await compute_onboarding_checklist(conn, tid)).has_knowledge
    await _submit_and_approve(tid, url=None, content="otra", axis=0)
    async with tenant_scope(tid) as conn:
        after_approve = (await compute_onboarding_checklist(conn, tid)).has_knowledge

    assert rejected is not None
    assert (pending, after_reject, after_approve) == (False, False, True)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.Tienda.com/Politica/?a=1#x",
        "http://tienda.com",
        "tienda.com/faq//",
        "https://tienda.com?x=1",
        "HTTPS://WWW.TIENDA.COM:8080/a/b/",
    ],
)
async def test_sql_and_python_canonical_keys_agree(pool: asyncpg.Pool, url: str) -> None:
    async with pool.acquire() as conn:
        sql_key = await conn.fetchval("select kb_canonical_source_key($1)", url)

    assert sql_key == canonical_source_key(url)


async def test_migration_keeps_the_newest_live_duplicate_and_soft_deletes_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, _dsn, conn = await create_migrated_database(stop_before=LIFECYCLE_MIGRATION)
    try:
        tid = uuid.uuid4()
        await conn.execute("insert into tenants (id, slug, name) values ($1, 'dup', 'Tienda')", tid)

        async def doc(source: str | None, created: str) -> uuid.UUID:
            did = uuid.uuid4()
            await conn.execute(
                "insert into knowledge_base_documents"
                " (id, tenant_id, title, source, content, created_at)"
                " values ($1, $2, 't', $3, 'c', $4::timestamptz)",
                did,
                tid,
                source,
                datetime.fromisoformat(created).replace(tzinfo=UTC),
            )
            await conn.execute(
                "insert into knowledge_base_chunks"
                " (tenant_id, document_id, chunk_index, content, embedding)"
                " values ($1, $2, 0, 'c', $3::vector)",
                tid,
                did,
                "[" + ",".join(["0"] * DIM) + "]",
            )
            return did

        oldest = await doc("https://www.tienda.com/envios/", "2026-01-01")
        newest = await doc("http://tienda.com/envios?x=1", "2026-03-01")
        middle = await doc("https://tienda.com/envios#a", "2026-02-01")
        other = await doc("https://tienda.com/otra", "2026-01-01")
        plain = await doc("manual", "2026-01-01")

        await apply_migrations(conn, [MIGRATIONS / LIFECYCLE_MIGRATION])

        rows = {
            r["id"]: r
            for r in await conn.fetch(
                "select id, source_key, deleted_at is not null as dead,"
                " (select count(*) from knowledge_base_chunks c"
                "   where c.document_id = d.id and c.deleted_at is null) as live_chunks"
                " from knowledge_base_documents d where tenant_id = $1",
                tid,
            )
        }
    finally:
        await conn.close()
        await drop_database(db)

    assert [rows[i]["dead"] for i in (oldest, middle, newest)] == [True, True, False]
    assert [rows[i]["live_chunks"] for i in (oldest, middle, newest)] == [0, 0, 1]
    assert rows[newest]["source_key"] == "tienda.com/envios"
    assert rows[other]["source_key"] == "tienda.com/otra"
    assert rows[plain]["source_key"] is None
    assert rows[plain]["dead"] is False
