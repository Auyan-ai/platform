"""Endpoints de aprobaciones humanas para skills L3.

Flujo:
  1. El agente detecta skill L3 + human_approval_required → crea pending_approval.
  2. Aparece en GET /approvals (filtrado por status=pending por defecto).
  3. El agente humano revisa los inputs (redactados) y aprueba o rechaza.
  4. POST /approvals/{id}/approve → ejecuta la skill + inserta mensaje + cierra aprobación.
  5. POST /approvals/{id}/reject → inserta mensaje de rechazo + cierra aprobación.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from apps.api.core.errors import ForbiddenError, NotFoundError
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id
from apps.api.db.client import tenant_scope
from apps.api.db.models import PendingApprovalStatus
from apps.api.db.queries import (
    get_pending_approval,
    get_tenant_configuration,
    insert_message,
    list_pending_approvals,
    resolve_pending_approval,
    update_conversation_last_message,
)
from apps.api.services.commerce_context import build_commerce_integration_ctx
from apps.api.skills.base import SkillContext
from apps.api.skills.registry import SkillRegistry
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approvals", tags=["approvals"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]


# ----------------------------------------------------------------
# Schemas de request / response
# ----------------------------------------------------------------


class ApprovalOut(BaseModel):
    id: UUID
    conversation_id: UUID
    skill_slug: str
    skill_tier: str
    inputs_redacted: dict
    aop_slug: str
    aop_version: int
    status: str
    reviewed_by: UUID | None = None
    reviewed_at: str | None = None
    review_comment: str | None = None
    created_at: str | None = None

    model_config = {"from_attributes": True}


class ApproveRequest(BaseModel):
    comment: str | None = None


class RejectRequest(BaseModel):
    comment: str


# ----------------------------------------------------------------
# GET /approvals
# ----------------------------------------------------------------


@router.get("", summary="Listar aprobaciones pendientes del tenant")
async def list_approvals(
    tenant_id: TenantIdDep,
    status: Annotated[PendingApprovalStatus | None, Query()] = "pending",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    async with tenant_scope(tenant_id) as conn:
        approvals = await list_pending_approvals(
            conn, tenant_id, status=status, limit=limit, offset=offset
        )
    return {
        "approvals": [ApprovalOut.model_validate(a.model_dump(mode="json")) for a in approvals],
        "limit": limit,
        "offset": offset,
    }


# ----------------------------------------------------------------
# GET /approvals/{id}
# ----------------------------------------------------------------


@router.get("/{approval_id}", summary="Detalle de una aprobación")
async def get_approval(
    approval_id: UUID,
    tenant_id: TenantIdDep,
) -> ApprovalOut:
    async with tenant_scope(tenant_id) as conn:
        approval = await get_pending_approval(conn, tenant_id, approval_id)
    if not approval:
        raise NotFoundError(f"approval {approval_id} not found", code="approval_not_found")
    return ApprovalOut.model_validate(approval.model_dump(mode="json"))


# ----------------------------------------------------------------
# POST /approvals/{id}/approve
# ----------------------------------------------------------------


@router.post("/{approval_id}/approve", summary="Aprobar y ejecutar skill L3")
async def approve_action(
    approval_id: UUID,
    body: ApproveRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> dict:
    """Aprueba la pending_approval, ejecuta la skill y añade el resultado a la conversación."""
    async with tenant_scope(tenant_id) as conn:
        approval = await get_pending_approval(conn, tenant_id, approval_id)
        if not approval:
            raise NotFoundError(f"approval {approval_id} not found", code="approval_not_found")
        if approval.status != "pending":
            raise ForbiddenError(
                f"La aprobación ya fue resuelta con status={approval.status}",
                code="approval_not_pending",
            )

        tenant_config = await get_tenant_configuration(conn, tenant_id)
        extra = (tenant_config.extra if tenant_config else None) or {}
        # Mismo camino que el grafo: creds desde tenant_integrations (cifradas +
        # token exchange Shopify), fallback legacy a tenant_config.extra.
        integration_ctx = await build_commerce_integration_ctx(conn, tenant_id, extra=extra)

    # Construir SkillContext con el IntegrationContext del tenant
    skill_ctx = SkillContext(
        tenant_id=str(tenant_id),
        conversation_id=str(approval.conversation_id),
        integration_ctx=integration_ctx,
    )

    # Resolver y ejecutar la skill
    try:
        skill_cls = SkillRegistry.get(approval.skill_slug)
    except ValueError as exc:
        raise NotFoundError(
            f"skill not found: {approval.skill_slug}", code="skill_not_found"
        ) from exc

    try:
        validated_input = skill_cls.input_schema.model_validate(approval.inputs_raw)
        skill_instance = skill_cls()
        output = await skill_instance.execute(skill_ctx, validated_input)
        output_data = output.model_dump(mode="json")
        execution_status = "success"
        result_message = f"Acción completada: {approval.skill_slug}. Resultado: {output_data}"
    except Exception as exc:
        logger.warning(
            "approved_skill_execution_failed",
            extra={
                "approval_id": str(approval_id),
                "skill": approval.skill_slug,
                "error": str(exc),
            },
        )
        output_data = {"error": str(exc)}
        execution_status = "failed"
        result_message = (
            f"La acción {approval.skill_slug} fue aprobada pero falló al ejecutarse: {exc}"
        )

    # Marcar aprobada y añadir mensaje a la conversación
    async with tenant_scope(tenant_id) as conn:
        await resolve_pending_approval(
            conn,
            tenant_id=tenant_id,
            approval_id=approval_id,
            new_status="approved",
            reviewed_by=auth.user_id,
            review_comment=body.comment,
        )
        msg = await insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=approval.conversation_id,
            role="agent_human",
            direction="outbound",
            content=result_message,
            metadata={
                "approval_id": str(approval_id),
                "skill_slug": approval.skill_slug,
                "execution_status": execution_status,
                "skill_output": output_data,
            },
        )
        await update_conversation_last_message(conn, tenant_id, approval.conversation_id)

    return {
        "approval_id": str(approval_id),
        "execution_status": execution_status,
        "message_id": str(msg.id),
        "output": output_data,
    }


# ----------------------------------------------------------------
# POST /approvals/{id}/reject
# ----------------------------------------------------------------


@router.post("/{approval_id}/reject", summary="Rechazar skill L3 sin ejecutar")
async def reject_action(
    approval_id: UUID,
    body: RejectRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> dict:
    async with tenant_scope(tenant_id) as conn:
        approval = await get_pending_approval(conn, tenant_id, approval_id)
        if not approval:
            raise NotFoundError(f"approval {approval_id} not found", code="approval_not_found")
        if approval.status != "pending":
            raise ForbiddenError(
                f"La aprobación ya fue resuelta con status={approval.status}",
                code="approval_not_pending",
            )

        await resolve_pending_approval(
            conn,
            tenant_id=tenant_id,
            approval_id=approval_id,
            new_status="rejected",
            reviewed_by=auth.user_id,
            review_comment=body.comment,
        )
        msg = await insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=approval.conversation_id,
            role="agent_human",
            direction="outbound",
            content=(
                f"La solicitud de {approval.skill_slug} fue revisada y no se realizará. "
                f"Motivo: {body.comment}"
            ),
            metadata={
                "approval_id": str(approval_id),
                "skill_slug": approval.skill_slug,
                "execution_status": "rejected",
            },
        )
        await update_conversation_last_message(conn, tenant_id, approval.conversation_id)

    return {
        "approval_id": str(approval_id),
        "execution_status": "rejected",
        "message_id": str(msg.id),
    }
