"""Endpoints de aprobaciones humanas para skills L3.

Flujo:
  1. El agente detecta skill L3 + human_approval_required → crea pending_approval.
  2. Aparece en GET /approvals (filtrado por status=pending por defecto).
  3. El agente humano revisa los inputs (redactados) y aprueba o rechaza.
  4. POST /approvals/{id}/approve → ejecuta la skill + inserta mensaje + cierra aprobación
     + resuelve la escalación del gate y, si la confirmación llegó, la conversación.
  5. POST /approvals/{id}/reject → inserta mensaje de rechazo + cierra aprobación
     + resuelve la escalación del gate (la conversación vuelve a 'open').
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from apps.api.core.config import get_settings
from apps.api.core.errors import ForbiddenError, NotFoundError
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id
from apps.api.db.client import tenant_scope
from apps.api.db.models import PendingApproval, PendingApprovalStatus
from apps.api.db.queries import (
    get_conversation,
    get_pending_approval,
    get_tenant_configuration,
    insert_message,
    is_simulation_conversation,
    list_pending_approvals,
    resolve_pending_approval,
    update_conversation_last_message,
)
from apps.api.services.agent_resolution import finalize_agent_resolution
from apps.api.services.approval_reply import generate_customer_reply
from apps.api.services.approval_resolution import (
    hand_executed_action_to_team,
    release_approval_escalation,
    release_escalations_after_executed_action,
    reply_delivered,
    team_followup_reason,
)
from apps.api.services.commerce_context import build_commerce_integration_ctx
from apps.api.services.helpdesk_delivery import deliver_message_to_helpdesk
from apps.api.services.helpdesk_escalation import push_escalation_to_helpdesk_safe
from apps.api.services.language import conversation_text_languages
from apps.api.skills.base import SkillContext
from apps.api.skills.registry import SkillRegistry
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

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
        raise ForbiddenError(
            f"La aprobación ya fue resuelta con status={approval.status}",
            code="approval_not_pending",
        )
    # Lo que nace en el simulador nunca toca la tienda ni el helpdesk del cliente (#348).
    if await is_simulation_conversation(conn, tenant_id, approval.conversation_id):
        raise ForbiddenError(
            "La aprobación viene de una simulación: no se ejecuta ni se resuelve",
            code="simulated_approval",
        )
    return approval


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
    """Aprueba la pending_approval, ejecuta la skill y añade el resultado a la conversación."""
    async with tenant_scope(tenant_id) as conn:
        approval = await _reviewable_approval(conn, tenant_id, approval_id)

        tenant_config = await get_tenant_configuration(conn, tenant_id)
        extra = (tenant_config.extra if tenant_config else None) or {}
        # Mismo camino que el grafo: creds desde tenant_integrations (cifradas +
        # token exchange Shopify), fallback legacy a tenant_config.extra.
        integration_ctx = await build_commerce_integration_ctx(conn, tenant_id, extra=extra)
        language, tenant_default = await conversation_text_languages(
            conn, tenant_id, approval.conversation_id, extra
        )

    # Construir SkillContext con el IntegrationContext del tenant
    skill_ctx = SkillContext(
        language=language,
        default_language=tenant_default,
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

    error_message: str | None = None
    t0 = time.monotonic()
    try:
        validated_input = skill_cls.input_schema.model_validate(approval.inputs_raw)
        skill_instance = skill_cls()
        output = await skill_instance.execute(skill_ctx, validated_input)
        output_data = output.model_dump(mode="json")
        execution_status = "success"
    except Exception as exc:
        logger.error(
            "approved_skill_execution_failed",
            extra={
                "approval_id": str(approval_id),
                "skill": approval.skill_slug,
                "conversation_id": str(approval.conversation_id),
                "error": str(exc),
            },
        )
        output_data = {"error": str(exc)}
        execution_status = "failed"
        error_message = str(exc)
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Observabilidad: la EJECUCIÓN real de la skill L3 al aprobar dejaba el grafo
    # sin rastro (solo quedaba el gate como rejected_by_permissions). Registramos
    # la ejecución en skill_audit_log con su status real, latencia y outputs.
    auditor = getattr(getattr(request.app.state, "agent_deps", None), "audit_logger", None)
    if auditor is not None:
        auditor.log(
            tenant_id=tenant_id,
            conversation_id=approval.conversation_id,
            aop_slug=approval.aop_slug,
            aop_version=approval.aop_version,
            skill_slug=approval.skill_slug,
            skill_tier=approval.skill_tier,
            inputs_raw=approval.inputs_raw,
            status=execution_status,
            outputs=output_data if execution_status == "success" else None,
            idempotency_key=approval_id,
            error_message=error_message,
            latency_ms=latency_ms,
        )

    # La ejecución falló (p.ej. error de la API del proveedor). NO marcamos la
    # aprobación como 'approved' ni le mandamos al cliente una confirmación: eso
    # enmascararía el fallo. La dejamos 'pending' para que siga en la cola del
    # operador y pueda reintentarse; el gate L3 ya le avisó al cliente que un
    # agente revisaría su solicitud. El error queda logueado arriba (nivel error)
    # y en la respuesta para que el dashboard lo muestre.
    if execution_status == "failed":
        return {
            "approval_id": str(approval_id),
            "execution_status": execution_status,
            "message_id": None,
            "output": output_data,
        }

    # Ejecutada. Si la skill releyó el pedido y no quedó cerrado (reembolso manual o
    # fallido, cambio que no aparece), el equipo tiene que rematarla.
    followup = team_followup_reason(approval.skill_slug, output_data)

    # Mensaje al cliente sin jerga interna: plantilla fija por resultado o Haiku con
    # fallback a plantilla. output_data crudo queda solo en metadata.
    anthropic_client = getattr(getattr(request.app.state, "agent_deps", None), "anthropic", None)
    result_message = await generate_customer_reply(
        anthropic_client,
        approval.skill_slug,
        success=True,
        output=output_data,
        language=language,
        tenant_default=tenant_default,
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
            # role 'agent_human' exige autor (constraint messages_human_has_author):
            # lo firma el operador que aprobó.
            author_user_id=auth.user_id,
            metadata={
                "approval_id": str(approval_id),
                "skill_slug": approval.skill_slug,
                "execution_status": execution_status,
                "skill_output": output_data,
            },
        )
        await update_conversation_last_message(conn, tenant_id, approval.conversation_id)
        if followup is None:
            # Acción ejecutada: se cierran todas las escalaciones abiertas de la
            # conversación (la del gate y cualquier escalado previo por la misma
            # petición) y vuelve a 'open'.
            await release_escalations_after_executed_action(
                conn,
                tenant_id=tenant_id,
                conversation_id=approval.conversation_id,
            )
        else:
            await hand_executed_action_to_team(
                conn,
                tenant_id=tenant_id,
                conversation_id=approval.conversation_id,
                approval_id=approval_id,
                reason=followup,
            )
        # Entregar el resultado al helpdesk del cliente (el mensaje ya quedó en DB).
        conversation = await get_conversation(conn, tenant_id, approval.conversation_id)
        delivered = False
        if conversation is not None:
            delivered = reply_delivered(
                conversation.channel,
                delivered=await deliver_message_to_helpdesk(
                    conn,
                    tenant_id=tenant_id,
                    conversation=conversation,
                    content=result_message,
                    message_id=msg.id,
                ),
            )

    if followup is not None:
        logger.warning(
            "approved_action_needs_team",
            extra={
                "approval_id": str(approval_id),
                "skill": approval.skill_slug,
                "conversation_id": str(approval.conversation_id),
                "outcome": output_data.get("outcome"),
            },
        )
        if conversation is not None:
            await push_escalation_to_helpdesk_safe(
                tenant_id=tenant_id, conversation=conversation, reason=followup
            )
    # Acción ejecutada y confirmada → resolución (resolved + resolution event + cierre
    # del ticket). Sin entrega confirmada queda abierta, igual que en el webhook.
    elif conversation is not None:
        await finalize_agent_resolution(
            tenant_id=tenant_id,
            conversation=conversation,
            delivered=delivered,
            settings=get_settings(),
        )

    return {
        "approval_id": str(approval_id),
        "execution_status": execution_status,
        "message_id": str(msg.id),
        "output": output_data,
        # Motivo con el que la acción quedó escalada al equipo; None si quedó cerrada.
        "team_followup": followup,
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
    async with tenant_scope(tenant_id) as conn:
        approval = await _reviewable_approval(conn, tenant_id, approval_id)

        await resolve_pending_approval(
            conn,
            tenant_id=tenant_id,
            approval_id=approval_id,
            new_status="rejected",
            reviewed_by=auth.user_id,
            review_comment=body.comment,
        )
        tenant_config = await get_tenant_configuration(conn, tenant_id)
        language, tenant_default = await conversation_text_languages(
            conn,
            tenant_id,
            approval.conversation_id,
            tenant_config.extra if tenant_config else None,
        )
        # Mensaje al cliente: natural y sin jerga interna (Haiku, con fallback a plantilla).
        anthropic_client = getattr(
            getattr(request.app.state, "agent_deps", None), "anthropic", None
        )
        reply = await generate_customer_reply(
            anthropic_client,
            approval.skill_slug,
            success=False,
            reject_comment=body.comment,
            language=language,
            tenant_default=tenant_default,
        )
        msg = await insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=approval.conversation_id,
            role="agent_human",
            direction="outbound",
            content=reply,
            # role 'agent_human' exige autor (constraint messages_human_has_author).
            author_user_id=auth.user_id,
            metadata={
                "approval_id": str(approval_id),
                "skill_slug": approval.skill_slug,
                "execution_status": "rejected",
            },
        )
        await update_conversation_last_message(conn, tenant_id, approval.conversation_id)
        # Cierra la escalación del gate; la conversación vuelve a 'open' esperando al
        # cliente (sin resolución: la acción no se hizo).
        await release_approval_escalation(
            conn,
            tenant_id=tenant_id,
            conversation_id=approval.conversation_id,
            approval_id=approval_id,
        )
        # Entregar el rechazo al helpdesk del cliente (best-effort).
        conversation = await get_conversation(conn, tenant_id, approval.conversation_id)
        if conversation is not None:
            await deliver_message_to_helpdesk(
                conn,
                tenant_id=tenant_id,
                conversation=conversation,
                content=reply,
                message_id=msg.id,
            )

    return {
        "approval_id": str(approval_id),
        "execution_status": "rejected",
        "message_id": str(msg.id),
    }
