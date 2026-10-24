"""Lógica de negocio de escalaciones.

Sin imports de FastAPI. Lanza excepciones de dominio; el handler global las traduce a HTTP.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.core.errors import ConflictError, NotFoundError
from apps.api.db.models import Escalation, EscalationStatus
from apps.api.db.queries import (
    claim_escalation,
    get_escalation,
    list_escalations,
    resolve_escalation,
)

if TYPE_CHECKING:
    import asyncpg


async def list_tenant_escalations(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    status: EscalationStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Escalation]:
    return await list_escalations(conn, tenant_id, status=status, limit=limit, offset=offset)


async def claim_tenant_escalation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    escalation_id: UUID,
    agent_user_id: UUID,
) -> Escalation:
    existing = await get_escalation(conn, tenant_id, escalation_id)
    if existing is None:
        raise NotFoundError(f"escalation {escalation_id} not found", code="escalation_not_found")
    result = await claim_escalation(conn, tenant_id, escalation_id, agent_user_id)
    if result is None:
        raise ConflictError(
            f"escalation {escalation_id} is not in 'pending' state",
            code="escalation_not_pending",
        )
    return result


async def resolve_tenant_escalation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    escalation_id: UUID,
) -> Escalation:
    existing = await get_escalation(conn, tenant_id, escalation_id)
    if existing is None:
        raise NotFoundError(f"escalation {escalation_id} not found", code="escalation_not_found")
    result = await resolve_escalation(conn, tenant_id, escalation_id)
    if result is None:
        raise ConflictError(
            f"escalation {escalation_id} is not in 'claimed' state",
            code="escalation_not_claimed",
        )
    return result
