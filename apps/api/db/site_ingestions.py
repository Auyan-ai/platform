from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apps.api.services.kb_source_key import content_sha256
from apps.api.services.site_ingestion.models import (
    ACTIVE_STATUSES,
    TRANSITIONS,
    IngestionStatus,
    Platform,
    predecessors_of,
)

if TYPE_CHECKING:
    import asyncpg

_ACTIVE = sorted(s.value for s in ACTIVE_STATUSES)
_RUNNING = sorted(s.value for s in ACTIVE_STATUSES if s is not IngestionStatus.QUEUED)


class LeaseLost(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaimedIngestion:
    id: UUID
    tenant_id: UUID
    root_url: str
    attempts: int
    max_attempts: int
    requested_by: UUID | None


@dataclass(frozen=True)
class SiteIngestion:
    id: UUID
    tenant_id: UUID
    root_url: str
    platform: Platform | None
    status: IngestionStatus
    attempts: int
    failure_reason: str | None
    stats: dict[str, Any]
    cost_usd: float
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class KnownContent:
    source_key: str
    sha256: str
    pending: bool


def _ingestion_from_row(row: asyncpg.Record) -> SiteIngestion:
    stats = row["stats"]
    if isinstance(stats, str):
        stats = json.loads(stats)
    return SiteIngestion(
        id=row["id"],
        tenant_id=row["tenant_id"],
        root_url=row["root_url"],
        platform=Platform(row["platform"]) if row["platform"] else None,
        status=IngestionStatus(row["status"]),
        attempts=row["attempts"],
        failure_reason=row["failure_reason"],
        stats=stats or {},
        cost_usd=float(row["cost_usd"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


async def enqueue_site_ingestion(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    root_url: str,
    requested_by: UUID | None,
) -> UUID | None:
    row = await conn.fetchrow(
        """
        INSERT INTO site_ingestions (tenant_id, root_url, requested_by)
        VALUES ($1, $2, $3)
        ON CONFLICT (tenant_id)
          WHERE deleted_at IS NULL AND status IN ('queued', 'fetching', 'extracting')
          DO NOTHING
        RETURNING id
        """,
        tenant_id,
        root_url,
        requested_by,
    )
    return row["id"] if row else None


async def get_active_site_ingestion(
    conn: asyncpg.Connection, tenant_id: UUID
) -> SiteIngestion | None:
    row = await conn.fetchrow(
        """
        SELECT * FROM site_ingestions
         WHERE tenant_id = $1 AND deleted_at IS NULL AND status = ANY($2::text[])
        """,
        tenant_id,
        _ACTIVE,
    )
    return _ingestion_from_row(row) if row else None


async def get_latest_site_ingestion(
    conn: asyncpg.Connection, tenant_id: UUID
) -> SiteIngestion | None:
    """La ingesta a mostrar en la ficha: la activa; si no hay, la última que dejó fuentes
    (una reingesta sin cambios no crea ninguna y no debe tapar el lote pendiente); si no, la
    última."""
    row = await conn.fetchrow(
        """
        SELECT i.* FROM site_ingestions i
         WHERE i.tenant_id = $1 AND i.deleted_at IS NULL
         ORDER BY (i.status = ANY($2::text[])) DESC,
                  EXISTS (SELECT 1 FROM tenant_knowledge_submissions s
                           WHERE s.ingestion_id = i.id AND s.deleted_at IS NULL) DESC,
                  i.created_at DESC
         LIMIT 1
        """,
        tenant_id,
        _ACTIVE,
    )
    return _ingestion_from_row(row) if row else None


async def get_site_ingestion(
    conn: asyncpg.Connection, tenant_id: UUID, ingestion_id: UUID
) -> SiteIngestion | None:
    row = await conn.fetchrow(
        "SELECT * FROM site_ingestions WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL",
        tenant_id,
        ingestion_id,
    )
    return _ingestion_from_row(row) if row else None


async def claim_next_site_ingestion(
    conn: asyncpg.Connection,
    *,
    lease_seconds: int,
    ingestion_id: UUID | None = None,
) -> ClaimedIngestion | None:
    async with conn.transaction():
        await conn.execute(
            """
            UPDATE site_ingestions
               SET status = 'failed', locked_until = NULL, finished_at = now(),
                   failure_reason = 'lease_expired: agotó sus intentos sin terminar'
             WHERE deleted_at IS NULL AND status = ANY($1::text[])
               AND locked_until < now() AND attempts >= max_attempts
            """,
            _RUNNING,
        )
        row = await conn.fetchrow(
            """
            UPDATE site_ingestions s
               SET status = 'fetching', attempts = s.attempts + 1,
                   locked_until = now() + make_interval(secs => $1),
                   started_at = coalesce(s.started_at, now())
             WHERE s.id = (
                   SELECT id FROM site_ingestions
                    WHERE deleted_at IS NULL
                      AND ((status = 'queued' AND run_after <= now())
                           OR (status = ANY($2::text[]) AND locked_until < now()))
                      AND ($3::uuid IS NULL OR id = $3)
                    ORDER BY created_at
                    LIMIT 1
                      FOR UPDATE SKIP LOCKED)
            RETURNING id, tenant_id, root_url, attempts, max_attempts, requested_by
            """,
            lease_seconds,
            _RUNNING,
            ingestion_id,
        )
    if row is None:
        return None
    return ClaimedIngestion(
        id=row["id"],
        tenant_id=row["tenant_id"],
        root_url=row["root_url"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        requested_by=row["requested_by"],
    )


async def extend_site_ingestion_lease(
    conn: asyncpg.Connection, job: ClaimedIngestion, *, lease_seconds: int
) -> bool:
    row = await conn.fetchrow(
        """
        UPDATE site_ingestions
           SET locked_until = now() + make_interval(secs => $3)
         WHERE id = $1 AND attempts = $2 AND status = ANY($4::text[])
        RETURNING id
        """,
        job.id,
        job.attempts,
        lease_seconds,
        _RUNNING,
    )
    return row is not None


async def transition_site_ingestion(
    conn: asyncpg.Connection,
    job: ClaimedIngestion,
    to: IngestionStatus,
    *,
    platform: Platform | None = None,
    stats: dict[str, Any] | None = None,
    failure_reason: str | None = None,
    run_after_seconds: int | None = None,
) -> None:
    terminal = not TRANSITIONS[to]
    row = await conn.fetchrow(
        """
        UPDATE site_ingestions
           SET status = $3,
               platform = coalesce($4, platform),
               stats = coalesce($5::jsonb, stats),
               failure_reason = CASE WHEN $3 = 'ready' THEN NULL
                                     ELSE coalesce($6, failure_reason) END,
               run_after = CASE WHEN $7::int IS NULL THEN run_after
                                ELSE now() + make_interval(secs => $7::int) END,
               locked_until = CASE WHEN $3 = 'queued' OR $8 THEN NULL ELSE locked_until END,
               finished_at = CASE WHEN $8 THEN now() ELSE NULL END
         WHERE id = $1 AND attempts = $2 AND deleted_at IS NULL
           AND status = ANY($9::text[])
        RETURNING id
        """,
        job.id,
        job.attempts,
        to.value,
        platform.value if platform else None,
        stats,
        failure_reason,
        run_after_seconds,
        terminal,
        predecessors_of(to),
    )
    if row is None:
        raise LeaseLost(f"site_ingestion {job.id}: no se pudo pasar a {to.value}")


async def lock_owned_site_ingestion(
    conn: asyncpg.Connection, job: ClaimedIngestion, status: IngestionStatus
) -> None:
    row = await conn.fetchrow(
        """
        SELECT id FROM site_ingestions
         WHERE id = $1 AND attempts = $2 AND status = $3 AND deleted_at IS NULL
           FOR UPDATE
        """,
        job.id,
        job.attempts,
        status.value,
    )
    if row is None:
        raise LeaseLost(f"site_ingestion {job.id}: ya no está en {status.value} con este lease")


async def fail_site_ingestion(
    conn: asyncpg.Connection,
    job: ClaimedIngestion,
    *,
    reason: str,
    retry_in_seconds: int | None,
) -> IngestionStatus:
    retry = retry_in_seconds is not None and job.attempts < job.max_attempts
    to = IngestionStatus.QUEUED if retry else IngestionStatus.FAILED
    await transition_site_ingestion(
        conn,
        job,
        to,
        failure_reason=reason[:2000],
        run_after_seconds=retry_in_seconds if retry else None,
    )
    return to


async def release_site_ingestion(conn: asyncpg.Connection, job: ClaimedIngestion) -> None:
    await transition_site_ingestion(conn, job, IngestionStatus.QUEUED, run_after_seconds=0)


async def known_source_contents(
    conn: asyncpg.Connection, tenant_id: UUID, source_keys: list[str]
) -> list[KnownContent]:
    if not source_keys:
        return []
    rows = await conn.fetch(
        """
        SELECT source_key, content, false AS pending
          FROM knowledge_base_documents
         WHERE tenant_id = $1 AND source_key = ANY($2::text[]) AND deleted_at IS NULL
        UNION ALL
        SELECT source_key, content, true AS pending
          FROM tenant_knowledge_submissions
         WHERE tenant_id = $1 AND source_key = ANY($2::text[]) AND deleted_at IS NULL
           AND status = 'pending_review'::tenant_knowledge_submission_status
        """,
        tenant_id,
        source_keys,
    )
    return [
        KnownContent(
            source_key=r["source_key"], sha256=content_sha256(r["content"]), pending=r["pending"]
        )
        for r in rows
    ]


@dataclass(frozen=True)
class IngestionSubmission:
    id: UUID
    title: str
    source_url: str | None
    source_key: str | None
    status: str
    metadata: dict[str, Any]
    review_note: str | None
    reviewed_at: datetime | None


async def list_ingestion_submissions(
    conn: asyncpg.Connection, tenant_id: UUID, ingestion_id: UUID
) -> list[IngestionSubmission]:
    rows = await conn.fetch(
        """
        SELECT id, title, source_url, source_key, status::text AS status, metadata,
               review_note, reviewed_at
          FROM tenant_knowledge_submissions
         WHERE tenant_id = $1 AND ingestion_id = $2 AND deleted_at IS NULL
         ORDER BY source_key, created_at
        """,
        tenant_id,
        ingestion_id,
    )
    return [
        IngestionSubmission(
            id=r["id"],
            title=r["title"],
            source_url=r["source_url"],
            source_key=r["source_key"],
            status=r["status"],
            metadata=json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
            review_note=r["review_note"],
            reviewed_at=r["reviewed_at"],
        )
        for r in rows
    ]
