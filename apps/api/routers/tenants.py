"""Endpoints de tenant — perfil y configuración del tenant autenticado."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from apps.api.core.config import Settings, get_settings
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id, require_role
from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.models import ChannelType
from apps.api.db.queries import get_tenant_usage_today, list_all_tenants
from apps.api.services.tenants import get_tenant, get_tenant_config, get_tenant_metrics
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/tenants", tags=["tenants"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]


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


class TenantUsageResponse(BaseModel):
    date: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    request_count: int
    budget_usd: float
    budget_used_pct: float


@router.get(
    "/me/usage",
    response_model=TenantUsageResponse,
    summary="Consumo de hoy del tenant — tokens, costo y % del presupuesto",
)
async def get_my_tenant_usage(
    tenant_id: TenantIdDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> TenantUsageResponse:
    async with tenant_scope(tenant_id) as conn:
        config = await get_tenant_config(conn, tenant_id)
        usage = await get_tenant_usage_today(conn, tenant_id=tenant_id)

    budget = float(config.extra.get("budget_usd_daily", settings.budget_usd_daily))
    if usage is None:
        return TenantUsageResponse(
            date="",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            request_count=0,
            budget_usd=budget,
            budget_used_pct=0.0,
        )

    pct = min(100.0, round(usage.cost_usd / budget * 100, 1)) if budget > 0 else 0.0
    return TenantUsageResponse(
        date=usage.date,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        cost_usd=round(usage.cost_usd, 4),
        request_count=usage.request_count,
        budget_usd=budget,
        budget_used_pct=pct,
    )
