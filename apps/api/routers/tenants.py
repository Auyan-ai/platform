"""Endpoints de tenant — perfil y configuración del tenant autenticado."""

from __future__ import annotations

import datetime
from typing import Annotated, Any
from uuid import UUID

from apps.api.core.config import get_settings
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id, require_role
from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.models import ChannelType
from apps.api.db.queries import (
    get_tenant_configuration,
    get_tenant_facts,
    get_tenant_playbook,
    get_tenant_usage_range,
    list_all_tenants,
    upsert_tenant_facts,
    upsert_tenant_playbook,
)
from apps.api.services.tenants import get_tenant, get_tenant_config, get_tenant_metrics
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/tenants", tags=["tenants"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]
SettingsDep = Annotated[object, Depends(get_settings)]


# ----------------------------------------------------------------
# Response schemas
# ----------------------------------------------------------------


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    status: str


class TenantConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    agent_model: str
    escalation_threshold: float
    active_channels: list[ChannelType]
    branding: dict
    extra: dict


class ConversationStatusCounts(BaseModel):
    open: int
    pending: int
    escalated: int
    resolved: int
    closed: int


class TenantMetricsResponse(BaseModel):
    total: int
    by_status: ConversationStatusCounts
    resolution_rate: float
    escalation_rate: float


class DailyUsage(BaseModel):
    date: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    request_count: int


class TenantUsageResponse(BaseModel):
    today: DailyUsage | None
    budget_usd_daily: float
    budget_used_pct: float
    days: int
    history: list[DailyUsage]


class TenantPlaybookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    brand_voice: str = ""
    product_overview: str = ""
    policies: str = ""
    escalation_notes: str = ""
    agent_instructions: str = ""
    version: int = 1
    last_edited_by: UUID | None = None
    updated_at: datetime.datetime | None = None


class TenantPlaybookUpdate(BaseModel):
    brand_voice: str = Field(default="", max_length=20_000)
    product_overview: str = Field(default="", max_length=20_000)
    policies: str = Field(default="", max_length=20_000)
    escalation_notes: str = Field(default="", max_length=20_000)
    agent_instructions: str = Field(default="", max_length=20_000)


class TenantFactsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    data: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    last_edited_by: UUID | None = None
    updated_at: datetime.datetime | None = None


class TenantFactsUpdate(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


# ----------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------


@router.get(
    "/admin/list",
    response_model=list[TenantResponse],
    summary="Listar todos los tenants — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def list_tenants_admin() -> list[TenantResponse]:
    async with bootstrap_connection() as conn:
        tenants = await list_all_tenants(conn)
    return [TenantResponse.model_validate(t) for t in tenants]


@router.get(
    "/me",
    response_model=TenantResponse,
    summary="Perfil del tenant del caller",
)
async def get_my_tenant(tenant_id: TenantIdDep) -> TenantResponse:
    async with tenant_scope(tenant_id) as conn:
        tenant = await get_tenant(conn, tenant_id)
    return TenantResponse.model_validate(tenant)


@router.get(
    "/me/config",
    response_model=TenantConfigResponse,
    summary="Configuración del tenant del caller",
)
async def get_my_tenant_config(tenant_id: TenantIdDep) -> TenantConfigResponse:
    async with tenant_scope(tenant_id) as conn:
        config = await get_tenant_config(conn, tenant_id)
    return TenantConfigResponse.model_validate(config)


@router.get(
    "/me/metrics",
    response_model=TenantMetricsResponse,
    summary="Métricas agregadas del tenant — conteos y tasas",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_tenant_metrics(tenant_id: TenantIdDep) -> TenantMetricsResponse:
    async with tenant_scope(tenant_id) as conn:
        data = await get_tenant_metrics(conn, tenant_id)
    return TenantMetricsResponse(
        total=data["total"],  # type: ignore[arg-type]
        by_status=ConversationStatusCounts(**data["by_status"]),  # type: ignore[arg-type]
        resolution_rate=data["resolution_rate"],  # type: ignore[arg-type]
        escalation_rate=data["escalation_rate"],  # type: ignore[arg-type]
    )


@router.get(
    "/me/usage",
    response_model=TenantUsageResponse,
    summary="Consumo de tokens y costo LLM del tenant — hoy y últimos N días",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_tenant_usage(
    tenant_id: TenantIdDep,
    settings: SettingsDep,
    days: int = Query(default=7, ge=1, le=90, description="Días de historial a retornar"),
) -> TenantUsageResponse:
    async with bootstrap_connection() as conn:
        tenant_config = await get_tenant_configuration(conn, tenant_id)

    async with tenant_scope(tenant_id) as conn:
        rows = await get_tenant_usage_range(conn, tenant_id=tenant_id, days=days)

    budget: float = settings.budget_usd_daily
    if tenant_config is not None:
        override = tenant_config.extra.get("budget_usd_daily")
        if isinstance(override, int | float) and override > 0:
            budget = float(override)

    history = [
        DailyUsage(
            date=row.date,
            tokens_in=row.tokens_in,
            tokens_out=row.tokens_out,
            cost_usd=float(row.cost_usd),
            request_count=row.request_count,
        )
        for row in rows
    ]

    today_str = datetime.date.today().isoformat()
    today = next((h for h in history if h.date == today_str), None)
    budget_used_pct = round(today.cost_usd / budget * 100, 1) if today and budget > 0 else 0.0

    return TenantUsageResponse(
        today=today,
        budget_usd_daily=budget,
        budget_used_pct=budget_used_pct,
        days=days,
        history=history,
    )


@router.get(
    "/me/playbook",
    response_model=TenantPlaybookResponse,
    summary="Playbook operativo del tenant — lectura cliente, edición Auyan",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_tenant_playbook(tenant_id: TenantIdDep) -> TenantPlaybookResponse:
    async with tenant_scope(tenant_id) as conn:
        playbook = await get_tenant_playbook(conn, tenant_id)
    if playbook is None:
        return TenantPlaybookResponse(tenant_id=tenant_id)
    return TenantPlaybookResponse.model_validate(playbook)


@router.put(
    "/me/playbook",
    response_model=TenantPlaybookResponse,
    summary="Actualiza el playbook operativo del tenant — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def update_my_tenant_playbook(
    body: TenantPlaybookUpdate,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> TenantPlaybookResponse:
    async with tenant_scope(tenant_id) as conn:
        playbook = await upsert_tenant_playbook(
            conn,
            tenant_id=tenant_id,
            brand_voice=body.brand_voice,
            product_overview=body.product_overview,
            policies=body.policies,
            escalation_notes=body.escalation_notes,
            agent_instructions=body.agent_instructions,
            edited_by=auth.user_id,
        )
    return TenantPlaybookResponse.model_validate(playbook)


@router.get(
    "/me/facts",
    response_model=TenantFactsResponse,
    summary="Datos factuales del tenant — usados como contexto estructurado del agente",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_tenant_facts(tenant_id: TenantIdDep) -> TenantFactsResponse:
    async with tenant_scope(tenant_id) as conn:
        facts = await get_tenant_facts(conn, tenant_id)
    if facts is None:
        return TenantFactsResponse(tenant_id=tenant_id)
    return TenantFactsResponse.model_validate(facts)


@router.put(
    "/me/facts",
    response_model=TenantFactsResponse,
    summary="Actualiza datos factuales del tenant",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def update_my_tenant_facts(
    body: TenantFactsUpdate,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> TenantFactsResponse:
    async with tenant_scope(tenant_id) as conn:
        facts = await upsert_tenant_facts(
            conn,
            tenant_id=tenant_id,
            data=body.data,
            edited_by=auth.user_id,
        )
    return TenantFactsResponse.model_validate(facts)
