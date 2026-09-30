"""Entrega al comprador consciente de la ventana de los canales de mensajería.

- Helpdesk (Zendesk/Gorgias/Chatwoot): `send_outbound` directo, como siempre.
- Mensajería (WhatsApp):
  - ventana **abierta** → se envía con `Idempotency-Key` = id del mensaje persistido y se
    guarda el wamid (`metadata.zernio_platform_message_ids`) para cruzar `message.failed`;
  - ventana **cerrada** → plantilla de re-enganche del tenant (una sola por chat mientras
    haya pendientes) y el mensaje queda `metadata.delivery = "pending_window"`. Se entrega
    cuando el comprador contesta (`flush_pending_messages`, en el worker, antes del grafo).
  - sin plantilla configurada, o si falla → `failed` + `logger.error`.

Todo es código determinista (regla dura del Sprint 2): el LLM no decide nada aquí.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from apps.api.core.errors import ExternalIntegrationError
from apps.api.db.queries import (
    get_active_handoff_for_chat,
    get_end_customer,
    list_pending_window_messages,
    merge_message_metadata,
)
from apps.api.services.channel_routing import is_messaging_channel, load_delivery_client
from apps.api.services.handoff import add_handoff_note
from apps.api.services.messaging_window import window_state

if TYPE_CHECKING:
    from uuid import UUID

    import asyncpg
    from apps.api.db.models import Conversation
    from apps.api.integrations.base import IntegrationContext

logger = logging.getLogger(__name__)

DeliveryResult = Literal["delivered", "pending_window", "failed"]

# `{{1}}` de la plantilla de re-enganche cuando no conocemos el nombre:
# "Hola de nuevo, tenemos una respuesta sobre tu consulta…"
REENGAGEMENT_FALLBACK_NAME = "de nuevo"

NOTE_PENDING_WINDOW = (
    "Ventana de WhatsApp cerrada: enviamos la plantilla de re-enganche; tu respuesta se "
    "entregará cuando el cliente conteste."
)
NOTE_REENGAGEMENT_FAILED = (
    "⚠️ Ventana de WhatsApp cerrada y NO se pudo enviar la plantilla de re-enganche "
    "({code}). El mensaje no llegó al cliente."
)


async def _note_on_active_handoff(
    conn: asyncpg.Connection, tenant_id: UUID, conversation: Conversation, content: str
) -> None:
    """Si hay un handoff activo en el chat, deja la nota interna en su ticket."""
    handoff = await get_active_handoff_for_chat(
        conn, tenant_id, conversation.channel, str(conversation.external_id)
    )
    if handoff is not None:
        await add_handoff_note(tenant_id=tenant_id, handoff=handoff, content=content)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _error_code(exc: Exception) -> str:
    return exc.code if isinstance(exc, ExternalIntegrationError) else type(exc).__name__


def _first_name(full_name: str | None) -> str:
    if not full_name or not full_name.strip():
        return REENGAGEMENT_FALLBACK_NAME
    return full_name.strip().split()[0][:40]


def _platform_ids(results: Any) -> list[str]:
    if not isinstance(results, list):
        return []
    return [str(r.message_id) for r in results if getattr(r, "message_id", None)]


async def deliver_to_customer(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation: Conversation,
    content: str,
    message_id: UUID | None,
) -> DeliveryResult:
    """Entrega `content` (ya persistido como `message_id`) al comprador. Nunca lanza."""
    log_extra = {
        "tenant_id": str(tenant_id),
        "conversation_id": str(conversation.id),
        "channel": conversation.channel,
        "message_id": str(message_id) if message_id else None,
    }
    try:
        client = await load_delivery_client(conn, tenant_id=tenant_id, conversation=conversation)
    except Exception:
        logger.error("channel_delivery_client_failed", extra=log_extra, exc_info=True)
        return "failed"
    if client is None:
        logger.warning("channel_delivery_no_route", extra=log_extra)
        return "failed"
    adapter, ctx = client

    if not is_messaging_channel(conversation.channel):
        try:
            await adapter.send_outbound(ctx, str(conversation.external_id), content)
        except Exception:
            logger.error("channel_delivery_failed", extra=log_extra, exc_info=True)
            return "failed"
        return "delivered"

    window = await window_state(conn, tenant_id=tenant_id, conversation=conversation)
    if window.open:
        return await _send_now(
            conn,
            adapter,
            ctx,
            tenant_id=tenant_id,
            conversation=conversation,
            content=content,
            message_id=message_id,
            log_extra=log_extra,
        )
    return await _park_until_customer_replies(
        conn,
        adapter,
        ctx,
        tenant_id=tenant_id,
        conversation=conversation,
        message_id=message_id,
        log_extra=log_extra,
    )


async def _send_now(
    conn: asyncpg.Connection,
    adapter: Any,
    ctx: IntegrationContext,
    *,
    tenant_id: UUID,
    conversation: Conversation,
    content: str,
    message_id: UUID | None,
    log_extra: dict[str, Any],
) -> DeliveryResult:
    try:
        results = await adapter.send_outbound(
            ctx,
            str(conversation.external_id),
            content,
            idempotency_key=str(message_id) if message_id else None,
        )
    except Exception as exc:
        logger.error("channel_delivery_failed", extra=log_extra, exc_info=True)
        if message_id:
            await merge_message_metadata(
                conn,
                tenant_id,
                message_id,
                {"delivery": "failed", "delivery_error": {"code": _error_code(exc)}},
            )
        return "failed"
    if message_id:
        await merge_message_metadata(
            conn,
            tenant_id,
            message_id,
            {
                "delivery": "delivered",
                "delivered_at": _now_iso(),
                "zernio_platform_message_ids": _platform_ids(results),
            },
        )
    return "delivered"


async def _park_until_customer_replies(
    conn: asyncpg.Connection,
    adapter: Any,
    ctx: IntegrationContext,
    *,
    tenant_id: UUID,
    conversation: Conversation,
    message_id: UUID | None,
    log_extra: dict[str, Any],
) -> DeliveryResult:
    """Ventana cerrada: plantilla de re-enganche (si no se mandó ya) + mensaje pendiente."""
    if message_id is None:
        logger.error("channel_delivery_window_closed_without_message", extra=log_extra)
        return "failed"
    already_pending = await list_pending_window_messages(
        conn, tenant_id, conversation.channel, str(conversation.external_id)
    )
    template_ids: list[str] = []
    if not any(m.id != message_id for m in already_pending):
        customer = await get_end_customer(conn, tenant_id, conversation.end_customer_id)
        try:
            result = await adapter.send_reengagement_template(
                ctx,
                str(conversation.external_id),
                first_name=_first_name(customer.full_name if customer else None),
                idempotency_key=f"reengage:{message_id}",
            )
        except Exception as exc:
            logger.error(
                "channel_delivery_reengagement_failed",
                extra={**log_extra, "error_code": _error_code(exc)},
                exc_info=True,
            )
            await merge_message_metadata(
                conn,
                tenant_id,
                message_id,
                {
                    "delivery": "failed",
                    "delivery_error": {"code": _error_code(exc), "phase": "reengagement"},
                },
            )
            await _note_on_active_handoff(
                conn,
                tenant_id,
                conversation,
                NOTE_REENGAGEMENT_FAILED.format(code=_error_code(exc)),
            )
            return "failed"
        template_ids = [result.message_id] if getattr(result, "message_id", None) else []
    await merge_message_metadata(
        conn,
        tenant_id,
        message_id,
        {
            "delivery": "pending_window",
            "pending_since": _now_iso(),
            "reengagement_platform_message_ids": template_ids,
        },
    )
    logger.info(
        "channel_delivery_pending_window",
        extra={**log_extra, "template_sent": bool(template_ids)},
    )
    await _note_on_active_handoff(conn, tenant_id, conversation, NOTE_PENDING_WINDOW)
    return "pending_window"


async def flush_pending_messages(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation: Conversation,
) -> int:
    """Entrega, en orden, los mensajes que esperaban la ventana del chat. Nunca lanza.

    Se llama en el worker justo después de un inbound del comprador (ventana recién
    abierta), antes del grafo. Devuelve cuántos se entregaron.
    """
    if not is_messaging_channel(conversation.channel) or not conversation.external_id:
        return 0
    pending = await list_pending_window_messages(
        conn, tenant_id, conversation.channel, conversation.external_id
    )
    if not pending:
        return 0
    try:
        client = await load_delivery_client(conn, tenant_id=tenant_id, conversation=conversation)
    except Exception:
        logger.error(
            "pending_flush_client_failed", extra={"tenant_id": str(tenant_id)}, exc_info=True
        )
        return 0
    if client is None:
        logger.error("pending_flush_no_route", extra={"tenant_id": str(tenant_id)})
        return 0
    adapter, ctx = client
    delivered = 0
    for message in pending:
        extra = {"tenant_id": str(tenant_id), "message_id": str(message.id)}
        try:
            results = await adapter.send_outbound(
                ctx, conversation.external_id, message.content, idempotency_key=str(message.id)
            )
        except Exception as exc:
            logger.error("pending_flush_failed", extra=extra, exc_info=True)
            await merge_message_metadata(
                conn,
                tenant_id,
                message.id,
                {"delivery": "failed", "delivery_error": {"code": _error_code(exc)}},
            )
            continue
        await merge_message_metadata(
            conn,
            tenant_id,
            message.id,
            {
                "delivery": "delivered",
                "delivered_at": _now_iso(),
                "zernio_platform_message_ids": _platform_ids(results),
            },
        )
        delivered += 1
    logger.info(
        "pending_flush_done",
        extra={"tenant_id": str(tenant_id), "delivered": delivered, "pending": len(pending)},
    )
    return delivered
