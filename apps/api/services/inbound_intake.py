"""Intake de un mensaje inbound de helpdesk: persistir + encolar en UNA transacción (#260).

Lo comparten los webhooks de Zendesk, Gorgias y Chatwoot. Dentro de la misma
transacción (`tenant_scope`):

    1. Reclamar la key de idempotencia (ON CONFLICT: un reintento concurrente espera y
       sale como duplicado; si la transacción cae no queda key y el reintento reprocesa).
       Luego advisory locks por ticket y por email: dos mensajes simultáneos del mismo
       ticket nuevo no crean dos veces el cliente ni la conversación.
    2. Upsert del end_customer (por email).
    3. Find-or-create de la conversación por (channel, external_id); reabrir si estaba
       resuelta.
    4. INSERT del mensaje inbound.
    5. Encolar el turno en `inbound_jobs`.

El webhook responde 200 en cuanto esto confirma; el grafo corre en
`services/inbound_worker.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
    find_conversation_by_external,
    find_end_customer_by_email,
    insert_message,
    update_conversation_last_message,
)
from apps.api.services.conversations import reopen_if_resolved

if TYPE_CHECKING:
    from uuid import UUID

    from apps.api.db.models import ChannelType
    from fastapi import Request

logger = logging.getLogger(__name__)


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
        )
        customer = None
        if customer_email:
            customer = await find_end_customer_by_email(conn, tenant_id, customer_email)
        if customer is None:
            customer = await create_end_customer(
                conn,
                tenant_id=tenant_id,
                email=customer_email,
                external_id=None,
                full_name=customer_name,
            )

        conversation = await find_conversation_by_external(conn, tenant_id, channel, external_id)
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

        inbound = await insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="customer",
            direction="inbound",
            content=content,
            metadata=message_metadata,
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


def notify_inbound_worker(request: Request) -> None:
    """Despierta al worker en proceso (si está corriendo). El job es durable: si no hay
    worker vivo, el siguiente sondeo o la siguiente instancia lo recoge."""
    worker = getattr(request.app.state, "inbound_worker", None)
    if worker is not None:
        worker.notify()
