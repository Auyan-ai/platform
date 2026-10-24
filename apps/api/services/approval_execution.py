"""Ejecución de una L3 aprobada: reclamarla, ejecutarla una vez, reconciliar y cerrar (#376).

Estados de `pending_approvals.status` (migración 20261018000003):

    pending ──aprobar (CAS)──▶ executing ──▶ approved   consta aplicada en el proveedor
       │                           ├──────▶ failed     una regla en código la rechazó, o no
       │                           │                   se puede saber si se aplicó: escala
       │                           └──────▶ pending    consta que no se aplicó
       └──rechazar (CAS)──▶ rejected

Solo ejecuta quien gana el CAS `pending → executing`. Tras un error, o si el proceso
murió con la aprobación en `executing`, se lee el proveedor (`Skill.reconcile`) y nunca
se repite a ciegas. Vuelve a `pending` solo lo que consta no aplicado: la mutación no
llegó a enviarse o el proveedor la rechazó (`MutationNotApplied`), o la recuperación lee
el proveedor pasado `STALE_EXECUTION`, cuando ya nada sigue en curso. Un error tras
enviarla con el proveedor sin mostrarla aplicada es `Unknown`: `orderCancel` es
asíncrono y un reembolso puede seguir en curso.

El mensaje al cliente se entrega después del COMMIT que lo registra: el cliente no
recibe "hecho" de algo que la base acabe revirtiendo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from apps.api.core.config import get_settings
from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.queries import (
    get_conversation,
    get_tenant_configuration,
    insert_message,
    list_all_tenants,
    list_stale_executing_approvals,
    settle_executing_approval,
    update_conversation_last_message,
)
from apps.api.integrations.base import MutationNotApplied
from apps.api.services.agent_resolution import finalize_agent_resolution
from apps.api.services.approval_reply import generate_customer_reply
from apps.api.services.approval_resolution import (
    hand_approval_to_team,
    release_escalations_after_executed_action,
    reply_delivered,
    team_followup_reason,
    unknown_outcome_reason,
)
from apps.api.services.commerce_context import build_commerce_integration_ctx
from apps.api.services.helpdesk_delivery import deliver_message_to_helpdesk
from apps.api.services.helpdesk_escalation import push_escalation_to_helpdesk_safe
from apps.api.services.language import conversation_text_languages
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillRefusal
from apps.api.skills.registry import SkillRegistry

if TYPE_CHECKING:
    from uuid import UUID

    import anthropic
    import asyncpg
    from apps.api.db.models import Conversation, Message, PendingApproval, PendingApprovalStatus

logger = logging.getLogger(__name__)

# Una `executing` más vieja que esto es de un proceso muerto: Cloud Run corta cada
# petición a los 300 s (`scripts/deploy_cloud_run.sh`).
STALE_EXECUTION = timedelta(minutes=15)


@dataclass(frozen=True)
class Applied:
    output: dict[str, Any]


@dataclass(frozen=True)
class Refused:
    refusal: SkillRefusal


@dataclass(frozen=True)
class NotApplied:
    error: str


@dataclass(frozen=True)
class Unknown:
    error: str


ExecutionResult = Applied | Refused | NotApplied | Unknown


@dataclass(frozen=True)
class Settlement:
    approval_status: PendingApprovalStatus
    execution_status: Literal["success", "refused", "failed", "unknown"]
    message_id: UUID | None
    output: dict[str, Any]
    # Motivo con el que el caso quedó escalado al equipo; None si no hizo falta.
    team_followup: str | None


@dataclass(frozen=True)
class ExecutionContext:
    skill_ctx: SkillContext
    language: str
    tenant_default: str


async def load_execution_context(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    approval: PendingApproval,
    skill_cls: type[Skill],
) -> ExecutionContext:
    """El mismo contexto que el grafo (creds de commerce e idioma), con la aprobación como
    clave de idempotencia para las skills que la usan."""
    tenant_config = await get_tenant_configuration(conn, tenant_id)
    extra = (tenant_config.extra if tenant_config else None) or {}
    integration_ctx = await build_commerce_integration_ctx(conn, tenant_id, extra=extra)
    language, tenant_default = await conversation_text_languages(
        conn, tenant_id, approval.conversation_id, extra
    )
    skill_ctx = SkillContext(
        language=language,
        default_language=tenant_default,
        tenant_id=str(tenant_id),
        conversation_id=str(approval.conversation_id),
        integration_ctx=integration_ctx,
        idempotency_key=str(approval.id) if skill_cls.requires_idempotency else None,
    )
    return ExecutionContext(skill_ctx, language, tenant_default)


async def execute_once(
    skill: Skill, ctx: SkillContext, inputs: SkillInput, *, earlier_attempt: bool
) -> ExecutionResult:
    """Ejecuta la skill. Si falla, no se sabe si la mutación llegó: se reconcilia.

    Un rechazo o un `MutationNotApplied` dicen que esta ejecución no tocó el proveedor.
    Si es el primer claim de la aprobación, lo que el proveedor muestre ya hecho lo hizo
    otro (el pedido ya estaba cancelado): no se reconcilia. Solo tras un intento anterior
    (`earlier_attempt`) puede ser obra de Auyan."""
    try:
        output = await skill.execute(ctx, inputs)
    except Exception as exc:
        logger.error(
            "approved_skill_execution_failed",
            extra={
                "skill": skill.slug,
                "conversation_id": ctx.conversation_id,
                "idempotency_key": ctx.idempotency_key,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        if not earlier_attempt and isinstance(exc, SkillRefusal):
            return Refused(exc)
        if not earlier_attempt and isinstance(exc, MutationNotApplied):
            return NotApplied(f"{type(exc).__name__}: {exc}")
        return await reconcile(skill, ctx, inputs, exc)
    return Applied(output.model_dump(mode="json"))


async def reconcile(
    skill: Skill, ctx: SkillContext, inputs: SkillInput, cause: Exception | None
) -> ExecutionResult:
    """Qué pasó con la ejecución, leído del proveedor. `cause` es el error de la
    ejecución, o None si el proceso murió a mitad (lo reconcilia la recuperación, pasado
    `STALE_EXECUTION`)."""
    error = f"{type(cause).__name__}: {cause}" if cause else "ejecución interrumpida"
    try:
        found = await skill.reconcile(ctx, inputs)
    except Exception as exc:
        if isinstance(cause, SkillRefusal):
            return Refused(cause)
        if isinstance(cause, MutationNotApplied):
            return NotApplied(error)
        return Unknown(f"{error}; al comprobarlo: {type(exc).__name__}: {exc}")
    if found is not None:
        return Applied(found.model_dump(mode="json"))
    if isinstance(cause, SkillRefusal):
        return Refused(cause)
    if cause is None or isinstance(cause, MutationNotApplied):
        return NotApplied(error)
    return Unknown(f"{error}; tras enviarla, el proveedor aún no la muestra aplicada")


async def settle(
    *,
    tenant_id: UUID,
    approval: PendingApproval,
    result: ExecutionResult,
    language: str,
    tenant_default: str,
    anthropic_client: anthropic.AsyncAnthropic | None,
) -> Settlement | None:
    """Cierra la ejecución con el CAS desde `executing` y, ya committed, avisa al cliente y
    al helpdesk. None si otro ya la había cerrado: entonces no escribe ni entrega nada."""
    match result:
        case Applied(output=output):
            return await _settle_applied(
                tenant_id, approval, output, language, tenant_default, anthropic_client
            )
        case Refused(refusal=refusal):
            return await _settle_refused(tenant_id, approval, refusal)
        case NotApplied(error=error):
            async with tenant_scope(tenant_id) as conn:
                reopened = await settle_executing_approval(
                    conn,
                    tenant_id=tenant_id,
                    approval_id=approval.id,
                    execution_attempt=approval.execution_attempt,
                    new_status="pending",
                )
            if reopened is None:
                return None
            return Settlement("pending", "failed", None, {"error": error}, None)
        case Unknown(error=error):
            return await _settle_unknown(tenant_id, approval, error)


async def _settle_applied(
    tenant_id: UUID,
    approval: PendingApproval,
    output: dict[str, Any],
    language: str,
    tenant_default: str,
    anthropic_client: anthropic.AsyncAnthropic | None,
) -> Settlement | None:
    # Ejecutada pero sin cerrar (reembolso manual o fallido, cambio que no aparece):
    # el equipo tiene que rematarla.
    followup = team_followup_reason(approval.skill_slug, output)
    content = await generate_customer_reply(
        anthropic_client,
        approval.skill_slug,
        success=True,
        output=output,
        language=language,
        tenant_default=tenant_default,
    )
    async with tenant_scope(tenant_id) as conn:
        settled = await settle_executing_approval(
            conn,
            tenant_id=tenant_id,
            approval_id=approval.id,
            execution_attempt=approval.execution_attempt,
            new_status="approved",
        )
        if settled is None:
            return None
        msg = await record_outcome_message(
            conn,
            settled,
            content,
            {"execution_status": "success", "skill_output": output},
        )
        if followup is None:
            await release_escalations_after_executed_action(
                conn,
                tenant_id=tenant_id,
                conversation_id=approval.conversation_id,
                approval_id=approval.id,
            )
        else:
            await hand_approval_to_team(
                conn,
                tenant_id=tenant_id,
                conversation_id=approval.conversation_id,
                approval_id=approval.id,
                reason=followup,
            )
        conversation = await get_conversation(conn, tenant_id, approval.conversation_id)

    delivered = await deliver_after_commit(tenant_id, conversation, content, msg.id)
    if conversation is not None:
        if followup is not None:
            logger.warning(
                "approved_action_needs_team",
                extra={
                    "approval_id": str(approval.id),
                    "skill": approval.skill_slug,
                    "conversation_id": str(approval.conversation_id),
                    "outcome": output.get("outcome"),
                },
            )
            await push_escalation_to_helpdesk_safe(
                tenant_id=tenant_id, conversation=conversation, reason=followup
            )
        else:
            # Resolución autónoma solo con la confirmación entregada.
            await finalize_agent_resolution(
                tenant_id=tenant_id,
                conversation=conversation,
                delivered=reply_delivered(conversation.channel, delivered=delivered),
                settings=get_settings(),
            )
    return Settlement("approved", "success", msg.id, output, followup)


async def _settle_refused(
    tenant_id: UUID, approval: PendingApproval, refusal: SkillRefusal
) -> Settlement | None:
    """Una regla en código impide la acción (p. ej. el pedido salió mientras esperaba):
    el cliente recibe el texto fijo de la regla y el equipo, su razón."""
    async with tenant_scope(tenant_id) as conn:
        settled = await settle_executing_approval(
            conn,
            tenant_id=tenant_id,
            approval_id=approval.id,
            execution_attempt=approval.execution_attempt,
            new_status="failed",
        )
        if settled is None:
            return None
        msg = await record_outcome_message(
            conn,
            settled,
            refusal.customer_message,
            {"execution_status": "refused", "refusal_code": refusal.code},
        )
        await hand_approval_to_team(
            conn,
            tenant_id=tenant_id,
            conversation_id=approval.conversation_id,
            approval_id=approval.id,
            reason=refusal.team_reason,
        )
        conversation = await get_conversation(conn, tenant_id, approval.conversation_id)

    await deliver_after_commit(tenant_id, conversation, refusal.customer_message, msg.id)
    if conversation is not None:
        await push_escalation_to_helpdesk_safe(
            tenant_id=tenant_id, conversation=conversation, reason=refusal.team_reason
        )
    return Settlement(
        "failed", "refused", msg.id, {"error": str(refusal)}, refusal.team_reason
    )


async def _settle_unknown(
    tenant_id: UUID, approval: PendingApproval, error: str
) -> Settlement | None:
    """No se sabe si la acción se aplicó: nada al cliente y el caso al equipo, que lo
    comprueba en el proveedor. Nunca se reintenta solo."""
    reason = unknown_outcome_reason(approval.skill_slug, approval.inputs_raw, error)
    async with tenant_scope(tenant_id) as conn:
        settled = await settle_executing_approval(
            conn,
            tenant_id=tenant_id,
            approval_id=approval.id,
            execution_attempt=approval.execution_attempt,
            new_status="failed",
        )
        if settled is None:
            return None
        await hand_approval_to_team(
            conn,
            tenant_id=tenant_id,
            conversation_id=approval.conversation_id,
            approval_id=approval.id,
            reason=reason,
        )
        conversation = await get_conversation(conn, tenant_id, approval.conversation_id)
    logger.error(
        "approved_action_outcome_unknown",
        extra={"approval_id": str(approval.id), "skill": approval.skill_slug, "error": error},
    )
    if conversation is not None:
        await push_escalation_to_helpdesk_safe(
            tenant_id=tenant_id, conversation=conversation, reason=reason
        )
    return Settlement("failed", "unknown", None, {"error": error}, reason)


async def record_outcome_message(
    conn: asyncpg.Connection,
    approval: PendingApproval,
    content: str,
    metadata: dict[str, Any],
) -> Message:
    """El mensaje del resultado en la conversación, firmado por el operador que decidió
    (role 'agent_human' exige autor: constraint messages_human_has_author)."""
    msg = await insert_message(
        conn,
        tenant_id=approval.tenant_id,
        conversation_id=approval.conversation_id,
        role="agent_human",
        direction="outbound",
        content=content,
        author_user_id=approval.reviewed_by,
        metadata={"approval_id": str(approval.id), "skill_slug": approval.skill_slug, **metadata},
    )
    await update_conversation_last_message(conn, approval.tenant_id, approval.conversation_id)
    return msg


async def deliver_after_commit(
    tenant_id: UUID, conversation: Conversation | None, content: str, message_id: UUID
) -> bool:
    """Entrega al canal del cliente un mensaje ya committed. Best-effort, como el webhook."""
    if conversation is None:
        return False
    async with tenant_scope(tenant_id) as conn:
        return await deliver_message_to_helpdesk(
            conn,
            tenant_id=tenant_id,
            conversation=conversation,
            content=content,
            message_id=message_id,
        )


async def recover_execution(tenant_id: UUID, approval: PendingApproval) -> Settlement | None:
    """Cierra una `executing` cuyo proceso murió, solo con lo que diga el proveedor."""
    skill_cls = SkillRegistry.get(approval.skill_slug)
    inputs = skill_cls.input_schema.model_validate(approval.inputs_raw)
    async with tenant_scope(tenant_id) as conn:
        run = await load_execution_context(conn, tenant_id, approval, skill_cls)
    result = await reconcile(skill_cls(), run.skill_ctx, inputs, cause=None)
    logger.warning(
        "approval_execution_recovered",
        extra={
            "approval_id": str(approval.id),
            "skill": approval.skill_slug,
            "result": type(result).__name__,
        },
    )
    return await settle(
        tenant_id=tenant_id,
        approval=approval,
        result=result,
        language=run.language,
        tenant_default=run.tenant_default,
        anthropic_client=None,
    )


async def recover_stale_executions(*, now: datetime | None = None) -> int:
    """Reconcilia las aprobaciones que llevan más de `STALE_EXECUTION` en `executing`.
    Lo llama el job de limpieza. Devuelve cuántas cerró."""
    started_before = (now or datetime.now(UTC)) - STALE_EXECUTION
    async with bootstrap_connection() as conn:
        tenants = await list_all_tenants(conn)
    recovered = 0
    for tenant in tenants:
        async with tenant_scope(tenant.id) as conn:
            stale = await list_stale_executing_approvals(
                conn, tenant.id, started_before=started_before
            )
        for approval in stale:
            try:
                if await recover_execution(tenant.id, approval) is not None:
                    recovered += 1
            except Exception:
                logger.exception(
                    "approval_recovery_failed",
                    extra={"tenant_id": str(tenant.id), "approval_id": str(approval.id)},
                )
    return recovered
