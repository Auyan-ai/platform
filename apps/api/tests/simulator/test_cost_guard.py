"""Tests del cost_guard.py — con mocks de DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


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
                return_value=500.0,  # $5, bajo el cap de $10
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
                return_value=1000.0,  # $10 exacto — lanza
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
                return_value=2000.0,
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
                return_value=5000.0,  # $50 exacto — lanza
            ),
        ):
            from apps.api.simulator.cost_guard import check_global_cost_cap
            with pytest.raises(HTTPException) as exc_info:
                await check_global_cost_cap()
            assert exc_info.value.status_code == 429
            assert "global_daily_sim_cost_cap_exceeded" in str(exc_info.value.detail)
