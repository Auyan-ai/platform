from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.queries import create_tenant_knowledge_submission
from apps.api.db.site_ingestions import (
    ClaimedIngestion,
    known_source_contents,
    lock_owned_site_ingestion,
    transition_site_ingestion,
)
from apps.api.integrations.demo_catalog import normalize_domain
from apps.api.services.site_ingestion.fetcher import PoliteFetcher
from apps.api.services.site_ingestion.models import (
    MIN_WORDS,
    DiscardReason,
    IngestionStats,
    IngestionStatus,
    Limits,
    Platform,
    SourceDoc,
    SourceName,
    SourceStats,
)
from apps.api.services.site_ingestion.sources import SOURCES, SourceContext, SourceSpec
from apps.api.services.site_ingestion.sources.storefront_api import probe_primary_domain

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


class NoContentError(RuntimeError):
    pass


@dataclass
class SiteCollection:
    origin: str
    platform: Platform
    stats: IngestionStats
    docs_by_source: dict[SourceName, list[SourceDoc]] = field(default_factory=dict)

    @property
    def docs(self) -> list[SourceDoc]:
        return [doc for docs in self.docs_by_source.values() for doc in docs]


async def detect_platform(fetcher: PoliteFetcher, origin: str) -> tuple[Platform, str]:
    session = fetcher.session(SourceName.STOREFRONT_API)
    primary = await probe_primary_domain(session, origin)
    if primary is None:
        return Platform.OTHER, origin
    return Platform.SHOPIFY, primary


async def collect_site(
    root_url: str,
    *,
    limits: Limits | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    sources: tuple[SourceSpec, ...] = SOURCES,
) -> SiteCollection:
    limits = limits or Limits()
    started = time.monotonic()
    stats = IngestionStats(root_url=root_url)
    origin = f"https://{normalize_domain(root_url)}"
    async with PoliteFetcher(stats, limits=limits, transport=transport, sleep=sleep) as fetcher:
        platform, origin = await detect_platform(fetcher, origin)
        stats.origin, stats.platform = origin, platform
        collection = SiteCollection(origin=origin, platform=platform, stats=stats)
        accepted_keys: set[str] = set()
        accepted_shas: set[str] = set()
        for spec in sources:
            if platform not in spec.platforms:
                continue
            session = fetcher.session(spec.name)
            ctx = SourceContext(
                origin=origin,
                platform=platform,
                fetcher=fetcher,
                session=session,
                remaining_pages=limits.max_pages - len(accepted_keys),
                accepted_keys=frozenset(accepted_keys),
            )
            source_started = time.monotonic()
            try:
                found = await spec.collect(ctx)
            except Exception as exc:
                logger.exception(
                    "site_ingestion_source_failed",
                    extra={"origin": origin, "source": spec.name.value},
                )
                session.stats.errors += 1
                session.abandon(f"error: {type(exc).__name__}")
                found = []
            session.stats.seconds += time.monotonic() - source_started
            stats.store_name = stats.store_name or ctx.store_name
            kept = [
                doc
                for doc in found
                if _accept(doc, session.stats, accepted_keys, accepted_shas, limits)
            ]
            collection.docs_by_source[spec.name] = kept
    stats.seconds = time.monotonic() - started
    return collection


def _accept(
    doc: SourceDoc,
    stats: SourceStats,
    keys: set[str],
    shas: set[str],
    limits: Limits,
) -> bool:
    if doc.words < MIN_WORDS[doc.kind]:
        stats.discard(DiscardReason.TOO_SHORT)
        return False
    if doc.sha256 in shas:
        stats.discard(DiscardReason.DUPLICATE_CONTENT)
        return False
    if doc.source_key in keys:
        stats.discard(DiscardReason.DUPLICATE_SOURCE_KEY)
        return False
    if len(keys) >= limits.max_pages:
        stats.discard(DiscardReason.PAGE_BUDGET)
        return False
    keys.add(doc.source_key)
    shas.add(doc.sha256)
    stats.docs += 1
    stats.words += doc.words
    return True


async def persist_documents(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    ingestion_id: UUID,
    collection: SiteCollection,
    submitted_by: UUID | None = None,
) -> int:
    known = await known_source_contents(
        conn, tenant_id, [doc.source_key for doc in collection.docs]
    )
    live = {(k.source_key, k.sha256) for k in known if not k.pending}
    pending = {(k.source_key, k.sha256) for k in known if k.pending}
    created = 0
    for source, docs in collection.docs_by_source.items():
        stats = collection.stats.source(source)
        for doc in docs:
            if (doc.source_key, doc.sha256) in live:
                stats.discard(DiscardReason.UNCHANGED)
                continue
            if (doc.source_key, doc.sha256) in pending:
                stats.discard(DiscardReason.ALREADY_PENDING)
                continue
            await create_tenant_knowledge_submission(
                conn,
                tenant_id,
                title=doc.title[:500],
                source_type="url",
                source_url=doc.url,
                content=doc.markdown,
                metadata={
                    "ingestion_id": str(ingestion_id),
                    "source": source.value,
                    "kind": doc.kind.value,
                    "priority": doc.priority.value,
                    "content_sha256": doc.sha256,
                    "words": doc.words,
                },
                submitted_by=submitted_by,
                source_key=doc.source_key,
                ingestion_id=ingestion_id,
            )
            created += 1
    collection.stats.created = created
    return created


def _no_content_reason(stats: IngestionStats) -> str:
    parts = [f"robots={stats.robots}"]
    parts += [f"{name}={s.abandoned or f'{s.requests}req'}" for name, s in stats.sources.items()]
    return "no_content: " + ", ".join(parts)


async def run_ingestion(
    job: ClaimedIngestion,
    *,
    limits: Limits | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> IngestionStats:
    """Corre una ingesta reclamada (`fetching`) hasta `ready`.

    Lanza `NoContentError` si ninguna fuente dio nada, y `LeaseLost` si otro worker se quedó
    la ingesta: en ese caso no se escribe ninguna submission.
    """
    collection = await collect_site(job.root_url, limits=limits, transport=transport, sleep=sleep)
    stats = collection.stats
    if not collection.docs:
        raise NoContentError(_no_content_reason(stats))
    async with bootstrap_connection() as conn:
        await transition_site_ingestion(
            conn,
            job,
            IngestionStatus.EXTRACTING,
            platform=collection.platform,
            stats=stats.to_json(),
        )
    async with tenant_scope(job.tenant_id) as conn:
        await lock_owned_site_ingestion(conn, job, IngestionStatus.EXTRACTING)
        await persist_documents(
            conn,
            tenant_id=job.tenant_id,
            ingestion_id=job.id,
            collection=collection,
            submitted_by=job.requested_by,
        )
        await transition_site_ingestion(conn, job, IngestionStatus.READY, stats=stats.to_json())
    return stats
