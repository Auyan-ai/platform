"""Endpoints de aprobaciones humanas para skills L3.

Flujo:
  1. El agente detecta skill L3 + human_approval_required → crea pending_approval.
  2. Aparece en GET /approvals (filtrado por status=pending por defecto).
  3. El agente humano revisa los inputs (redactados) y aprueba o rechaza.
  4. POST /approvals/{id}/approve → reclama la aprobación (CAS pending → executing),
     ejecuta la skill una vez y cierra con el resultado: mensaje, escalaciones y, con la
     confirmación entregada, la resolución (`services/approval_execution.py`).
  5. POST /approvals/{id}/reject → CAS pending → rejected + mensaje de rechazo
     + resuelve la escalación del gate (la conversación vuelve a 'open').
Quien llega tarde a cualquiera de los dos CAS recibe 409 sin efectos.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from apps.api.core.errors import ConflictError, ForbiddenError, NotFoundError
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id
from apps.api.db.client import tenant_scope
from apps.api.db.models import PendingApproval, PendingApprovalStatus
from apps.api.db.queries import (
    claim_pending_approval,
    get_conversation,
    get_pending_approval,
    get_tenant_configuration,
    is_simulation_conversation,
    list_pending_approvals,
    reject_pending_approval,
)
from apps.api.services.approval_execution import (
    Applied,
    deliver_after_commit,
    execute_once,
    load_execution_context,
    record_outcome_message,
    settle,
)
from apps.api.services.approval_reply import generate_customer_reply
from apps.api.services.approval_resolution import release_approval_escalation
from apps.api.services.language import conversation_text_languages
from apps.api.skills.registry import SkillRegistry
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    import asyncpg

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
    # inputs_redacted: copia forense (PII pseudonimizada). inputs_raw: datos reales
    # que el operador necesita para decidir (ej. la dirección a la que enviar). La
    # API ya aísla por tenant; el operador revisa a su propio cliente.
    inputs_redacted: dict
    inputs_raw: dict
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


async def _reviewable_approval(
    conn: asyncpg.Connection, tenant_id: UUID, approval_id: UUID
) -> PendingApproval:
    """La aprobación que el operador puede aprobar o rechazar, o el error de dominio."""
    approval = await get_pending_approval(conn, tenant_id, approval_id)
    if not approval:
        raise NotFoundError(f"approval {approval_id} not found", code="approval_not_found")
    if approval.status != "pending":
        raise _not_pending(approval.status)
    # Lo que nace en el simulador nunca toca la tienda ni el helpdesk del cliente (#348).
    if await is_simulation_conversation(conn, tenant_id, approval.conversation_id):
        raise ForbiddenError(
            "La aprobación viene de una simulación: no se ejecuta ni se resuelve",
            code="simulated_approval",
        )
    return approval


def _not_pending(status: str | None) -> ConflictError:
    shown = f"status={status}" if status else "otra petición se adelantó"
    return ConflictError(
        f"La aprobación ya no está pendiente ({shown})", code="approval_not_pending"
    )


# ----------------------------------------------------------------
# POST /approvals/{id}/approve
# ----------------------------------------------------------------


@router.post("/{approval_id}/approve", summary="Aprobar y ejecutar skill L3")
async def approve_action(
    approval_id: UUID,
    body: ApproveRequest,
    request: Request,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> dict:
    """Reclama la aprobación (`pending → executing`), ejecuta la skill una vez y cierra
    con el resultado (`services/approval_execution.py`). Quien no gana el CAS recibe 409
    sin ejecutar nada."""
    async with tenant_scope(tenant_id) as conn:
        approval = await _reviewable_approval(conn, tenant_id, approval_id)

    try:
        skill_cls = SkillRegistry.get(approval.skill_slug)
    except ValueError as exc:
        raise NotFoundError(
            f"skill not found: {approval.skill_slug}", code="skill_not_found"
        ) from exc
    try:
        inputs = skill_cls.input_schema.model_validate(approval.inputs_raw)
    except ValidationError as exc:
        logger.error(
            "approval_inputs_invalid",
            extra={"approval_id": str(approval_id), "skill": approval.skill_slug},
        )
        return {
            "approval_id": str(approval_id),
            "approval_status": "pending",
            "execution_status": "failed",
            "message_id": None,
            "output": {"error": str(exc)},
            "team_followup": None,
        }

    async with tenant_scope(tenant_id) as conn:
        claimed = await claim_pending_approval(
            conn,
            tenant_id=tenant_id,
            approval_id=approval_id,
            reviewed_by=auth.user_id,
            review_comment=body.comment,
        )
        if claimed is None:
            raise _not_pending(None)
        # Dentro de la transacción del claim: si cargar el contexto falla, el claim se
        # deshace y la aprobación sigue pendiente sin haber tocado la tienda.
        run = await load_execution_context(conn, tenant_id, claimed, skill_cls)

    t0 = time.monotonic()
    result = await execute_once(skill_cls(), run.skill_ctx, inputs)
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Observabilidad: la ejecución real de la L3 queda en skill_audit_log con su
    # resultado, latencia y la aprobación como clave de idempotencia.
    agent_deps = getattr(request.app.state, "agent_deps", None)
    auditor = getattr(agent_deps, "audit_logger", None)
    if auditor is not None:
        applied = isinstance(result, Applied)
        auditor.log(
            tenant_id=tenant_id,
            conversation_id=approval.conversation_id,
            aop_slug=approval.aop_slug,
            aop_version=approval.aop_version,
            skill_slug=approval.skill_slug,
            skill_tier=approval.skill_tier,
            inputs_raw=approval.inputs_raw,
            status="success" if applied else "failed",
            outputs=result.output if isinstance(result, Applied) else None,
            idempotency_key=approval_id,
            error_message=None if applied else repr(result),
            latency_ms=latency_ms,
        )

    settlement = await settle(
        tenant_id=tenant_id,
        approval=claimed,
        result=result,
        language=run.language,
        tenant_default=run.tenant_default,
        anthropic_client=getattr(agent_deps, "anthropic", None),
    )
    if settlement is None:
        raise ConflictError(
            "Otro proceso cerró esta ejecución mientras corría",
            code="approval_settled_elsewhere",
        )
    return {
        "approval_id": str(approval_id),
        "approval_status": settlement.approval_status,
        "execution_status": settlement.execution_status,
        "message_id": str(settlement.message_id) if settlement.message_id else None,
        "output": settlement.output,
        "team_followup": settlement.team_followup,
    }


# ----------------------------------------------------------------
# POST /approvals/{id}/reject
# ----------------------------------------------------------------


@router.post("/{approval_id}/reject", summary="Rechazar skill L3 sin ejecutar")
async def reject_action(
    approval_id: UUID,
    body: RejectRequest,
    request: Request,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> dict:
    """Rechaza solo desde `pending` (CAS comprobado): una aprobación que se está
    ejecutando devuelve 409 y el cliente no recibe "rechazada"."""
    async with tenant_scope(tenant_id) as conn:
        approval = await _reviewable_approval(conn, tenant_id, approval_id)
        tenant_config = await get_tenant_configuration(conn, tenant_id)
        language, tenant_default = await conversation_text_languages(
            conn,
            tenant_id,
            approval.conversation_id,
            tenant_config.extra if tenant_config else None,
        )
    # Mensaje al cliente: natural y sin jerga interna (Haiku, con fallback a plantilla).
    # Se redacta fuera de la transacción para no retener la fila durante la llamada.
    reply = await generate_customer_reply(
        getattr(getattr(request.app.state, "agent_deps", None), "anthropic", None),
        approval.skill_slug,
        success=False,
        reject_comment=body.comment,
        language=language,
        tenant_default=tenant_default,
    )
    async with tenant_scope(tenant_id) as conn:
        rejected = await reject_pending_approval(
            conn,
            tenant_id=tenant_id,
            approval_id=approval_id,
            reviewed_by=auth.user_id,
            review_comment=body.comment,
        )
        if rejected is None:
            raise _not_pending(None)
        msg = await record_outcome_message(conn, rejected, reply, {"execution_status": "rejected"})
        # Cierra la escalación del gate; la conversación vuelve a 'open' esperando al
        # cliente (sin resolución: la acción no se hizo).
        await release_approval_escalation(
            conn,
            tenant_id=tenant_id,
            conversation_id=approval.conversation_id,
            approval_id=approval_id,
        )
        conversation = await get_conversation(conn, tenant_id, approval.conversation_id)

    await deliver_after_commit(tenant_id, conversation, reply, msg.id)
    return {
        "approval_id": str(approval_id),
        "approval_status": "rejected",
        "execution_status": "rejected",
        "message_id": str(msg.id),
    }
