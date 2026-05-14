"""Endpoints de escalaciones para agentes humanos."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id
from apps.api.db.client import tenant_scope
from apps.api.db.models import EscalationStatus
from apps.api.routers.conversations import EscalationOut
from apps.api.services.escalations import (
    claim_tenant_escalation,
    list_tenant_escalations,
    resolve_tenant_escalation,
)
from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/escalations", tags=["escalations"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]


# ----------------------------------------------------------------
# Response schemas
# ----------------------------------------------------------------


class EscalationListResponse:
    def __init__(self, escalations: list[EscalationOut], limit: int, offset: int) -> None:
        self.escalations = escalations
        self.limit = limit
        self.offset = offset


# ----------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------


@router.get(
    "",
    summary="Listar escalaciones del tenant",
)
async def list_escalations(
    tenant_id: TenantIdDep,
    status: Annotated[EscalationStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    async with tenant_scope(tenant_id) as conn:
        escalations = await list_tenant_escalations(
            conn, tenant_id, status=status, limit=limit, offset=offset
        )
    return {
        "escalations": [EscalationOut.model_validate(e) for e in escalations],
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/{escalation_id}/claim",
    response_model=EscalationOut,
    summary="Tomar una escalación pendiente",
)
async def claim(
    escalation_id: UUID,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> EscalationOut:
    async with tenant_scope(tenant_id) as conn:
        escalation = await claim_tenant_escalation(
            conn, tenant_id, escalation_id, auth.user_id
        )
    return EscalationOut.model_validate(escalation)


@router.post(
    "/{escalation_id}/resolve",
    response_model=EscalationOut,
    summary="Resolver una escalación claimed",
)
async def resolve(
    escalation_id: UUID,
    tenant_id: TenantIdDep,
) -> EscalationOut:
    async with tenant_scope(tenant_id) as conn:
        escalation = await resolve_tenant_escalation(conn, tenant_id, escalation_id)
    return EscalationOut.model_validate(escalation)
