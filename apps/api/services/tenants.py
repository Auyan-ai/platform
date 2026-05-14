"""Lógica de negocio de tenants.

Sin imports de FastAPI. Lanza excepciones de dominio; el handler global las traduce a HTTP.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.core.errors import NotFoundError
from apps.api.db.models import Tenant, TenantConfiguration
from apps.api.db.queries import get_tenant_by_id, get_tenant_configuration

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
