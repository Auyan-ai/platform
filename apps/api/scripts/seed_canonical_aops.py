"""Siembra/actualiza los 8 AOPs canónicos en tenants EXISTENTES.

Los tenants nuevos ya los reciben automáticamente al crearse (provision_tenant llama
a provision_canonical_aops). Este script es para:
  - backfillear tenants que se crearon antes de existir el auto-provisioning, o
  - propagar mejoras del canon a tenants existentes (--update crea una versión nueva).

Uso:
    # un tenant
    PYTHONPATH=<repo_root> poetry run -C apps/api python -m apps.api.scripts.seed_canonical_aops --tenant <uuid>
    # todos los tenants activos
    PYTHONPATH=<repo_root> poetry run -C apps/api python -m apps.api.scripts.seed_canonical_aops --all
    # propagar mejoras (crea versión nueva de los que ya existen)
    PYTHONPATH=<repo_root> poetry run -C apps/api python -m apps.api.scripts.seed_canonical_aops --all --update

Idempotente: sin --update, los AOPs que ya existen se saltan (no pisa personalizaciones
del tenant). Con --update, crea una versión nueva con el contenido canónico.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("seed_canonical_aops")


async def main(*, tenant_id: uuid.UUID | None, all_tenants: bool, update: bool) -> int:
    from apps.api.aops.canonical import provision_canonical_aops
    from apps.api.core.config import get_settings
    from apps.api.db.client import (
        bootstrap_connection,
        close_pool,
        init_pool,
        tenant_scope,
    )

    get_settings()
    await init_pool()

    try:
        if all_tenants:
            async with bootstrap_connection() as conn:
                rows = await conn.fetch(
                    "SELECT id FROM tenants WHERE deleted_at IS NULL ORDER BY created_at"
                )
            tenant_ids = [r["id"] for r in rows]
            logger.info("Backfill de %d tenants activos", len(tenant_ids))
        else:
            assert tenant_id is not None
            tenant_ids = [tenant_id]

        totals = {"created": 0, "updated": 0, "skipped": 0}
        for tid in tenant_ids:
            # tenant_scope abre transacción + setea app.tenant_id → atómico por tenant.
            async with tenant_scope(tid) as conn:
                result = await provision_canonical_aops(
                    conn, tid, update_existing=update
                )
            for key in totals:
                totals[key] += result[key]
            logger.info(
                "tenant=%s creados=%d actualizados=%d saltados=%d",
                tid,
                result["created"],
                result["updated"],
                result["skipped"],
            )

        print(
            f"\nListo: {totals['created']} creados, {totals['updated']} actualizados, "
            f"{totals['skipped']} saltados, en {len(tenant_ids)} tenant(s)."
        )
        return 0
    finally:
        await close_pool()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Siembra los 8 AOPs canónicos en tenants existentes."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant", help="UUID del tenant")
    group.add_argument(
        "--all",
        action="store_true",
        help="Aplica a TODOS los tenants activos (no soft-deleted).",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Crea una versión nueva de los AOPs que ya existen (propaga mejoras del canon).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    parsed_tenant: uuid.UUID | None = None
    if args.tenant:
        try:
            parsed_tenant = uuid.UUID(args.tenant)
        except ValueError:
            print(f"Error: '{args.tenant}' no es un UUID válido.", file=sys.stderr)
            sys.exit(1)

    sys.exit(
        asyncio.run(
            main(tenant_id=parsed_tenant, all_tenants=args.all, update=args.update)
        )
    )
