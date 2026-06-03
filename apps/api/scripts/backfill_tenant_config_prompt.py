"""Backfill de `tenant_configurations` + prompt 'system' en tenants EXISTENTES.

Los tenants nuevos ya los reciben al crearse (provision_tenant llama a
`ensure_tenant_config_and_prompt`). Este script es para tenants creados antes del
fix (provisioning por portal no las creaba → fallaban con `tenant_config_missing` /
`no_active_system_prompt` en el primer mensaje).

Uso:
    # un tenant
    PYTHONPATH=<repo_root> poetry run -C apps/api python -m apps.api.scripts.backfill_tenant_config_prompt --tenant <uuid>
    # todos los tenants activos
    PYTHONPATH=<repo_root> poetry run -C apps/api python -m apps.api.scripts.backfill_tenant_config_prompt --all

Idempotente: la config usa ON CONFLICT DO NOTHING y el prompt sólo se crea si el
tenant no tiene ya un 'system'. Tenants ya completos (ej. los arreglados a mano) se
saltan sin tocar nada.
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
logger = logging.getLogger("backfill_tenant_config_prompt")


async def main(*, tenant_id: uuid.UUID | None, all_tenants: bool) -> int:
    from apps.api.core.config import get_settings
    from apps.api.db.client import (
        bootstrap_connection,
        close_pool,
        init_pool,
        tenant_scope,
    )
    from apps.api.services.tenant_provisioning import ensure_tenant_config_and_prompt

    get_settings()
    await init_pool()

    try:
        if all_tenants:
            async with bootstrap_connection() as conn:
                rows = await conn.fetch(
                    "SELECT id, name FROM tenants WHERE deleted_at IS NULL ORDER BY created_at"
                )
            targets = [(r["id"], r["name"]) for r in rows]
            logger.info("Backfill de %d tenants activos", len(targets))
        else:
            assert tenant_id is not None
            async with bootstrap_connection() as conn:
                name = await conn.fetchval(
                    "SELECT name FROM tenants WHERE id = $1 AND deleted_at IS NULL",
                    tenant_id,
                )
            if name is None:
                print(f"Error: tenant {tenant_id} no existe o está soft-deleted.", file=sys.stderr)
                return 1
            targets = [(tenant_id, name)]

        totals = {"config_created": 0, "prompt_created": 0}
        for tid, name in targets:
            # tenant_scope abre transacción + setea app.tenant_id → atómico por tenant.
            async with tenant_scope(tid) as conn:
                result = await ensure_tenant_config_and_prompt(conn, tid, company_name=name)
            totals["config_created"] += int(result["config_created"])
            totals["prompt_created"] += int(result["prompt_created"])
            logger.info(
                "tenant=%s config_created=%s prompt_created=%s",
                tid,
                result["config_created"],
                result["prompt_created"],
            )

        print(
            f"\nListo: {totals['config_created']} configs creadas, "
            f"{totals['prompt_created']} prompts creados, en {len(targets)} tenant(s)."
        )
        return 0
    finally:
        await close_pool()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill de tenant_configurations + prompt 'system' en tenants existentes."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant", help="UUID del tenant")
    group.add_argument(
        "--all",
        action="store_true",
        help="Aplica a TODOS los tenants activos (no soft-deleted).",
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

    sys.exit(asyncio.run(main(tenant_id=parsed_tenant, all_tenants=args.all)))
