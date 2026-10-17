"""Guardas de costo para el simulador.

Dos niveles, configurables (`SIMULATOR_DAILY_CAP_USD_TENANT` / `_GLOBAL`):
  - Per-tenant: $2/día por defecto.
  - Global: $5/día por defecto en todo el proceso.

`ensure_simulation_budget` lo llama `run_simulation` antes de cada run, así que el
tope vale igual para el panel que para `scripts/run_simulator.py`.

Ambos caps usan la DB directamente (no Redis — no está en el stack actual).
Las queries leen solo runs terminados (passed/partial/failed/errored) del último día.

Los checks se llaman ANTES de iniciar cada run o batch.
"""

from __future__ import annotations

import logging
from uuid import UUID

from apps.api.core.config import get_settings
from apps.api.core.errors import BudgetExceededError
from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.queries import (
    get_global_sim_cost_cents_today,
    get_tenant_sim_cost_cents_today,
)
from fastapi import HTTPException

logger = logging.getLogger(__name__)

_DAY_SECONDS = 86_400


class SimulationBudgetExceeded(BudgetExceededError):
    """Se alcanzó el tope diario de gasto del simulador."""

    code = "simulation_budget_exceeded"


def _tenant_cap_cents() -> float:
    return get_settings().simulator_daily_cap_usd_tenant * 100


def _global_cap_cents() -> float:
    return get_settings().simulator_daily_cap_usd_global * 100


async def simulation_spend_cents(tenant_id: UUID) -> tuple[float, float]:
    """(gasto del tenant, gasto global) del simulador en las últimas 24 h, en centavos."""
    async with tenant_scope(tenant_id) as conn:
        tenant = await get_tenant_sim_cost_cents_today(conn, tenant_id)
    async with bootstrap_connection() as conn:
        total = await get_global_sim_cost_cents_today(conn)
    return tenant, total


async def ensure_simulation_budget(tenant_id: UUID) -> None:
    """Lanza `SimulationBudgetExceeded` si el tenant o el total superan el tope diario."""
    tenant, total = await simulation_spend_cents(tenant_id)
    for scope, spent, cap in (
        ("tenant", tenant, _tenant_cap_cents()),
        ("global", total, _global_cap_cents()),
    ):
        if spent >= cap:
            logger.error(
                "sim_daily_budget_exceeded scope=%s tenant_id=%s spent_cents=%.2f cap_cents=%.2f",
                scope,
                tenant_id,
                spent,
                cap,
            )
            raise SimulationBudgetExceeded(
                f"Tope diario del simulador ({scope}) alcanzado: ${spent / 100:.2f} de "
                f"${cap / 100:.2f}. Sube SIMULATOR_DAILY_CAP_USD_{scope.upper()} a propósito.",
                retry_after=_DAY_SECONDS,
            )


async def check_tenant_cost_cap(tenant_id: UUID) -> None:
    """Lanza HTTPException 429 si el tenant superó su tope diario en simulaciones."""
    async with tenant_scope(tenant_id) as conn:
        total = await get_tenant_sim_cost_cents_today(conn, tenant_id)

    if total >= _tenant_cap_cents():
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
                    f"(${_tenant_cap_cents() / 100:.0f}/día). "
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
    """Lanza HTTPException 429 si el costo global diario superó el tope."""
    async with bootstrap_connection() as conn:
        total = await get_global_sim_cost_cents_today(conn)

    if total >= _global_cap_cents():
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
