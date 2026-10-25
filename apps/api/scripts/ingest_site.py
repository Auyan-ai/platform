"""Ingesta en línea de la web de una tienda (ADR 0015, PR 3).

Uso (desde la raíz del repo, con el entorno de staging cargado para el modo real):
    python -m apps.api.scripts.ingest_site --url thinkingmu.com --dry-run
    python -m apps.api.scripts.ingest_site --tenant <slug> --url thinkingmu.com

`--dry-run` solo lee la web: imprime las fuentes y documentos encontrados y no toca la base.
Sin `--dry-run` encola una ingesta para el tenant, la reclama y la corre aquí mismo con el
mismo código que el worker del API; deja las submissions `pending_review` con su
`ingestion_id` e imprime la fila final de `site_ingestions`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from apps.api.integrations.demo_catalog import normalize_domain
from apps.api.services.site_ingestion.models import IngestionStats
from apps.api.services.site_ingestion.orchestrator import SiteCollection, collect_site


def print_stats(stats: IngestionStats) -> None:
    print(
        f"origen={stats.origin} plataforma={stats.platform} robots={stats.robots} "
        f"docs={stats.docs} palabras={stats.words} peticiones={stats.requests} "
        f"429={stats.rate_limited} segundos={stats.seconds:.1f}"
        + (" TOPE_DE_PETICIONES" if stats.budget_exhausted else "")
    )
    header = f"  {'fuente':16} {'docs':>4} {'palabras':>8} {'pet.':>4} {'429':>3} {'robots':>6} {'seg':>5}  abandono / descartes"
    print(header)
    rows = [("(robots)", stats.robots_txt), *stats.sources.items()]
    for name, s in rows:
        notes = [s.abandoned] if s.abandoned else []
        notes += [f"{k}={v}" for k, v in sorted(s.discarded.items())]
        print(
            f"  {name:16} {s.docs:>4} {s.words:>8} {s.requests:>4} {s.rate_limited:>3} "
            f"{s.blocked_by_robots:>6} {s.seconds:>5.1f}  {', '.join(notes)}"
        )


def print_docs(collection: SiteCollection) -> None:
    for source, docs in collection.docs_by_source.items():
        for doc in docs:
            print(
                f"  [{source.value}] {doc.kind.value:12} {doc.priority.value:6} "
                f"{doc.words:>6}w  {doc.source_key}  — {doc.title[:60]}"
            )


async def dry_run(url: str) -> int:
    collection = await collect_site(url)
    print_stats(collection.stats)
    print_docs(collection)
    return 0 if collection.docs else 1


async def ingest(slug: str, url: str) -> int:
    from apps.api.core.config import get_settings
    from apps.api.db.client import bootstrap_connection, close_pool, init_pool, tenant_scope
    from apps.api.db.queries import get_tenant_by_slug
    from apps.api.db.site_ingestions import (
        claim_next_site_ingestion,
        enqueue_site_ingestion,
        get_site_ingestion,
    )
    from apps.api.services.site_ingestion.worker import SiteIngestionWorker

    settings = get_settings()
    await init_pool()
    try:
        async with bootstrap_connection() as conn:
            tenant = await get_tenant_by_slug(conn, slug)
        if tenant is None:
            print(f"tenant no encontrado: {slug}", file=sys.stderr)
            return 2
        root_url = f"https://{normalize_domain(url)}"
        async with tenant_scope(tenant.id) as conn:
            ingestion_id = await enqueue_site_ingestion(
                conn, tenant_id=tenant.id, root_url=root_url, requested_by=None
            )
        if ingestion_id is None:
            print(f"el tenant {slug} ya tiene una ingesta en curso", file=sys.stderr)
            return 3
        async with bootstrap_connection() as conn:
            job = await claim_next_site_ingestion(
                conn,
                lease_seconds=settings.site_ingestion_worker_lease_seconds,
                ingestion_id=ingestion_id,
            )
        if job is None:
            print(f"otro worker reclamó la ingesta {ingestion_id}", file=sys.stderr)
            return 4
        worker = SiteIngestionWorker(
            concurrency=0, lease_seconds=settings.site_ingestion_worker_lease_seconds
        )
        await worker.execute(job)
        async with tenant_scope(tenant.id) as conn:
            row = await get_site_ingestion(conn, tenant.id, ingestion_id)
        assert row is not None
        print(f"ingesta {row.id} tenant={slug} estado={row.status.value}")
        if row.failure_reason:
            print(f"causa: {row.failure_reason}")
        print(json.dumps(row.stats, ensure_ascii=False, indent=1))
        return 0 if row.status.value == "ready" else 1
    finally:
        await close_pool()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="dominio o URL de la tienda")
    parser.add_argument("--tenant", help="slug del tenant (obligatorio sin --dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="solo lee la web, no escribe")
    args = parser.parse_args()
    if args.dry_run:
        return asyncio.run(dry_run(args.url))
    if not args.tenant:
        parser.error("--tenant es obligatorio sin --dry-run")
    return asyncio.run(ingest(args.tenant, args.url))


if __name__ == "__main__":
    sys.exit(main())
