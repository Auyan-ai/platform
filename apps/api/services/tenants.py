"""Lógica de negocio de tenants.

Sin imports de FastAPI. Lanza excepciones de dominio; el handler global las traduce a HTTP.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.core.errors import NotFoundError
from apps.api.db.models import (
    IntegrationGroup,
    IntegrationKind,
    OnboardingChecklist,
    Tenant,
    TenantConfiguration,
)
from apps.api.db.queries import (
    compute_onboarding_checklist,
    get_tenant_by_id,
    get_tenant_configuration,
    list_active_integration_summaries,
    update_tenant_lifecycle_state,
)
from apps.api.db.queries import get_tenant_insights as _get_tenant_insights
from apps.api.db.queries import get_tenant_metrics as _get_tenant_metrics
from apps.api.db.queries import get_tenant_resolution_series as _get_tenant_resolution_series

if TYPE_CHECKING:
    import asyncpg


async def get_tenant(conn: asyncpg.Connection, tenant_id: UUID) -> Tenant:
    tenant = await get_tenant_by_id(conn, tenant_id)
    if tenant is None:
        raise NotFoundError(f"tenant {tenant_id} not found", code="tenant_not_found")
    return tenant


async def evaluate_and_advance_lifecycle(
    conn: asyncpg.Connection, tenant_id: UUID
) -> tuple[Tenant, OnboardingChecklist]:
    """Avanza discovery → building si el checklist de onboarding está completo.

    Sólo automatiza ese salto: nunca retrocede ni toca estados building+
    (gated manualmente por el AIDE). Idempotente: re-llamarla no hace nada
    si el tenant ya pasó de discovery o si el checklist no está completo.
    """
    checklist = await compute_onboarding_checklist(conn, tenant_id)
    tenant = await get_tenant(conn, tenant_id)
    if tenant.agent_lifecycle_state == "discovery" and checklist.complete:
        tenant = await update_tenant_lifecycle_state(conn, tenant_id, "building")
    return tenant, checklist


async def get_tenant_config(conn: asyncpg.Connection, tenant_id: UUID) -> TenantConfiguration:
    config = await get_tenant_configuration(conn, tenant_id)
    if config is None:
        raise NotFoundError(
            f"config for tenant {tenant_id} not found", code="tenant_config_not_found"
        )
    return config


# Orden estable de los grupos en la tarjeta del cliente. `llm` es interno de Auyan
# (credenciales del proveedor de modelos) y no se muestra al cliente.
_CLIENT_VISIBLE_KINDS: tuple[IntegrationKind, ...] = ("channel", "helpdesk", "commerce")


async def list_tenant_integration_groups(
    conn: asyncpg.Connection, tenant_id: UUID
) -> list[IntegrationGroup]:
    """Integraciones activas del tenant agrupadas por kind, en lista blanca."""
    summaries = await list_active_integration_summaries(conn, tenant_id=tenant_id)
    return [
        IntegrationGroup(
            kind=kind,
            integrations=[s for s in summaries if s.kind == kind],
        )
        for kind in _CLIENT_VISIBLE_KINDS
        if any(s.kind == kind for s in summaries)
    ]


async def get_tenant_metrics(conn: asyncpg.Connection, tenant_id: UUID) -> dict[str, object]:
    counts = await _get_tenant_metrics(conn, tenant_id)
    raw_series = await _get_tenant_resolution_series(conn, tenant_id)
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
        "resolution_windows": [
            _build_resolution_window("30d", "Últimos 30 días", "day", raw_series["30d"]),
            _build_resolution_window("7d", "Últimos 7 días", "day", raw_series["7d"]),
            _build_resolution_window("24h", "Último día", "hour", raw_series["24h"]),
        ],
    }


def _build_resolution_window(
    key: str,
    label: str,
    granularity: str,
    points: list[dict[str, object]],
) -> dict[str, object]:
    total_conversations = sum(int(point["conversations"]) for point in points)
    total_resolved = sum(int(point["resolved"]) for point in points)
    total_escalated = sum(int(point["escalated"]) for point in points)

    decorated_points = []
    for point in points:
        conversations = int(point["conversations"])
        resolved = int(point["resolved"])
        escalated = int(point["escalated"])
        decorated_points.append(
            {
                **point,
                "resolution_rate": round(resolved / conversations, 4) if conversations > 0 else 0.0,
                "escalation_rate": round(escalated / conversations, 4)
                if conversations > 0
                else 0.0,
            }
        )

    return {
        "key": key,
        "label": label,
        "granularity": granularity,
        "total": total_conversations,
        "resolved": total_resolved,
        "escalated": total_escalated,
        "resolution_rate": round(total_resolved / total_conversations, 4)
        if total_conversations > 0
        else 0.0,
        "escalation_rate": round(total_escalated / total_conversations, 4)
        if total_conversations > 0
        else 0.0,
        "points": decorated_points,
    }


async def get_tenant_insights(
    conn: asyncpg.Connection, tenant_id: UUID, days: int = 14
) -> dict[str, object]:
    return await _get_tenant_insights(conn, tenant_id, days)
