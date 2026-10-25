"""Nombre oficial de una demo (issue #423, ADR 0015 §5).

`POST /tenants/demos` pone un nombre provisional sacado del dominio (`Thinkingmu`). Cuando la
ingesta llega a `ready`, la fuente oficial de la tienda (`IngestionStats.store_name`) trae el
nombre real (`Thinking MU`) y lo sustituimos, solo si la demo sigue con el provisional.
"""

from __future__ import annotations

import logging
from uuid import UUID

from apps.api.db.client import bootstrap_connection
from apps.api.integrations.demo_catalog import normalize_domain
from apps.api.services.demo_tenants import company_name_from_domain

logger = logging.getLogger(__name__)

MAX_STORE_NAME_LENGTH = 120


async def rename_demo_to_store_name(tenant_id: UUID, store_name: str | None) -> bool:
    """Sustituye el nombre derivado del dominio por `store_name`. Devuelve si cambió algo.

    Solo toca tenants `origin = 'demo'` cuyo nombre sigue siendo el provisional del dominio
    de `demo_source_url`; un cliente o un nombre editado a mano no se tocan. El `UPDATE`
    compara el nombre actual, así que una edición concurrente gana y la llamada es idempotente.
    """
    official = " ".join((store_name or "").split())[:MAX_STORE_NAME_LENGTH]
    if not official:
        return False
    async with bootstrap_connection() as conn:
        row = await conn.fetchrow(
            "SELECT name, demo_source_url FROM tenants"
            " WHERE id = $1 AND origin = 'demo' AND deleted_at IS NULL",
            tenant_id,
        )
        if row is None or not row["demo_source_url"]:
            return False
        try:
            provisional = company_name_from_domain(normalize_domain(row["demo_source_url"]))
        except ValueError:
            logger.warning("demo_rename_bad_source_url", extra={"tenant_id": str(tenant_id)})
            return False
        if row["name"] == official or row["name"] != provisional:
            return False
        updated = await conn.fetchval(
            "UPDATE tenants SET name = $2, updated_at = now()"
            " WHERE id = $1 AND origin = 'demo' AND deleted_at IS NULL AND name = $3"
            " RETURNING id",
            tenant_id,
            official,
            provisional,
        )
    if updated is None:
        return False
    logger.info(
        "demo_renamed_to_store_name",
        extra={"tenant_id": str(tenant_id), "from": provisional, "to": official},
    )
    return True
