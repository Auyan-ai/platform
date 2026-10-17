"""Router del simulador MVP.

Endpoints:
  POST /simulations/profiles             → crear perfil de cliente sintético
  POST /simulations/scenarios            → crear scenario
  GET  /simulations/scenarios            → listar scenarios del tenant
  GET  /simulations/scenarios/{id}/runs  → historial de runs de un scenario
  POST /simulations/runs                 → lanzar run SYNC (timeout 60s), retorna resultado
  GET  /simulations/runs/{run_id}        → estado y resultado de un run
  POST /simulations/batches              → lanzar batch ASYNC, retorna batch_id
  GET  /simulations/batches/{batch_id}   → listar runs del batch (polling)

Tenant gate: el run se atribuye al tenant del scenario.
super_admin puede operar cross-tenant con X-Tenant-Id.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Literal
from uuid import UUID, uuid4

from apps.api.core.errors import ForbiddenError, NotFoundError
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    get_simulation_run,
    get_simulation_scenario,
    get_user_profile,
    insert_simulation_scenario,
    insert_user_profile,
    list_runs_for_batch,
    list_runs_for_scenario,
    list_simulation_scenarios,
)
from apps.api.simulator.cost_guard import (
    check_global_cost_cap,
    check_tenant_batch_rate_limit,
    check_tenant_cost_cap,
    check_tenant_run_rate_limit,
)
from apps.api.simulator.runner import run_batch, run_simulation
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simulations", tags=["simulations"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]

RUN_SYNC_TIMEOUT_SECONDS = 60


# ─── Schemas ───────────────────────────────────────────────────────────────────


class CreateProfileRequest(BaseModel):
    name: str
    persona: dict = {}
    goal: str
    initial_message: str
    language: str = "es"


class CreateScenarioRequest(BaseModel):
    name: str
    description: str | None = None
    aop_slug: str
    user_profile_id: UUID
    expected_outcome: str
    mock_fixtures: dict = {}
    assertions: dict = {}
    max_turns: int = 8


class RunRequest(BaseModel):
    scenario_id: UUID
    judge_model: Literal["sonnet", "opus"] = "sonnet"


class BatchRequest(BaseModel):
    scenario_ids: list[UUID]
    judge_model: Literal["sonnet", "opus"] = "sonnet"


class ProfileOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    persona: dict
    goal: str
    initial_message: str
    language: str
    model_config = {"from_attributes": True}


class ScenarioOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None = None
    aop_slug: str
    user_profile_id: UUID
    expected_outcome: str
    mock_fixtures: dict
    assertions: dict
    max_turns: int
    is_active: bool
    model_config = {"from_attributes": True}


class RunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    scenario_id: UUID | None = None
    aop_slug: str
    status: str
    termination_reason: str | None = None
    turns_count: int | None = None
    transcript: list[dict] | None = None
    judge_eval: dict | None = None
    assertions_results: list[dict] | None = None
    assertions_passed: int | None = None
    assertions_total: int | None = None
    tokens_simulator: int = 0
    tokens_agent: int = 0
    tokens_judge: int = 0
    cost_cents: float | None = None
    started_at: str | None = None
    completed_at: str | None = None
    model_config = {"from_attributes": True}


class BatchCreatedOut(BaseModel):
    batch_id: UUID
    scenario_count: int


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _assert_tenant_access(auth: AuthContext, resource_tenant_id: UUID, name: str) -> None:
    if auth.role == "super_admin":
        return
    if auth.tenant_id != resource_tenant_id:
        raise ForbiddenError(
            f"cross_tenant_{name}_access_denied", code="cross_tenant_access_denied"
        )


def _run_to_out(run) -> dict:
    return {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "scenario_id": run.scenario_id,
        "aop_slug": run.aop_slug,
        "status": run.status,
        "termination_reason": run.termination_reason,
        "turns_count": run.turns_count,
        "transcript": run.transcript,
        "judge_eval": run.judge_eval,
        "assertions_results": run.assertions_results,
        "assertions_passed": run.assertions_passed,
        "assertions_total": run.assertions_total,
        "tokens_simulator": run.tokens_simulator or 0,
        "tokens_agent": run.tokens_agent or 0,
        "tokens_judge": run.tokens_judge or 0,
        "cost_cents": float(run.cost_cents) if run.cost_cents else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _get_deps():
    from apps.api.main import app
    return app.state.agent_deps


def _get_graph():
    from apps.api.main import app
    return app.state.agent_service._graph


# ─── Profiles ──────────────────────────────────────────────────────────────────


@router.post("/profiles", summary="Crear perfil de cliente sintético")
async def create_profile(body: CreateProfileRequest, tenant_id: TenantIdDep) -> ProfileOut:
    async with tenant_scope(tenant_id) as conn:
        profile = await insert_user_profile(
            conn,
            tenant_id=tenant_id,
            name=body.name,
            persona=body.persona,
            goal=body.goal,
            initial_message=body.initial_message,
            language=body.language,
        )
    return ProfileOut.model_validate(profile)


# ─── Scenarios ─────────────────────────────────────────────────────────────────


@router.post("/scenarios", summary="Crear scenario de simulación")
async def create_scenario(body: CreateScenarioRequest, tenant_id: TenantIdDep) -> ScenarioOut:
    async with tenant_scope(tenant_id) as conn:
        profile = await get_user_profile(conn, tenant_id, body.user_profile_id)
        if not profile:
            raise NotFoundError("user_profile_not_found", code="user_profile_not_found")
        scenario = await insert_simulation_scenario(
            conn,
            tenant_id=tenant_id,
            name=body.name,
            description=body.description,
            aop_slug=body.aop_slug,
            user_profile_id=body.user_profile_id,
            expected_outcome=body.expected_outcome,
            mock_fixtures=body.mock_fixtures,
            assertions=body.assertions,
            max_turns=body.max_turns,
        )
    return ScenarioOut.model_validate(scenario)


@router.get("/scenarios", summary="Listar scenarios del tenant")
async def list_scenarios(tenant_id: TenantIdDep) -> list[ScenarioOut]:
    async with tenant_scope(tenant_id) as conn:
        scenarios = await list_simulation_scenarios(conn, tenant_id)
    return [ScenarioOut.model_validate(s) for s in scenarios]


@router.get("/scenarios/{scenario_id}/runs", summary="Historial de runs de un scenario")
async def list_scenario_runs(
    scenario_id: UUID, auth: AuthDep, tenant_id: TenantIdDep
) -> list[RunOut]:
    async with tenant_scope(tenant_id) as conn:
        scenario = await get_simulation_scenario(conn, tenant_id, scenario_id)
        if not scenario:
            raise NotFoundError("scenario_not_found", code="scenario_not_found")
        _assert_tenant_access(auth, scenario.tenant_id, "scenario")
        runs = await list_runs_for_scenario(conn, tenant_id, scenario_id)
    return [RunOut(**_run_to_out(r)) for r in runs]


# ─── Runs ──────────────────────────────────────────────────────────────────────


@router.post("/runs", summary="Lanzar simulación (sync, timeout 60s)")
async def create_run(body: RunRequest, auth: AuthDep, tenant_id: TenantIdDep) -> RunOut:
    async with tenant_scope(tenant_id) as conn:
        scenario = await get_simulation_scenario(conn, tenant_id, body.scenario_id)
        if not scenario:
            raise NotFoundError("scenario_not_found", code="scenario_not_found")

    _assert_tenant_access(auth, scenario.tenant_id, "scenario")
    run_tenant_id = scenario.tenant_id

    await check_tenant_cost_cap(run_tenant_id)
    await check_global_cost_cap()
    await check_tenant_run_rate_limit(run_tenant_id)

    triggered_by = auth.user_id
    deps = _get_deps()
    graph = _get_graph()

    try:
        run_id = await asyncio.wait_for(
            run_simulation(
                body.scenario_id,
                run_tenant_id,
                anthropic=deps.anthropic,
                graph=graph,
                triggered_by=triggered_by,
                judge_model=body.judge_model,
                observability=deps.observability,
            ),
            timeout=RUN_SYNC_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "simulation_timeout",
                "message": f"La simulación superó {RUN_SYNC_TIMEOUT_SECONDS}s de timeout.",
            },
        ) from exc

    async with tenant_scope(run_tenant_id) as conn:
        run = await get_simulation_run(conn, run_tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=500, detail={"code": "run_not_found_after_completion"})
    return RunOut(**_run_to_out(run))


@router.get("/runs/{run_id}", summary="Estado y resultado de un run")
async def get_run(run_id: UUID, auth: AuthDep, tenant_id: TenantIdDep) -> RunOut:
    async with tenant_scope(tenant_id) as conn:
        run = await get_simulation_run(conn, tenant_id, run_id)
    if not run:
        raise NotFoundError("run_not_found", code="run_not_found")
    _assert_tenant_access(auth, run.tenant_id, "run")
    return RunOut(**_run_to_out(run))


# ─── Batches ───────────────────────────────────────────────────────────────────


@router.post("/batches", summary="Lanzar batch de scenarios (async, retorna batch_id)")
async def create_batch(
    body: BatchRequest,
    auth: AuthDep,
    tenant_id: TenantIdDep,
    background_tasks: BackgroundTasks,
) -> BatchCreatedOut:
    if not body.scenario_ids:
        raise HTTPException(status_code=422, detail="scenario_ids cannot be empty")

    async with tenant_scope(tenant_id) as conn:
        for sid in body.scenario_ids:
            sc = await get_simulation_scenario(conn, tenant_id, sid)
            if not sc:
                raise NotFoundError(f"scenario_not_found:{sid}", code="scenario_not_found")
            _assert_tenant_access(auth, sc.tenant_id, "scenario")

    await check_tenant_cost_cap(tenant_id)
    await check_global_cost_cap()
    await check_tenant_batch_rate_limit(tenant_id)

    triggered_by = auth.user_id
    deps = _get_deps()
    graph = _get_graph()
    batch_id = uuid4()

    async def _batch_task() -> None:
        try:
            await run_batch(
                body.scenario_ids,
                tenant_id,
                anthropic=deps.anthropic,
                graph=graph,
                triggered_by=triggered_by,
                judge_model=body.judge_model,
                observability=deps.observability,
            )
        except Exception:
            logger.exception("sim_background_batch_failed batch_id=%s", batch_id)

    background_tasks.add_task(_batch_task)
    return BatchCreatedOut(batch_id=batch_id, scenario_count=len(body.scenario_ids))


@router.get("/batches/{batch_id}", summary="Listar runs de un batch")
async def get_batch_runs(batch_id: UUID, auth: AuthDep, tenant_id: TenantIdDep) -> list[RunOut]:
    async with tenant_scope(tenant_id) as conn:
        runs = await list_runs_for_batch(conn, tenant_id, batch_id)
    for run in runs:
        _assert_tenant_access(auth, run.tenant_id, "run")
    return [RunOut(**_run_to_out(r)) for r in runs]
