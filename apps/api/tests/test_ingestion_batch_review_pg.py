"""Revisión por lotes de una ingesta contra un Postgres REAL (ADR 0015 §3 y §5, PR 4).

Aprobar un lote, rechazar lo excluido, repetir la llamada y auto-aprobar la demo dependen de SQL
(`FOR UPDATE`, transacción por submission, metadata jsonb). Solo corren con
`AUYAN_TEST_DATABASE_URL`; sin ella se saltan.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from apps.api.db.client import tenant_scope
from apps.api.db.kb_confirmation import confirm_kb_documents
from apps.api.db.queries import create_tenant_knowledge_submission
from apps.api.db.site_ingestions import (
    claim_next_site_ingestion,
    enqueue_site_ingestion,
    get_latest_site_ingestion,
)
from apps.api.routers import site_ingestions as router
from apps.api.routers.site_ingestions import IngestionApprove
from apps.api.services.kb_approval import approve_submissions_batch
from apps.api.services.site_ingestion.auto_approve import DEMO_REVIEW_NOTE
from apps.api.services.site_ingestion.worker import SiteIngestionWorker
from apps.api.tests.pg_support import migrated_pool, requires_pg
from apps.api.tests.site_ingestion_replay import Replay

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

pytestmark = requires_pg

REVIEWER = uuid.uuid4()
DIM = 1536


class FakeEmbedder:
    """Embedder sin red. Falla si algún texto contiene la marca `BOOM`."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(len(texts))
        if any("BOOM" in text for text in texts):
            raise RuntimeError("embeddings caídos")
        return [[1.0] + [0.0] * (DIM - 1) for _ in texts]


@pytest.fixture
async def pool(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[asyncpg.Pool]:
    async with migrated_pool(monkeypatch) as p:
        async with p.acquire() as conn:
            await conn.execute(
                "insert into auth.users (id) values ($1) on conflict do nothing", REVIEWER
            )
        yield p


async def _tenant(pool: asyncpg.Pool, origin: str = "client") -> uuid.UUID:
    tid = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into tenants (id, slug, name, origin, demo_expires_at)"
            " values ($1, $2, 'Tienda', $3, case when $3 = 'demo' then now() + interval '30 days' end)",
            tid,
            f"t-{tid.hex[:8]}",
            origin,
        )
    return tid


async def _ingestion_with_submissions(
    pool: asyncpg.Pool, tid: uuid.UUID, contents: list[str]
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    async with pool.acquire() as conn:
        ingestion_id = await enqueue_site_ingestion(
            conn, tenant_id=tid, root_url="https://tienda.test", requested_by=None
        )
    assert ingestion_id is not None
    async with pool.acquire() as conn:
        await conn.execute(
            "update site_ingestions set status = 'ready', finished_at = now() where id = $1",
            ingestion_id,
        )
    ids: list[uuid.UUID] = []
    async with tenant_scope(tid) as conn:
        for index, content in enumerate(contents):
            sub = await create_tenant_knowledge_submission(
                conn,
                tid,
                title=f"Fuente {index}",
                source_type="url",
                source_url=f"https://tienda.test/pages/p{index}",
                content=content,
                metadata={"kind": "shop_page", "priority": "normal", "words": 5},
                ingestion_id=ingestion_id,
            )
            ids.append(sub.id)
    return ingestion_id, ids


async def _statuses(pool: asyncpg.Pool, tid: uuid.UUID) -> dict[str, str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select title, status::text from tenant_knowledge_submissions where tenant_id = $1",
            tid,
        )
    return {r["title"]: r["status"] for r in rows}


async def _live_docs(pool: asyncpg.Pool, tid: uuid.UUID) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "select id, title, metadata->>'confirmation' as confirmation,"
            " (select count(*) from knowledge_base_chunks c"
            "   where c.document_id = d.id and c.deleted_at is null) as chunks"
            " from knowledge_base_documents d"
            " where tenant_id = $1 and deleted_at is null order by title",
            tid,
        )


def _request(embedder: FakeEmbedder, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setattr(router, "make_embedder", lambda *_a, **_k: embedder)
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace())
    state = SimpleNamespace(agent_deps=SimpleNamespace(openai=object()))
    return SimpleNamespace(app=SimpleNamespace(state=state))


async def test_the_batch_approves_all_but_the_excluded_ones_and_rejects_them(
    pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid = await _tenant(pool)
    ingestion_id, ids = await _ingestion_with_submissions(
        pool, tid, [f"Contenido útil número {i}." for i in range(5)]
    )
    embedder = FakeEmbedder()

    out = await router.approve_site_ingestion(
        ingestion_id,
        IngestionApprove(exclude_submission_ids=[ids[3]], review_note="Sin la de ofertas"),
        _request(embedder, monkeypatch),
        tid,
        SimpleNamespace(user_id=REVIEWER),
    )

    assert out.counts.model_dump() == {"approved": 4, "rejected": 1, "skipped": 0}
    assert out.failures == []
    assert await _statuses(pool, tid) == {
        "Fuente 0": "approved",
        "Fuente 1": "approved",
        "Fuente 2": "approved",
        "Fuente 3": "rejected",
        "Fuente 4": "approved",
    }
    docs = await _live_docs(pool, tid)
    assert [(d["title"], d["confirmation"], d["chunks"]) for d in docs] == [
        ("Fuente 0", "confirmed", 1),
        ("Fuente 1", "confirmed", 1),
        ("Fuente 2", "confirmed", 1),
        ("Fuente 4", "confirmed", 1),
    ]
    assert embedder.calls == [4]


async def test_calling_the_batch_again_only_touches_what_is_still_pending(
    pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid = await _tenant(pool)
    ingestion_id, ids = await _ingestion_with_submissions(
        pool, tid, ["Contenido uno.", "Contenido dos.", "Contenido tres."]
    )
    embedder = FakeEmbedder()
    request = _request(embedder, monkeypatch)
    body = IngestionApprove(exclude_submission_ids=[ids[2]])
    auth = SimpleNamespace(user_id=REVIEWER)

    first = await router.approve_site_ingestion(ingestion_id, body, request, tid, auth)
    second = await router.approve_site_ingestion(ingestion_id, body, request, tid, auth)

    assert first.counts.model_dump() == {"approved": 2, "rejected": 1, "skipped": 0}
    assert second.counts.model_dump() == {"approved": 0, "rejected": 0, "skipped": 3}
    assert len(await _live_docs(pool, tid)) == 2
    assert embedder.calls == [2]


async def test_one_failing_embedding_is_reported_and_the_rest_are_approved(
    pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid = await _tenant(pool)
    ingestion_id, ids = await _ingestion_with_submissions(
        pool, tid, ["Contenido uno.", "Esto es BOOM.", "Contenido tres."]
    )
    embedder = FakeEmbedder()
    request = _request(embedder, monkeypatch)
    auth = SimpleNamespace(user_id=REVIEWER)

    out = await router.approve_site_ingestion(ingestion_id, IngestionApprove(), request, tid, auth)

    assert out.counts.model_dump() == {"approved": 2, "rejected": 0, "skipped": 0}
    assert [(f.submission_id, f.code) for f in out.failures] == [(ids[1], "embedding_failed")]
    assert await _statuses(pool, tid) == {
        "Fuente 0": "approved",
        "Fuente 1": "pending_review",
        "Fuente 2": "approved",
    }

    retry = await router.approve_site_ingestion(
        ingestion_id, IngestionApprove(), request, tid, auth
    )
    assert retry.counts.approved == 0
    assert [f.code for f in retry.failures] == ["embedding_failed"]


async def test_a_submission_without_indexable_content_fails_alone(pool: asyncpg.Pool) -> None:
    tid = await _tenant(pool)
    _, ids = await _ingestion_with_submissions(
        pool, tid, ["https://tienda.test/pages/p0", "Contenido bueno."]
    )

    result = await approve_submissions_batch(
        tenant_id=tid,
        submission_ids=ids,
        reviewed_by=REVIEWER,
        review_note=None,
        confirmation="confirmed",
        embedder=FakeEmbedder(),
    )

    assert [s.id for s in result.approved] == [ids[1]]
    assert [(f.submission_id, f.code.value) for f in result.failures] == [(ids[0], "no_content")]


async def _run_ingestion(pool: asyncpg.Pool, tid: uuid.UUID, embedder: FakeEmbedder) -> uuid.UUID:
    async with pool.acquire() as conn:
        await enqueue_site_ingestion(
            conn, tenant_id=tid, root_url="https://thinkingmu.com", requested_by=None
        )
        job = await claim_next_site_ingestion(conn, lease_seconds=60)
    assert job is not None
    worker = SiteIngestionWorker(
        concurrency=0,
        transport=Replay(("thinkingmu",)).transport(),
        embedder=embedder,
    )
    await worker.execute(job)
    return job.id


async def test_a_ready_demo_ingestion_goes_live_unconfirmed(pool: asyncpg.Pool) -> None:
    tid = await _tenant(pool, origin="demo")

    await _run_ingestion(pool, tid, FakeEmbedder())

    docs = await _live_docs(pool, tid)
    assert len(docs) == 7
    assert {d["confirmation"] for d in docs} == {"unconfirmed"}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select status::text, reviewed_by, review_note"
            " from tenant_knowledge_submissions where tenant_id = $1",
            tid,
        )
    assert {(r["status"], r["reviewed_by"], r["review_note"]) for r in rows} == {
        ("approved", None, DEMO_REVIEW_NOTE)
    }


async def test_a_ready_client_ingestion_stays_pending(pool: asyncpg.Pool) -> None:
    tid = await _tenant(pool, origin="client")
    embedder = FakeEmbedder()

    await _run_ingestion(pool, tid, embedder)

    assert set((await _statuses(pool, tid)).values()) == {"pending_review"}
    assert await _live_docs(pool, tid) == []
    assert embedder.calls == []


async def test_confirm_flips_only_unconfirmed_documents_of_that_tenant(
    pool: asyncpg.Pool,
) -> None:
    demo, other = await _tenant(pool, origin="demo"), await _tenant(pool, origin="demo")
    for tid in (demo, other):
        _, ids = await _ingestion_with_submissions(pool, tid, ["Contenido uno.", "Contenido dos."])
        await approve_submissions_batch(
            tenant_id=tid,
            submission_ids=ids,
            reviewed_by=None,
            review_note=DEMO_REVIEW_NOTE,
            confirmation="unconfirmed",
            embedder=FakeEmbedder(),
        )
    demo_docs = [d["id"] for d in await _live_docs(pool, demo)]
    other_docs = [d["id"] for d in await _live_docs(pool, other)]

    async with tenant_scope(demo) as conn:
        flipped = await confirm_kb_documents(conn, demo, demo_docs[:1] + other_docs, REVIEWER)
        again = await confirm_kb_documents(conn, demo, demo_docs[:1], REVIEWER)

    assert (flipped, again) == (1, 0)
    assert [d["confirmation"] for d in await _live_docs(pool, demo)] == [
        "confirmed",
        "unconfirmed",
    ]
    assert {d["confirmation"] for d in await _live_docs(pool, other)} == {"unconfirmed"}


async def test_the_latest_ingestion_is_the_active_one_then_the_last_that_left_sources(
    pool: asyncpg.Pool,
) -> None:
    tid = await _tenant(pool)
    with_sources, _ = await _ingestion_with_submissions(pool, tid, ["Contenido uno."])
    async with pool.acquire() as conn:
        empty = await enqueue_site_ingestion(
            conn, tenant_id=tid, root_url="https://tienda.test", requested_by=None
        )
        assert empty is not None
        await conn.execute("update site_ingestions set status = 'ready' where id = $1", empty)
        shown = await get_latest_site_ingestion(conn, tid)
        running = await enqueue_site_ingestion(
            conn, tenant_id=tid, root_url="https://tienda.test", requested_by=None
        )
        shown_while_running = await get_latest_site_ingestion(conn, tid)

    assert shown is not None and shown.id == with_sources
    assert shown_while_running is not None and shown_while_running.id == running


async def _name_of(pool: asyncpg.Pool, tid: uuid.UUID) -> str:
    async with pool.acquire() as conn:
        return str(await conn.fetchval("select name from tenants where id = $1", tid))


async def _set_name(pool: asyncpg.Pool, tid: uuid.UUID, name: str, source_url: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "update tenants set name = $2, demo_source_url = $3 where id = $1",
            tid,
            name,
            source_url,
        )


async def test_a_ready_demo_takes_the_official_shop_name(pool: asyncpg.Pool) -> None:
    tid = await _tenant(pool, origin="demo")
    await _set_name(pool, tid, "Thinkingmu", "https://thinkingmu.com")

    await _run_ingestion(pool, tid, FakeEmbedder())

    assert await _name_of(pool, tid) == "Thinking MU"


async def test_a_ready_demo_with_an_edited_name_keeps_it(pool: asyncpg.Pool) -> None:
    tid = await _tenant(pool, origin="demo")
    await _set_name(pool, tid, "Demo para Laura", "https://thinkingmu.com")

    await _run_ingestion(pool, tid, FakeEmbedder())

    assert await _name_of(pool, tid) == "Demo para Laura"


async def test_a_ready_client_keeps_its_name(pool: asyncpg.Pool) -> None:
    tid = await _tenant(pool, origin="client")
    await _set_name(pool, tid, "Thinkingmu", "https://thinkingmu.com")

    await _run_ingestion(pool, tid, FakeEmbedder())

    assert await _name_of(pool, tid) == "Thinkingmu"
