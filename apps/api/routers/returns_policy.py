"""Política de devoluciones y cambios del tenant (ADR 0014 §3).

La define y edita el cliente (`tenant_admin`); el `super_admin` también, con `X-Tenant-Id`.
Cada guardado es una versión nueva con autor: la tabla es el historial de cambios.
"""

from __future__ import annotations

import datetime
import logging
from typing import Annotated
from uuid import UUID

from apps.api.core.errors import ConflictError
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id, require_role
from apps.api.db.client import tenant_scope
from apps.api.db.returns_policy import (
    StaleVersionError,
    get_current_returns_policy,
    insert_returns_policy_version,
    list_returns_policy_versions,
)
from apps.api.services.returns_policy import ReturnsPolicy, parse_stored_policy
from fastapi import APIRouter, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenants/me/returns-policy",
    tags=["returns-policy"],
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]


class PolicyVersionOut(BaseModel):
    version: int
    edited_by_email: str | None
    created_at: datetime.datetime


class ReturnsPolicyResponse(BaseModel):
    tenant_id: UUID
    policy: ReturnsPolicy | None
    version: int | None
    updated_at: datetime.datetime | None
    edited_by_email: str | None
    history: list[PolicyVersionOut]


class ReturnsPolicyUpdate(BaseModel):
    policy: ReturnsPolicy
    # Versión que se estaba editando (None = no había política): evita pisar otra edición.
    expected_version: int | None


async def _read(tenant_id: UUID) -> ReturnsPolicyResponse:
    async with tenant_scope(tenant_id) as conn:
        current = await get_current_returns_policy(conn, tenant_id)
        history = await list_returns_policy_versions(conn, tenant_id)
    return ReturnsPolicyResponse(
        tenant_id=tenant_id,
        policy=parse_stored_policy(current.policy) if current else None,
        version=current.version if current else None,
        updated_at=current.created_at if current else None,
        edited_by_email=current.edited_by_email if current else None,
        history=[
            PolicyVersionOut(
                version=h.version, edited_by_email=h.edited_by_email, created_at=h.created_at
            )
            for h in history
        ],
    )


@router.get("", response_model=ReturnsPolicyResponse, summary="Política de devoluciones vigente")
async def get_returns_policy(tenant_id: TenantIdDep) -> ReturnsPolicyResponse:
    return await _read(tenant_id)


@router.put("", response_model=ReturnsPolicyResponse, summary="Guarda una versión nueva")
async def put_returns_policy(
    body: ReturnsPolicyUpdate, tenant_id: TenantIdDep, auth: AuthDep
) -> ReturnsPolicyResponse:
    try:
        async with tenant_scope(tenant_id) as conn:
            version = await insert_returns_policy_version(
                conn,
                tenant_id,
                policy=body.policy.model_dump(mode="json"),
                schema_version=body.policy.schema_version,
                expected_version=body.expected_version,
                edited_by=auth.user_id,
            )
    except StaleVersionError as exc:
        raise ConflictError(
            f"La política cambió mientras la editabas (versión vigente: {exc.current}). "
            "Recarga y vuelve a aplicar tus cambios.",
            code="returns_policy_stale",
        ) from exc
    logger.info(
        "returns_policy_saved",
        extra={"tenant_id": str(tenant_id), "version": version, "user_id": str(auth.user_id)},
    )
    return await _read(tenant_id)
