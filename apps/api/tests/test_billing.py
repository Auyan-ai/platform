"""Tests del service de billing por resolución (Bloque 2).

Unitarios: la lógica de periodo (anclado, clamp de fin de mes, cruce de año), el
catálogo de tiers y el cálculo de la factura (suelo + overage). Las queries SQL se
mockean — su corrección se verifica con la migración aplicada + prueba E2E.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from apps.api.core.errors import NotFoundError
from apps.api.db.models import BillingSubscription
from apps.api.services import billing
from apps.api.services.billing import (
    current_period_bounds,
    tier_defaults,
)

TENANT_ID = uuid4()


def _dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


# ─── Catálogo de tiers ─────────────────────────────────────────────────────────


def test_tier_defaults_returns_catalog_values() -> None:
    assert tier_defaults("starter") == {
        "floor_cents": 89_000,
        "included_resolutions": 1_000,
        "overage_cents": 25,
    }
    assert tier_defaults("scale")["included_resolutions"] == 10_000


def test_tier_defaults_returns_a_copy() -> None:
    """Mutar el resultado no debe contaminar el catálogo global."""
    d = tier_defaults("starter")
    d["floor_cents"] = 0
    assert billing.BILLING_TIERS["starter"]["floor_cents"] == 89_000


def test_tier_defaults_founding_raises() -> None:
    with pytest.raises(ValueError, match="founding"):
        tier_defaults("founding")


# ─── Periodo de facturación anclado ────────────────────────────────────────────


def test_period_now_after_anchor_natural_month() -> None:
    start, end = current_period_bounds(_dt(2026, 6, 21), anchor_day=1)
    assert start == _dt(2026, 6, 1)
    assert end == _dt(2026, 7, 1)


def test_period_now_before_anchor() -> None:
    start, end = current_period_bounds(_dt(2026, 6, 10), anchor_day=15)
    assert start == _dt(2026, 5, 15)
    assert end == _dt(2026, 6, 15)


def test_period_now_on_anchor_is_period_start() -> None:
    """En el día/hora exacta del anchor empieza el periodo nuevo (half-open)."""
    start, _ = current_period_bounds(_dt(2026, 6, 15), anchor_day=15)
    assert start == _dt(2026, 6, 15)


def test_period_anchor_clamps_to_short_month() -> None:
    # anchor 31 en un now de marzo: el inicio del periodo previo cae en febrero,
    # clampado al último día (28 en 2026).
    start, end = current_period_bounds(_dt(2026, 3, 5), anchor_day=31)
    assert start == _dt(2026, 2, 28)
    assert end == _dt(2026, 3, 31)


def test_period_crosses_year_boundary_backwards() -> None:
    start, end = current_period_bounds(_dt(2026, 1, 10), anchor_day=20)
    assert start == _dt(2025, 12, 20)
    assert end == _dt(2026, 1, 20)


def test_period_crosses_year_boundary_forwards() -> None:
    start, end = current_period_bounds(_dt(2026, 12, 25), anchor_day=1)
    assert start == _dt(2026, 12, 1)
    assert end == _dt(2027, 1, 1)


# ─── Cálculo de uso / factura ──────────────────────────────────────────────────


def _sub(**overrides) -> BillingSubscription:
    base = dict(
        tenant_id=TENANT_ID,
        tier="starter",
        floor_cents=89_000,
        included_resolutions=1_000,
        overage_cents=25,
        currency="EUR",
        reopen_window_days=7,
        period_anchor_day=1,
        status="active",
    )
    return BillingSubscription(**{**base, **overrides})


def _patch_queries(monkeypatch, *, sub, count) -> None:
    monkeypatch.setattr(
        "apps.api.services.billing.get_billing_subscription",
        AsyncMock(return_value=sub),
    )
    monkeypatch.setattr(
        "apps.api.services.billing.count_billable_resolutions",
        AsyncMock(return_value=count),
    )


@pytest.mark.asyncio
async def test_usage_within_included_is_just_the_floor(monkeypatch) -> None:
    _patch_queries(monkeypatch, sub=_sub(), count=600)

    usage = await billing.compute_period_usage(AsyncMock(), TENANT_ID, now=_dt(2026, 6, 21))

    assert usage.billable_resolutions == 600
    assert usage.overage_resolutions == 0
    assert usage.overage_cents_total == 0
    assert usage.total_cents == 89_000  # solo el suelo
    assert usage.currency == "EUR"


@pytest.mark.asyncio
async def test_usage_with_overage_adds_to_floor(monkeypatch) -> None:
    _patch_queries(monkeypatch, sub=_sub(), count=1_200)

    usage = await billing.compute_period_usage(AsyncMock(), TENANT_ID, now=_dt(2026, 6, 21))

    assert usage.overage_resolutions == 200
    assert usage.overage_cents_total == 200 * 25
    assert usage.total_cents == 89_000 + 200 * 25


@pytest.mark.asyncio
async def test_usage_passes_reopen_window_to_count(monkeypatch) -> None:
    """La ventana de reapertura de la suscripción se propaga al conteo (PRD §2.3)."""
    count_mock = AsyncMock(return_value=10)
    monkeypatch.setattr(
        "apps.api.services.billing.get_billing_subscription",
        AsyncMock(return_value=_sub(reopen_window_days=14)),
    )
    monkeypatch.setattr("apps.api.services.billing.count_billable_resolutions", count_mock)

    await billing.compute_period_usage(AsyncMock(), TENANT_ID, now=_dt(2026, 6, 21))

    from datetime import timedelta

    assert count_mock.await_args.kwargs["reopen_window"] == timedelta(days=14)


@pytest.mark.asyncio
async def test_usage_without_subscription_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.api.services.billing.get_billing_subscription",
        AsyncMock(return_value=None),
    )

    with pytest.raises(NotFoundError, match="billing subscription"):
        await billing.compute_period_usage(AsyncMock(), TENANT_ID)
