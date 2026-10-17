"""Corridas lanzadas desde el panel (`POST /simulations/runs`)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

from apps.api.core.security import AuthContext
from apps.api.db.models import SimulationRun, SimulationScenario
from apps.api.routers import simulations
from apps.api.tests.conftest import make_fake_tenant_scope

TENANT = uuid4()


async def test_a_panel_run_is_traced_in_langsmith_like_the_cli(monkeypatch: Any) -> None:
    scenario = SimulationScenario(
        id=uuid4(), tenant_id=TENANT, name="CE-01", aop_slug="order_status",
        user_profile_id=uuid4(), expected_outcome="tracking",
    )
    run = SimulationRun(
        id=uuid4(), tenant_id=TENANT, aop_slug="order_status", status="passed",
        started_at=datetime.now(UTC),
    )
    observability = object()
    run_simulation = AsyncMock(return_value=run.id)
    deps = SimpleNamespace(anthropic=object(), observability=observability)
    monkeypatch.setattr(simulations, "tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(simulations, "get_simulation_scenario", AsyncMock(return_value=scenario))
    monkeypatch.setattr(simulations, "get_simulation_run", AsyncMock(return_value=run))
    for guard in ("check_tenant_cost_cap", "check_global_cost_cap", "check_tenant_run_rate_limit"):
        monkeypatch.setattr(simulations, guard, AsyncMock())
    monkeypatch.setattr(simulations, "_get_deps", lambda: deps)
    monkeypatch.setattr(simulations, "_get_graph", lambda: object())
    monkeypatch.setattr(simulations, "run_simulation", run_simulation)
    auth = AuthContext(user_id=uuid4(), tenant_id=None, role="super_admin", email="a@b.c")

    out = await simulations.create_run(
        simulations.RunRequest(scenario_id=scenario.id), auth, TENANT
    )

    assert out.status == "passed"
    assert run_simulation.await_args.kwargs["observability"] is observability
