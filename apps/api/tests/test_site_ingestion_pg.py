from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import httpx
import pytest
from apps.api.db.client import tenant_scope
from apps.api.db.queries import approve_tenant_knowledge_submission_with_document
from apps.api.db.site_ingestions import (
    LeaseLost,
    claim_next_site_ingestion,
    enqueue_site_ingestion,
    extend_site_ingestion_lease,
    fail_site_ingestion,
    transition_site_ingestion,
)
from apps.api.services.site_ingestion.models import IngestionStatus
from apps.api.services.site_ingestion.orchestrator import run_ingestion
from apps.api.services.site_ingestion.worker import SiteIngestionWorker
from apps.api.tests.pg_support import migrated_pool, requires_pg
from apps.api.tests.site_ingestion_replay import Replay, SleepLog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

pytestmark = requires_pg

THINKINGMU_KEYS = [
    "thinkingmu.com",
    "thinkingmu.com/pages/cambios-devoluciones",
    "thinkingmu.com/pages/envios-costes",
    "thinkingmu.com/policies/refund-policy",
    "thinkingmu.com/policies/shipping-policy",
    "thinkingmu.com/policies/subscription-policy",
    "thinkingmu.com/policies/terms-of-service",
]


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
    return tid


async def _enqueue(pool: asyncpg.Pool, tid: uuid.UUID, url: str = "https://thinkingmu.com"):
    async with pool.acquire() as conn:
        return await enqueue_site_ingestion(conn, tenant_id=tid, root_url=url, requested_by=None)


async def _claim(pool: asyncpg.Pool, lease_seconds: int = 60):
    async with pool.acquire() as conn:
        return await claim_next_site_ingestion(conn, lease_seconds=lease_seconds)


async def _row(pool: asyncpg.Pool, ingestion_id: uuid.UUID) -> asyncpg.Record:
    async with pool.acquire() as conn:
        return await conn.fetchrow("select * from site_ingestions where id = $1", ingestion_id)


async def _expire_lease(pool: asyncpg.Pool, ingestion_id: uuid.UUID) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "update site_ingestions set locked_until = now() - interval '1 second' where id = $1",
            ingestion_id,
        )


async def test_only_one_unfinished_ingestion_per_tenant(pool: asyncpg.Pool) -> None:
    tid, other = await _tenant(pool), await _tenant(pool)

    first = await _enqueue(pool, tid)
    second = await _enqueue(pool, tid)
    other_tenant = await _enqueue(pool, other)
    job = await _claim(pool)
    assert job is not None and job.id == first
    async with pool.acquire() as conn:
        await transition_site_ingestion(conn, job, IngestionStatus.EXTRACTING)
        await transition_site_ingestion(conn, job, IngestionStatus.READY)
    after_ready = await _enqueue(pool, tid)

    assert first is not None
    assert second is None
    assert other_tenant is not None
    assert after_ready is not None and after_ready != first


async def test_expired_lease_is_reclaimed_and_the_old_worker_can_no_longer_write(
    pool: asyncpg.Pool,
) -> None:
    tid = await _tenant(pool)
    ingestion_id = await _enqueue(pool, tid)

    old = await _claim(pool)
    while_alive = await _claim(pool)
    assert old is not None
    await _expire_lease(pool, old.id)
    new = await _claim(pool)
    assert new is not None
    async with pool.acquire() as conn:
        old_heartbeat = await extend_site_ingestion_lease(conn, old, lease_seconds=60)
        with pytest.raises(LeaseLost):
            await transition_site_ingestion(conn, old, IngestionStatus.EXTRACTING)
        await transition_site_ingestion(conn, new, IngestionStatus.EXTRACTING)

    assert while_alive is None
    assert (old.id, old.attempts) == (ingestion_id, 1)
    assert (new.id, new.attempts) == (ingestion_id, 2)
    assert old_heartbeat is False
    row = await _row(pool, ingestion_id)
    assert (row["status"], row["attempts"]) == ("extracting", 2)


async def test_a_lease_that_expires_after_the_last_attempt_fails(pool: asyncpg.Pool) -> None:
    tid = await _tenant(pool)
    ingestion_id = await _enqueue(pool, tid)
    async with pool.acquire() as conn:
        await conn.execute(
            "update site_ingestions set max_attempts = 1 where id = $1", ingestion_id
        )
    job = await _claim(pool)
    assert job is not None
    await _expire_lease(pool, ingestion_id)

    reclaimed = await _claim(pool)

    row = await _row(pool, ingestion_id)
    assert reclaimed is None
    assert row["status"] == "failed"
    assert row["failure_reason"] == "lease_expired: agotó sus intentos sin terminar"


async def test_a_failure_retries_with_backoff_until_max_attempts(pool: asyncpg.Pool) -> None:
    tid = await _tenant(pool)
    ingestion_id = await _enqueue(pool, tid)
    async with pool.acquire() as conn:
        await conn.execute(
            "update site_ingestions set max_attempts = 2 where id = $1", ingestion_id
        )

    first = await _claim(pool)
    assert first is not None
    async with pool.acquire() as conn:
        after_first = await fail_site_ingestion(conn, first, reason="boom 1", retry_in_seconds=60)
    not_yet = await _claim(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            "update site_ingestions set run_after = now() where id = $1", ingestion_id
        )
    second = await _claim(pool)
    assert second is not None
    async with pool.acquire() as conn:
        after_second = await fail_site_ingestion(conn, second, reason="boom 2", retry_in_seconds=60)

    assert after_first is IngestionStatus.QUEUED
    assert not_yet is None
    assert after_second is IngestionStatus.FAILED
    row = await _row(pool, ingestion_id)
    assert (row["status"], row["failure_reason"], row["locked_until"]) == ("failed", "boom 2", None)


async def _submissions(pool: asyncpg.Pool, tid: uuid.UUID) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "select id, source_key, status::text, ingestion_id, content"
            " from tenant_knowledge_submissions where tenant_id = $1 order by source_key, created_at",
            tid,
        )


async def _ingest(pool: asyncpg.Pool, tid: uuid.UUID, replay: Replay) -> tuple:
    await _enqueue(pool, tid)
    job = await _claim(pool)
    assert job is not None
    stats = await run_ingestion(job, transport=replay.transport(), sleep=SleepLog())
    return job, stats


async def test_ingestion_creates_pending_submissions_and_reingesting_creates_nothing(
    pool: asyncpg.Pool,
) -> None:
    tid = await _tenant(pool)

    first_job, first = await _ingest(pool, tid, Replay(("thinkingmu",)))
    _, second = await _ingest(pool, tid, Replay(("thinkingmu",)))

    rows = await _submissions(pool, tid)
    assert [r["source_key"] for r in rows] == THINKINGMU_KEYS
    assert {r["status"] for r in rows} == {"pending_review"}
    assert {r["ingestion_id"] for r in rows} == {first_job.id}
    assert (first.created, second.created) == (7, 0)
    assert second.sources["storefront_api"].discarded["already_pending"] == 7
    row = await _row(pool, first_job.id)
    stats = json.loads(row["stats"]) if isinstance(row["stats"], str) else row["stats"]
    assert (row["status"], row["platform"], row["locked_until"]) == ("ready", "shopify", None)
    assert (stats["docs"], stats["created"], stats["requests"]) == (7, 7, 30)
    assert stats["sources"]["html"]["abandoned"] == "rate_limited: retry_after=60s"


async def test_reingesting_skips_the_live_document_and_proposes_only_what_changed(
    pool: asyncpg.Pool,
) -> None:
    tid = await _tenant(pool)
    await _ingest(pool, tid, Replay(("thinkingmu",)))
    refund = next(
        r for r in await _submissions(pool, tid) if r["source_key"].endswith("/refund-policy")
    )
    async with tenant_scope(tid) as conn:
        approved = await approve_tenant_knowledge_submission_with_document(
            conn,
            tid,
            refund["id"],
            reviewed_by=None,
            review_note=None,
            chunks=[("x", [1.0] + [0.0] * 1535)],
        )
    assert approved is not None

    def changed_shipping_policy(request: httpx.Request) -> httpx.Response | None:
        if b"AuyanStoreContent" not in request.content:
            return None
        recorded = Replay(("thinkingmu",))
        original = recorded.transport().handle_request(request)
        data = json.loads(original.read())
        data["data"]["shop"]["shippingPolicy"]["body"] += "<p>Nuevo: envío a Andorra en 48 h.</p>"
        return httpx.Response(200, json=data)

    second_job, second = await _ingest(
        pool, tid, Replay(("thinkingmu",), overrides=[changed_shipping_policy])
    )

    rows = await _submissions(pool, tid)
    new_rows = [r for r in rows if r["ingestion_id"] == second_job.id]
    assert second.created == 1
    assert [r["source_key"] for r in new_rows] == ["thinkingmu.com/policies/shipping-policy"]
    assert "Nuevo: envío a Andorra en 48 h." in new_rows[0]["content"]
    discarded = second.sources["storefront_api"].discarded
    assert (discarded["unchanged"], discarded["already_pending"]) == (1, 5)
    statuses = {
        (r["source_key"], r["status"]) for r in rows if r["source_key"].endswith("/shipping-policy")
    }
    assert statuses == {
        ("thinkingmu.com/policies/shipping-policy", "superseded"),
        ("thinkingmu.com/policies/shipping-policy", "pending_review"),
    }


async def test_a_store_that_serves_nothing_fails_without_retrying(pool: asyncpg.Pool) -> None:
    tid = await _tenant(pool)
    ingestion_id = await _enqueue(pool, tid, "https://mimitos.es")
    job = await _claim(pool)
    assert job is not None

    def robots_down(request: httpx.Request) -> httpx.Response | None:
        return httpx.Response(503) if request.url.path == "/robots.txt" else None

    worker = SiteIngestionWorker(
        concurrency=0, transport=Replay(("mimitos",), overrides=[robots_down]).transport()
    )
    await worker.execute(job)

    row = await _row(pool, ingestion_id)
    assert row["status"] == "failed"
    assert row["failure_reason"] == (
        "no_content: robots=unavailable, storefront_api=0req, agent_files=0req, html=0req"
    )
    assert await _submissions(pool, tid) == []
