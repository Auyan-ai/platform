"""Guardas de costo para el simulador.

Dos niveles:
  - Per-tenant: $5/día. Previene que un tenant queme presupuesto sin control.
  - Global: $50/día en todo el proceso. Previene runaway en casos de bug/abuso.

Ambos caps usan la DB directamente (no Redis — no está en el stack actual).
Las queries leen solo runs terminados (passed/partial/failed/errored) del último día.

Los checks se llaman ANTES de iniciar cada run o batch.
"""

from __future__ import annotations

import logging
from uuid import UUID

from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.queries import (
    get_global_sim_cost_cents_today,
    get_tenant_sim_cost_cents_today,
)
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Límites en centavos de dólar
_TENANT_DAILY_CAP_CENTS: float = 500.0    # $5/día por tenant
_GLOBAL_DAILY_CAP_CENTS: float = 5000.0   # $50/día cross-tenant


async def check_tenant_cost_cap(tenant_id: UUID) -> None:
    """Lanza HTTPException 429 si el tenant superó $5/día en simulaciones."""
    async with tenant_scope(tenant_id) as conn:
        total = await get_tenant_sim_cost_cents_today(conn, tenant_id)

    if total >= _TENANT_DAILY_CAP_CENTS:
        logger.warning(
            "sim_tenant_cost_cap_exceeded tenant_id=%s total_cents=%.2f",
            tenant_id,
            total,
        )
        raise HTTPException(
            status_code=429,
            detail={
                "code": "tenant_daily_sim_cost_cap_exceeded",
                "message": (
                    f"El tenant superó el límite diario de simulaciones "
                    f"(${_TENANT_DAILY_CAP_CENTS / 100:.0f}/día). "
                    "Intenta de nuevo mañana."
                ),
            },
        )


_TENANT_RUNS_PER_HOUR: int = 20
_TENANT_BATCHES_PER_HOUR: int = 5


async def check_tenant_run_rate_limit(tenant_id: UUID) -> None:
    """Lanza HTTPException 429 si el tenant superó 20 runs/h."""
    async with tenant_scope(tenant_id) as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM simulation_runs
             WHERE tenant_id = $1
               AND started_at >= NOW() - INTERVAL '1 hour'
            """,
            tenant_id,
        )
    if (count or 0) >= _TENANT_RUNS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "tenant_sim_run_rate_limit_exceeded",
                "message": f"Límite de {_TENANT_RUNS_PER_HOUR} simulaciones por hora alcanzado.",
            },
        )


async def check_tenant_batch_rate_limit(tenant_id: UUID) -> None:
    """Lanza HTTPException 429 si el tenant superó 5 batches/h."""
    async with tenant_scope(tenant_id) as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT batch_id)
              FROM simulation_runs
             WHERE tenant_id = $1
               AND batch_id IS NOT NULL
               AND started_at >= NOW() - INTERVAL '1 hour'
            """,
            tenant_id,
        )
    if (count or 0) >= _TENANT_BATCHES_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "tenant_sim_batch_rate_limit_exceeded",
                "message": f"Límite de {_TENANT_BATCHES_PER_HOUR} batches por hora alcanzado.",
            },
        )


async def check_global_cost_cap() -> None:
    """Lanza HTTPException 429 si el costo global diario superó $50."""
    async with bootstrap_connection() as conn:
        total = await get_global_sim_cost_cents_today(conn)

    if total >= _GLOBAL_DAILY_CAP_CENTS:
        logger.error(
            "sim_global_cost_cap_exceeded total_cents=%.2f",
            total,
        )
        raise HTTPException(
            status_code=429,
            detail={
                "code": "global_daily_sim_cost_cap_exceeded",
                "message": (
                    "El sistema de simulación alcanzó el límite diario global. "
                    "Contacta a soporte si necesitas más capacidad hoy."
                ),
            },
        )
