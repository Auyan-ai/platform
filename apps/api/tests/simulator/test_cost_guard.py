"""Tests del cost_guard.py — con mocks de DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def _caps(monkeypatch: pytest.MonkeyPatch) -> None:
    # CI no tiene .env: los topes salen de un Settings falso con los valores por defecto.
    from types import SimpleNamespace

    from apps.api.simulator import cost_guard

    caps = SimpleNamespace(simulator_daily_cap_usd_tenant=2.0, simulator_daily_cap_usd_global=5.0)
    monkeypatch.setattr(cost_guard, "get_settings", lambda: caps)


class TestCheckTenantCostCap:
    @pytest.mark.asyncio
    async def test_passes_under_cap(self):
        tenant_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("apps.api.simulator.cost_guard.tenant_scope", return_value=mock_conn),
            patch(
                "apps.api.simulator.cost_guard.get_tenant_sim_cost_cents_today",
                new_callable=AsyncMock,
                return_value=150.0,  # $1,50, bajo el tope por defecto de $2
            ),
        ):
            from apps.api.simulator.cost_guard import check_tenant_cost_cap

            await check_tenant_cost_cap(tenant_id)  # no debe lanzar

    @pytest.mark.asyncio
    async def test_raises_at_cap(self):
        tenant_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("apps.api.simulator.cost_guard.tenant_scope", return_value=mock_conn),
            patch(
                "apps.api.simulator.cost_guard.get_tenant_sim_cost_cents_today",
                new_callable=AsyncMock,
                return_value=200.0,  # $2 exacto — lanza
            ),
        ):
            from apps.api.simulator.cost_guard import check_tenant_cost_cap

            with pytest.raises(HTTPException) as exc_info:
                await check_tenant_cost_cap(tenant_id)
            assert exc_info.value.status_code == 429
            assert "tenant_daily_sim_cost_cap_exceeded" in str(exc_info.value.detail)


class TestCheckGlobalCostCap:
    @pytest.mark.asyncio
    async def test_passes_under_global_cap(self):
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("apps.api.simulator.cost_guard.bootstrap_connection", return_value=mock_conn),
            patch(
                "apps.api.simulator.cost_guard.get_global_sim_cost_cents_today",
                new_callable=AsyncMock,
                return_value=300.0,
            ),
        ):
            from apps.api.simulator.cost_guard import check_global_cost_cap

            await check_global_cost_cap()  # no debe lanzar

    @pytest.mark.asyncio
    async def test_raises_at_global_cap(self):
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("apps.api.simulator.cost_guard.bootstrap_connection", return_value=mock_conn),
            patch(
                "apps.api.simulator.cost_guard.get_global_sim_cost_cents_today",
                new_callable=AsyncMock,
                return_value=500.0,  # $5 exacto — lanza
            ),
        ):
            from apps.api.simulator.cost_guard import check_global_cost_cap

            with pytest.raises(HTTPException) as exc_info:
                await check_global_cost_cap()
            assert exc_info.value.status_code == 429
            assert "global_daily_sim_cost_cap_exceeded" in str(exc_info.value.detail)


class TestEnsureSimulationBudget:
    """El tope vale para el CLI y el panel: lo llama `run_simulation` antes de gastar."""

    @staticmethod
    def _patches(tenant_cents: float, global_cents: float):
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        return (
            patch("apps.api.simulator.cost_guard.tenant_scope", return_value=mock_conn),
            patch("apps.api.simulator.cost_guard.bootstrap_connection", return_value=mock_conn),
            patch(
                "apps.api.simulator.cost_guard.get_tenant_sim_cost_cents_today",
                new_callable=AsyncMock,
                return_value=tenant_cents,
            ),
            patch(
                "apps.api.simulator.cost_guard.get_global_sim_cost_cents_today",
                new_callable=AsyncMock,
                return_value=global_cents,
            ),
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("tenant", "total"), [(200.0, 200.0), (10.0, 500.0)])
    async def test_stops_when_tenant_or_global_cap_is_reached(self, tenant, total):
        from apps.api.simulator.cost_guard import (
            SimulationBudgetExceeded,
            ensure_simulation_budget,
        )

        a, b, c, d = self._patches(tenant, total)
        with a, b, c, d, pytest.raises(SimulationBudgetExceeded) as exc:
            await ensure_simulation_budget(uuid4())
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_passes_under_both_caps(self):
        from apps.api.simulator.cost_guard import ensure_simulation_budget

        a, b, c, d = self._patches(150.0, 300.0)
        with a, b, c, d:
            await ensure_simulation_budget(uuid4())

    @pytest.mark.asyncio
    async def test_run_simulation_checks_the_budget_before_anything_else(self, monkeypatch):
        from apps.api.simulator import runner
        from apps.api.simulator.cost_guard import SimulationBudgetExceeded

        boom = AsyncMock(side_effect=SimulationBudgetExceeded("tope", retry_after=1))
        scenario_lookup = AsyncMock()
        monkeypatch.setattr(runner, "ensure_simulation_budget", boom)
        monkeypatch.setattr(runner, "get_simulation_scenario", scenario_lookup)
        with pytest.raises(SimulationBudgetExceeded):
            await runner.run_simulation(uuid4(), uuid4(), anthropic=AsyncMock(), graph=AsyncMock())
        scenario_lookup.assert_not_awaited()
