"""Tests del sistema de budget diario por tenant.

Cubre:
- check_tenant_budget: pasa si no hay uso, pasa si bajo el límite,
  lanza BudgetExceededError si supera el límite, respeta override per-tenant
- UsageRecorder: noop con uso cero, noop sin event loop,
  encola task con uso real, fallo de DB silenciado
"""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from apps.api.core.errors import BudgetExceededError
from apps.api.db.models import TenantUsageDaily
from apps.api.services.usage import UsageRecorder, _seconds_until_midnight_utc, check_tenant_budget

from tests.conftest import TENANT_ID, FakeSettings, make_tenant_configuration

# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------


def make_usage(cost_usd: float = 0.0, tokens_in: int = 0, tokens_out: int = 0) -> TenantUsageDaily:
    return TenantUsageDaily(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        tenant_id=TENANT_ID,
        date="2026-05-19",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        request_count=1,
        created_at=datetime.datetime(2026, 5, 19, 0, 0, 0, tzinfo=datetime.UTC),
        updated_at=datetime.datetime(2026, 5, 19, 0, 0, 0, tzinfo=datetime.UTC),
    )


# ----------------------------------------------------------------
# check_tenant_budget
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_budget_no_usage_today_passes():
    """Sin registro hoy → pasa sin error."""
    conn = AsyncMock()
    with patch(
        "apps.api.services.usage.get_tenant_usage_today",
        new=AsyncMock(return_value=None),
    ):
        await check_tenant_budget(
            conn,
            tenant_id=TENANT_ID,
            tenant_config=None,
            settings=FakeSettings(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_check_budget_under_limit_passes():
    """Uso < presupuesto → pasa."""
    conn = AsyncMock()
    usage = make_usage(cost_usd=5.0)
    with patch(
        "apps.api.services.usage.get_tenant_usage_today",
        new=AsyncMock(return_value=usage),
    ):
        await check_tenant_budget(
            conn,
            tenant_id=TENANT_ID,
            tenant_config=None,
            settings=FakeSettings(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_check_budget_at_limit_raises():
    """Uso == presupuesto → BudgetExceededError."""
    conn = AsyncMock()
    usage = make_usage(cost_usd=10.0)
    with patch(
        "apps.api.services.usage.get_tenant_usage_today",
        new=AsyncMock(return_value=usage),
    ):
        with pytest.raises(BudgetExceededError) as exc_info:
            await check_tenant_budget(
                conn,
                tenant_id=TENANT_ID,
                tenant_config=None,
                settings=FakeSettings(),  # type: ignore[arg-type]
            )
    assert exc_info.value.code == "budget_exceeded"
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after > 0


@pytest.mark.asyncio
async def test_check_budget_over_limit_raises():
    """Uso > presupuesto → BudgetExceededError."""
    conn = AsyncMock()
    usage = make_usage(cost_usd=12.5)
    with patch(
        "apps.api.services.usage.get_tenant_usage_today",
        new=AsyncMock(return_value=usage),
    ):
        with pytest.raises(BudgetExceededError):
            await check_tenant_budget(
                conn,
                tenant_id=TENANT_ID,
                tenant_config=None,
                settings=FakeSettings(),  # type: ignore[arg-type]
            )


@pytest.mark.asyncio
async def test_check_budget_tenant_override_respected():
    """Override per-tenant en extra.budget_usd_daily es usado en lugar del default."""
    conn = AsyncMock()
    # Uso de 3 USD — supera el custom budget de 2 USD pero NO el default de 10 USD
    usage = make_usage(cost_usd=3.0)
    tenant_config = make_tenant_configuration(extra={"budget_usd_daily": 2.0})
    with patch(
        "apps.api.services.usage.get_tenant_usage_today",
        new=AsyncMock(return_value=usage),
    ):
        with pytest.raises(BudgetExceededError) as exc_info:
            await check_tenant_budget(
                conn,
                tenant_id=TENANT_ID,
                tenant_config=tenant_config,
                settings=FakeSettings(),  # type: ignore[arg-type]
            )
    assert "3.0000/2.00" in exc_info.value.detail


@pytest.mark.asyncio
async def test_check_budget_invalid_override_uses_default():
    """Override no numérico o <= 0 es ignorado; se usa el default."""
    conn = AsyncMock()
    usage = make_usage(cost_usd=8.0)
    # budget_usd_daily=0 → inválido → usa default 10.0 → 8.0 < 10.0 → pasa
    tenant_config = make_tenant_configuration(extra={"budget_usd_daily": 0})
    with patch(
        "apps.api.services.usage.get_tenant_usage_today",
        new=AsyncMock(return_value=usage),
    ):
        await check_tenant_budget(
            conn,
            tenant_id=TENANT_ID,
            tenant_config=tenant_config,
            settings=FakeSettings(),  # type: ignore[arg-type]
        )


def test_seconds_until_midnight_is_positive():
    assert _seconds_until_midnight_utc() > 0


def test_seconds_until_midnight_under_day():
    assert _seconds_until_midnight_utc() <= 86_400


# ----------------------------------------------------------------
# UsageRecorder
# ----------------------------------------------------------------


def test_usage_recorder_noop_on_zero_usage():
    """record() con todo en cero no encola ninguna tarea."""
    recorder = UsageRecorder()
    initial = len(UsageRecorder._pending_tasks)
    recorder.record(tenant_id=TENANT_ID, tokens_in=0, tokens_out=0, cost_usd=0.0)
    assert len(UsageRecorder._pending_tasks) == initial


def test_usage_recorder_noop_without_event_loop():
    """record() fuera de un event loop no lanza excepción."""
    recorder = UsageRecorder()
    recorder.record(tenant_id=TENANT_ID, tokens_in=100, tokens_out=50, cost_usd=0.001)


@pytest.mark.asyncio
async def test_usage_recorder_creates_task_with_real_usage():
    """record() con uso > 0 encola una tarea asyncio."""
    recorder = UsageRecorder()

    async def _fake_upsert(**_kwargs):  # type: ignore[override]
        pass

    with patch(
        "apps.api.services.usage.upsert_tenant_usage_daily",
        new=AsyncMock(side_effect=_fake_upsert),
    ), patch(
        "apps.api.services.usage.bootstrap_connection",
        new=lambda: _fake_bootstrap(),
    ):
        recorder.record(tenant_id=TENANT_ID, tokens_in=200, tokens_out=100, cost_usd=0.005)
        # Deja que la tarea se ejecute
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_usage_recorder_db_failure_is_silenced():
    """Si la inserción falla, el error es logueado y no se propaga al caller."""
    recorder = UsageRecorder()

    with patch(
        "apps.api.services.usage.upsert_tenant_usage_daily",
        new=AsyncMock(side_effect=RuntimeError("DB down")),
    ), patch(
        "apps.api.services.usage.bootstrap_connection",
        new=lambda: _fake_bootstrap(),
    ):
        recorder.record(tenant_id=TENANT_ID, tokens_in=100, tokens_out=50, cost_usd=0.002)
        await asyncio.sleep(0)  # no lanza


# ----------------------------------------------------------------
# Helper para bootstrap_connection en tests
# ----------------------------------------------------------------


@asynccontextmanager
async def _fake_bootstrap() -> AsyncIterator[MagicMock]:
    yield MagicMock()
