"""Billing por resolución — catálogo de tiers + cálculo de uso del periodo (Bloque 2).

Sin imports de FastAPI; lanza DomainError que el handler global traduce a HTTP. La
unidad de cobro es la resolución (PRD docs/billing-resolution-prd.md): el agente cerró
la conversación sin escalar. Este módulo provee:
- BILLING_TIERS: defaults del catálogo para crear suscripciones.
- current_period_bounds: el periodo de facturación mensual anclado.
- compute_period_usage: cuenta resoluciones cobrables y arma la factura del periodo.

Stripe (cobro real) se conecta después; aquí solo se MIDE y se calcula el importe.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.core.errors import NotFoundError
from apps.api.db.models import BillingTier, BillingUsage
from apps.api.db.queries import count_billable_resolutions, get_billing_subscription

if TYPE_CHECKING:
    import asyncpg

# Catálogo de tiers — DEFAULTS para CREAR suscripciones. No es la fuente de verdad de
# un contrato vigente: cada suscripción guarda su propio snapshot de floor/included/
# overage, así cambiar este catálogo no altera contratos ya firmados. Números del
# PRD §4 (céntimos).
#
# ⚠️ PROVISIONALES — por validar con Founding Partners antes de fijarlos: el overage
# exacto (€0,20 vs €0,25) y las resoluciones incluidas dependen del COGS real medido
# en LangSmith (PRD §3.1, §6, decisiones abiertas). No tratar como verdad cerrada.
# `founding` se omite a propósito: tiene rampa per-cliente (se pasan valores explícitos).
BILLING_TIERS: dict[BillingTier, dict[str, int]] = {
    "starter": {"floor_cents": 89_000, "included_resolutions": 1_000, "overage_cents": 25},
    "growth": {"floor_cents": 249_000, "included_resolutions": 3_000, "overage_cents": 25},
    "scale": {"floor_cents": 599_000, "included_resolutions": 10_000, "overage_cents": 20},
}


def tier_defaults(tier: BillingTier) -> dict[str, int]:
    """floor/included/overage por defecto de un tier del catálogo. Lanza ValueError
    para tiers sin defaults (founding tiene rampa per-cliente → valores explícitos)."""
    if tier not in BILLING_TIERS:
        raise ValueError(f"tier sin defaults en el catálogo: {tier}")
    return dict(BILLING_TIERS[tier])


def _clamp_day(year: int, month: int, day: int) -> int:
    """Acota `day` al último día válido del mes (anchor 31 → 28/29/30 según el mes)."""
    return min(day, calendar.monthrange(year, month)[1])


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """(year, month) desplazado `delta` meses, normalizando el cruce de año."""
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def current_period_bounds(now: datetime, anchor_day: int) -> tuple[datetime, datetime]:
    """[inicio, fin) del periodo de facturación MENSUAL que contiene `now`, anclado a
    `anchor_day` del mes (clamp al último día en meses cortos). Half-open: el fin es
    el inicio del periodo siguiente."""
    anchor_this = now.replace(
        day=_clamp_day(now.year, now.month, anchor_day),
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    if now >= anchor_this:
        ny, nm = _shift_month(now.year, now.month, 1)
        start = anchor_this
        end = now.replace(
            year=ny, month=nm, day=_clamp_day(ny, nm, anchor_day),
            hour=0, minute=0, second=0, microsecond=0,
        )
    else:
        py, pm = _shift_month(now.year, now.month, -1)
        start = now.replace(
            year=py, month=pm, day=_clamp_day(py, pm, anchor_day),
            hour=0, minute=0, second=0, microsecond=0,
        )
        end = anchor_this
    return start, end


async def compute_period_usage(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    now: datetime | None = None,
) -> BillingUsage:
    """Uso del periodo actual del tenant: resoluciones cobrables vs incluidas, overage
    y total estimado (céntimos). Lanza NotFoundError si el tenant no tiene suscripción."""
    sub = await get_billing_subscription(conn, tenant_id)
    if sub is None:
        raise NotFoundError(
            f"billing subscription for tenant {tenant_id} not found",
            code="billing_subscription_not_found",
        )

    now = now or datetime.now(UTC)
    period_start, period_end = current_period_bounds(now, sub.period_anchor_day)

    billable = await count_billable_resolutions(
        conn,
        tenant_id,
        period_start=period_start,
        period_end=period_end,
        reopen_window=timedelta(days=sub.reopen_window_days),
    )
    overage = max(0, billable - sub.included_resolutions)
    overage_total = overage * sub.overage_cents
    total = sub.floor_cents + overage_total

    return BillingUsage(
        tenant_id=tenant_id,
        tier=sub.tier,
        period_start=period_start,
        period_end=period_end,
        billable_resolutions=billable,
        included_resolutions=sub.included_resolutions,
        overage_resolutions=overage,
        floor_cents=sub.floor_cents,
        overage_cents_total=overage_total,
        total_cents=total,
        currency=sub.currency,
    )
