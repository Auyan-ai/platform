"""Lógica de negocio de tenants.

Sin imports de FastAPI. Lanza excepciones de dominio; el handler global las traduce a HTTP.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.core.errors import NotFoundError
from apps.api.db.models import Tenant, TenantConfiguration
from apps.api.db.queries import get_tenant_by_id, get_tenant_configuration
from apps.api.db.queries import get_tenant_metrics as _get_tenant_metrics

if TYPE_CHECKING:
    import asyncpg


async def get_tenant(conn: asyncpg.Connection, tenant_id: UUID) -> Tenant:
    tenant = await get_tenant_by_id(conn, tenant_id)
    if tenant is None:
        raise NotFoundError(f"tenant {tenant_id} not found", code="tenant_not_found")
    return tenant


async def get_tenant_config(
    conn: asyncpg.Connection, tenant_id: UUID
) -> TenantConfiguration:
    config = await get_tenant_configuration(conn, tenant_id)
    if config is None:
        raise NotFoundError(
            f"config for tenant {tenant_id} not found", code="tenant_config_not_found"
        )
    return config


async def get_tenant_metrics(conn: asyncpg.Connection, tenant_id: UUID) -> dict[str, object]:
    counts = await _get_tenant_metrics(conn, tenant_id)
    total = int(counts["total"])
    resolved = int(counts["resolved_count"]) + int(counts["closed_count"])
    escalated = int(counts["escalated_count"])
    resolution_rate = round(resolved / total, 4) if total > 0 else 0.0
    escalation_rate = round(escalated / total, 4) if total > 0 else 0.0
    return {
        "total": total,
        "by_status": {
            "open": int(counts["open_count"]),
            "pending": int(counts["pending_count"]),
            "escalated": escalated,
            "resolved": int(counts["resolved_count"]),
            "closed": int(counts["closed_count"]),
        },
        "resolution_rate": resolution_rate,
        "escalation_rate": escalation_rate,
    }
