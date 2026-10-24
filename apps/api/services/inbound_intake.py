"""Intake de un mensaje inbound de helpdesk: persistir + encolar en UNA transacción (#260).

Lo comparten los webhooks de Zendesk, Gorgias y Chatwoot. Dentro de la misma
transacción (`tenant_scope`):

    1. Reclamar la key de idempotencia (ON CONFLICT: un reintento concurrente espera y
       sale como duplicado; si la transacción cae no queda key y el reintento reprocesa).
       Luego advisory locks por ticket y por email: dos mensajes simultáneos del mismo
       ticket nuevo no crean dos veces el cliente ni la conversación.
    2. Resolver el end_customer: id externo del canal (BSUID de WhatsApp) → teléfono →
       email → crear. Si se encuentra por teléfono/email se completan los identificadores
       que falten (nunca se sobrescriben).
    3. Find-or-create de la conversación por (channel, external_id); reabrir si estaba
       resuelta. En mensajería (WhatsApp) el chat no termina: se abre una **sesión** nueva
       si la última está cerrada o resuelta hace más de `reopen_window_days`.
    4. INSERT del mensaje inbound, con su `identity_evidence` (ADR 0013): el contacto del
       remitente que el origen del mensaje verifica.
    5. Encolar el turno en `inbound_jobs`.

El webhook responde 200 en cuanto esto confirma; el grafo corre en
`services/inbound_worker.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from apps.api.db.client import tenant_scope
from apps.api.db.inbound_jobs import (
    claim_webhook_idempotency_key,
    enqueue_inbound_job,
    lock_inbound_intake,
)
from apps.api.db.queries import (
    create_conversation,
    create_end_customer,
    fill_end_customer_identity,
    find_conversation_by_external,
    find_end_customer_by_email,
    find_end_customer_by_external_id,
    find_end_customer_by_phone,
    get_billing_subscription,
    insert_message,
    update_conversation_last_message,
)
from apps.api.services.channel_routing import is_messaging_channel
from apps.api.services.conversations import reopen_if_resolved
from apps.api.services.identity import EVIDENCE_KEY, build_identity_evidence
from apps.api.services.identity_guest import PROVIDED_CONTACT_KEY, build_provided_contact

if TYPE_CHECKING:
    from uuid import UUID

    import asyncpg
    from apps.api.db.models import ChannelType, Conversation, EndCustomer
    from fastapi import Request

logger = logging.getLogger(__name__)

DEFAULT_REOPEN_WINDOW_DAYS = 7
_FINISHED_STATUSES = frozenset({"closed", "closed_abandoned"})


@dataclass(frozen=True)
class InboundIntakeResult:
    duplicate: bool
    conversation_id: UUID | None = None
    job_id: UUID | None = None

    def response(self) -> dict[str, Any]:
        """Cuerpo del 200 del webhook."""
        if self.duplicate:
            return {"received": True, "processed": False, "duplicate": True}
        return {"received": True, "queued": True, "job_id": str(self.job_id)}


def _with_identity_metadata(
    metadata: dict[str, Any], evidence: dict[str, str] | None, email: str | None
) -> dict[str, Any]:
    """Metadata del inbound con la evidencia del remitente (ADR 0013).

    Si el origen no verifica el email (chat), el que tecleó el visitante se guarda aparte
    como dato aportado: sirve para el nivel `guest`, nunca como remitente.
    """
    if evidence:
        return {**metadata, EVIDENCE_KEY: evidence}
    provided = build_provided_contact(email)
    return {**metadata, PROVIDED_CONTACT_KEY: provided} if provided else metadata


async def persist_and_enqueue_inbound(
    *,
    tenant_id: UUID,
    channel: ChannelType,
    external_id: str,
    idempotency_key: str,
    request_path: str,
    content: str,
    customer_email: str | None,
    customer_name: str | None,
    subject: str | None,
    message_metadata: dict[str, Any],
    customer_phone: str | None = None,
    customer_external_id: str | None = None,
) -> InboundIntakeResult:
    async with tenant_scope(tenant_id) as conn:
        claimed = await claim_webhook_idempotency_key(
            conn, tenant_id=tenant_id, key=idempotency_key, request_path=request_path
        )
        if not claimed:
            logger.info(
                "inbound_webhook_duplicate",
                extra={"tenant_id": str(tenant_id), "channel": channel, "key": idempotency_key},
            )
            return InboundIntakeResult(duplicate=True)

        await lock_inbound_intake(
            conn,
            tenant_id=tenant_id,
            channel=channel,
            external_id=external_id,
            customer_email=customer_email,
            customer_phone=customer_phone,
            customer_external_id=customer_external_id,
        )
        customer = await resolve_end_customer(
            conn,
            tenant_id=tenant_id,
            email=customer_email,
            phone=customer_phone,
            external_id=customer_external_id,
            full_name=customer_name,
        )

        conversation = await find_conversation_by_external(conn, tenant_id, channel, external_id)
        if conversation is not None and is_messaging_channel(channel):
            if not await _session_is_reusable(conn, tenant_id, conversation):
                conversation = None
        if conversation is None:
            conversation = await create_conversation(
                conn,
                tenant_id=tenant_id,
                end_customer_id=customer.id,
                channel=channel,
                external_id=external_id,
                subject=subject,
            )
        else:
            # El cliente volvió a escribir: si estaba resuelta, reactivarla.
            conversation = await reopen_if_resolved(conn, tenant_id, conversation)

        evidence = build_identity_evidence(
            channel,
            message_metadata.get("source_channel"),
            email=customer_email,
            phone=customer_phone,
        )
        inbound = await insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="customer",
            direction="inbound",
            content=content,
            metadata=_with_identity_metadata(message_metadata, evidence, customer_email),
        )
        await update_conversation_last_message(conn, tenant_id, conversation.id)

        job_id = await enqueue_inbound_job(
            conn,
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            inbound_message_id=inbound.id,
            end_customer_id=customer.id,
            channel=channel,
        )

    logger.info(
        "inbound_enqueued",
        extra={
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation.id),
            "channel": channel,
            "job_id": str(job_id),
        },
    )
    return InboundIntakeResult(duplicate=False, conversation_id=conversation.id, job_id=job_id)


async def resolve_end_customer(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    email: str | None,
    phone: str | None,
    external_id: str | None,
    full_name: str | None,
) -> EndCustomer:
    """external_id (BSUID) → teléfono → email → crear. Determinista y sin sobrescribir.

    Al encontrar al cliente por un identificador se le completan los que falten, salvo
    que ese valor ya pertenezca a OTRO cliente del tenant (los índices únicos lo
    impedirían): entonces se deja como está y se loguea.
    """
    customer = None
    if external_id:
        customer = await find_end_customer_by_external_id(conn, tenant_id, external_id)
    if customer is None and phone:
        customer = await find_end_customer_by_phone(conn, tenant_id, phone)
    if customer is None and email:
        customer = await find_end_customer_by_email(conn, tenant_id, email)
    if customer is None:
        return await create_end_customer(
            conn,
            tenant_id=tenant_id,
            email=email,
            phone=phone,
            external_id=external_id,
            full_name=full_name,
        )

    fill_phone = phone if phone and not customer.phone else None
    if fill_phone and await find_end_customer_by_phone(conn, tenant_id, fill_phone):
        logger.warning(
            "end_customer_phone_owned_by_other",
            extra={"tenant_id": str(tenant_id), "customer_id": str(customer.id)},
        )
        fill_phone = None
    fill_external = external_id if external_id and not customer.external_id else None
    if fill_external and await find_end_customer_by_external_id(conn, tenant_id, fill_external):
        logger.warning(
            "end_customer_external_id_owned_by_other",
            extra={"tenant_id": str(tenant_id), "customer_id": str(customer.id)},
        )
        fill_external = None
    if fill_phone or fill_external:
        updated = await fill_end_customer_identity(
            conn, tenant_id, customer.id, phone=fill_phone, external_id=fill_external
        )
        if updated is not None:
            return updated
    return customer


async def _session_is_reusable(
    conn: asyncpg.Connection, tenant_id: UUID, conversation: Conversation
) -> bool:
    """¿El nuevo mensaje del chat sigue en esta sesión? (solo canales de mensajería)

    No si está cerrada (`closed`/`closed_abandoned`) ni si se resolvió hace más de
    `reopen_window_days` (de la suscripción de billing del tenant; 7 si no hay).
    """
    if conversation.status in _FINISHED_STATUSES:
        return False
    if conversation.status != "resolved" or conversation.resolved_at is None:
        return True
    subscription = await get_billing_subscription(conn, tenant_id)
    window_days = (
        subscription.reopen_window_days if subscription is not None else DEFAULT_REOPEN_WINDOW_DAYS
    )
    resolved_at = conversation.resolved_at
    if resolved_at.tzinfo is None:
        resolved_at = resolved_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - resolved_at <= timedelta(days=window_days)


def notify_inbound_worker(request: Request) -> None:
    """Despierta al worker en proceso (si está corriendo). El job es durable: si no hay
    worker vivo, el siguiente sondeo o la siguiente instancia lo recoge."""
    worker = getattr(request.app.state, "inbound_worker", None)
    if worker is not None:
        worker.notify()
