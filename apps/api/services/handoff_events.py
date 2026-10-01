"""Vuelta del handoff: eventos del helpdesk y toma desde el móvil (ADR 0010, PR-5).

- `handle_helpdesk_event` — webhook del helpdesk para un ticket de handoff:
  - `handoff_reply`: comentario PÚBLICO de un agente → mensaje `agent_human` con autor
    externo → entrega por WhatsApp respetando la ventana (plantilla + pendiente + nota
    interna si está cerrada). Nunca se reenvían comentarios privados, del requester (son
    los mensajes del comprador que Auyan copió al ticket) ni del usuario API de Auyan.
  - `handoff_solved`: cierra el handoff, sus escalaciones y deja la conversación
    `resolved` **sin** `resolution_event` (resolución humana: no se factura). No se manda
    nada al comprador: lo decide el humano.
- `handle_device_takeover` — la marca contestó desde la app de WhatsApp Business
  (coexistence) o desde el inbox de Zernio: se registra y la IA calla `device_hold_hours`.

Idempotencia: `zendesk_handoff:{ticket}:{comment}` y `zernio:{event_id}` en la misma tabla
de idempotencia que el intake; los envíos a Zernio llevan `Idempotency-Key`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import asyncpg
from apps.api.db.client import tenant_scope
from apps.api.db.inbound_jobs import claim_webhook_idempotency_key
from apps.api.db.queries import (
    find_conversation_by_external,
    find_outbound_message_by_platform_id,
    get_active_handoff_for_chat,
    get_conversation,
    get_handoff_by_ticket,
    insert_handoff,
    insert_message,
    mark_conversation_resolved,
    reactivate_escalated_conversation,
    reopen_handoff_row,
    resolve_open_escalations_for_conversation,
    touch_handoff_human_activity,
    update_conversation_last_message,
)
from apps.api.services.channel_delivery import deliver_to_customer
from apps.api.services.handoff import add_handoff_note, close_handoff

if TYPE_CHECKING:
    from uuid import UUID

    from apps.api.db.models import ConversationHandoff, TenantConfiguration
    from apps.api.integrations.base import IntegrationContext
    from apps.api.integrations.zernio import ZernioEvent

logger = logging.getLogger(__name__)

DEFAULT_DEVICE_HOLD_HOURS = 12
DEVICE_SOURCES = frozenset({"whatsapp_business_app"})
NOTE_DELIVERY_FAILED = (
    "⚠️ No se pudo entregar tu respuesta por WhatsApp ({reason}). El cliente NO la recibió."
)


def _ignored(reason: str) -> dict[str, Any]:
    return {"received": True, "processed": False, "ignored": reason}


def _ignored_reply(
    reason: str, extra: dict[str, Any], *, level: int = logging.INFO
) -> dict[str, Any]:
    """Descarte de un comentario del helpdesk: nunca en silencio (s81: una respuesta
    humana se perdía sin rastro)."""
    logger.log(level, "handoff_reply_ignored", extra={**extra, "reason": reason})
    return _ignored(reason)


async def _latest_session(
    conn: asyncpg.Connection, tenant_id: UUID, handoff: ConversationHandoff
) -> Any:
    """Sesión viva más reciente del chat del handoff (el comprador puede haber abierto otra)."""
    conversation = await get_conversation(conn, tenant_id, handoff.conversation_id)
    if conversation is None or not conversation.external_id:
        return conversation
    latest = await find_conversation_by_external(
        conn, tenant_id, conversation.channel, conversation.external_id
    )
    return latest or conversation


# ─── Helpdesk → WhatsApp ──────────────────────────────────────────────────────


async def handle_helpdesk_event(
    *,
    tenant_id: UUID,
    provider: str,
    adapter: Any,
    ctx: IntegrationContext,
    ticket_id: str,
    comment_id: str | None,
    event: str | None,
) -> dict[str, Any]:
    """Evento del helpdesk sobre un ticket de handoff. NUNCA pasa al intake normal."""
    async with tenant_scope(tenant_id) as conn:
        handoff = await get_handoff_by_ticket(conn, tenant_id, provider, ticket_id)
    if handoff is None:
        logger.warning(
            "handoff_event_without_handoff",
            extra={"tenant_id": str(tenant_id), "ticket_id": ticket_id, "event": event},
        )
        return _ignored("handoff_not_found")
    if event == "handoff_solved":
        return await _on_helpdesk_solved(tenant_id, handoff)
    return await _on_helpdesk_reply(tenant_id, provider, adapter, ctx, handoff, comment_id)


async def _on_helpdesk_reply(
    tenant_id: UUID,
    provider: str,
    adapter: Any,
    ctx: IntegrationContext,
    handoff: ConversationHandoff,
    comment_id: str | None,
) -> dict[str, Any]:
    ticket_id = str(handoff.external_ticket_id)
    extra: dict[str, Any] = {"tenant_id": str(tenant_id), "ticket_id": ticket_id}
    comment = await adapter.fetch_handoff_comment(ctx, ticket_id, comment_id)
    if comment is None:
        return _ignored_reply("comment_not_found", extra, level=logging.WARNING)
    extra |= {
        "comment_id": comment.comment_id,
        "author_id": comment.author_id,
        "via": comment.via_channel,
    }
    api_user_id = str(ctx.config.get("api_user_id") or "")
    if not comment.public:
        return _ignored_reply("private_comment", extra)
    if comment.author_id == comment.requester_id:
        return _ignored_reply("requester_comment", extra)
    # Anti-loop: solo lo que Auyan publica POR LA API. Si el OAuth client se creó con la
    # cuenta de una persona, sus respuestas desde la web de Zendesk (`via=web`) sí llegan
    # al cliente. Sin `via` se asume la API (fail-safe contra el bucle).
    if api_user_id and comment.author_id == api_user_id and (comment.via_channel or "api") == "api":
        return _ignored_reply("api_user_comment", extra)
    if not comment.content:
        # Un comentario público solo con adjunto tampoco llega: que se vea.
        return _ignored_reply("empty_content", extra, level=logging.WARNING)

    async with tenant_scope(tenant_id) as conn:
        claimed = await claim_webhook_idempotency_key(
            conn,
            tenant_id=tenant_id,
            key=f"{provider}_handoff:{ticket_id}:{comment.comment_id}",
            request_path=f"/webhooks/{provider}",
        )
        if not claimed:
            return {"received": True, "processed": False, "duplicate": True}
        conversation = await _latest_session(conn, tenant_id, handoff)
        if conversation is None:
            logger.error("handoff_reply_conversation_missing", extra={"tenant_id": str(tenant_id)})
            return _ignored("conversation_not_found")
        if handoff.status == "closed":
            # El equipo volvió a escribir en un ticket ya resuelto: retoma la conversación.
            try:
                await reopen_handoff_row(conn, tenant_id, handoff.id)
            except asyncpg.UniqueViolationError:
                logger.warning("handoff_reopen_conflict", extra={"tenant_id": str(tenant_id)})
        message = await insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="agent_human",
            direction="outbound",
            content=comment.content,
            metadata={
                "external_author": {
                    "provider": provider,
                    "id": comment.author_id,
                    "name": comment.author_name,
                },
                "handoff_id": str(handoff.id),
                f"{provider}_ticket_id": ticket_id,
                f"{provider}_comment_id": comment.comment_id,
            },
        )
        await update_conversation_last_message(conn, tenant_id, conversation.id)
        await touch_handoff_human_activity(conn, tenant_id, handoff.id)

    # Envío fuera de la transacción del registro: si el POST a Zernio tarda, no bloquea.
    async with tenant_scope(tenant_id) as conn:
        result = await deliver_to_customer(
            conn,
            tenant_id=tenant_id,
            conversation=conversation,
            content=comment.content,
            message_id=message.id,
        )
    if result == "failed":
        logger.error(
            "handoff_reply_delivery_failed",
            extra={"tenant_id": str(tenant_id), "message_id": str(message.id)},
        )
        await add_handoff_note(
            tenant_id=tenant_id,
            handoff=handoff,
            content=NOTE_DELIVERY_FAILED.format(reason="error del canal"),
        )
    logger.info(
        "handoff_reply_processed",
        extra={"tenant_id": str(tenant_id), "handoff_id": str(handoff.id), "delivery": result},
    )
    return {"received": True, "processed": True, "delivery": result}


async def _on_helpdesk_solved(tenant_id: UUID, handoff: ConversationHandoff) -> dict[str, Any]:
    """Ticket resuelto: la IA vuelve; la conversación queda resuelta SIN facturar."""
    if handoff.status != "active":
        return _ignored("handoff_already_closed")
    async with tenant_scope(tenant_id) as conn:
        closed = await close_handoff(
            conn, tenant_id=tenant_id, handoff=handoff, reason="helpdesk_solved"
        )
        if not closed:
            return _ignored("handoff_already_closed")
        escalations = await resolve_open_escalations_for_conversation(
            conn, tenant_id, handoff.conversation_id
        )
        await reactivate_escalated_conversation(conn, tenant_id, handoff.conversation_id)
        # Resolución HUMANA: sin resolution_event (billing solo cuenta las autónomas).
        resolved = await mark_conversation_resolved(conn, tenant_id, handoff.conversation_id)
    logger.info(
        "handoff_helpdesk_solved",
        extra={
            "tenant_id": str(tenant_id),
            "handoff_id": str(handoff.id),
            "escalations_closed": escalations,
            "conversation_resolved": resolved,
        },
    )
    return {"received": True, "processed": True, "event": "handoff_solved"}


# ─── Toma desde el móvil (coexistence) ────────────────────────────────────────


def device_hold_hours(tenant_config: TenantConfiguration | None) -> int:
    extra = tenant_config.extra if tenant_config else {}
    value = extra.get("whatsapp_device_hold_hours")
    if isinstance(value, int) and value > 0:
        return value
    return DEFAULT_DEVICE_HOLD_HOURS


def is_human_send(event: ZernioEvent) -> bool:
    """`message.sent` escrito por una persona de la marca (no por nuestra API)."""
    message = event.message
    if message is None:
        return False
    return message.source in DEVICE_SOURCES or message.sent_via == "human"


async def handle_device_takeover(
    event: ZernioEvent,
    *,
    tenant_id: UUID,
    tenant_config: TenantConfiguration | None,
) -> dict[str, Any]:
    """La marca escribió desde el móvil (o el inbox de Zernio): la IA calla N horas."""
    message = event.message
    if message is None or not event.conversation_id or not is_human_send(event):
        return _ignored("not_human_send")
    hold_until = datetime.now(UTC) + timedelta(hours=device_hold_hours(tenant_config))
    async with tenant_scope(tenant_id) as conn:
        if message.platform_message_id and await find_outbound_message_by_platform_id(
            conn, tenant_id, message.platform_message_id
        ):
            return _ignored("own_message")
        claimed = await claim_webhook_idempotency_key(
            conn,
            tenant_id=tenant_id,
            key=f"zernio:{event.event_id}",
            request_path="/webhooks/zernio",
        )
        if not claimed:
            return {"received": True, "processed": False, "duplicate": True}
        conversation = await find_conversation_by_external(
            conn, tenant_id, "whatsapp", event.conversation_id
        )
        if conversation is None:
            logger.info("device_takeover_without_conversation", extra={"tenant_id": str(tenant_id)})
            return _ignored("conversation_not_found")
        provider = "whatsapp_business_app" if message.source in DEVICE_SOURCES else "zernio_inbox"
        await insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="agent_human",
            direction="outbound",
            content=message.text,
            metadata={
                "external_author": {"provider": provider},
                "delivery": "delivered",
                "zernio_platform_message_ids": (
                    [message.platform_message_id] if message.platform_message_id else []
                ),
            },
        )
        await update_conversation_last_message(conn, tenant_id, conversation.id)
        active = await get_active_handoff_for_chat(
            conn, tenant_id, "whatsapp", event.conversation_id
        )
        if active is not None and active.target == "helpdesk":
            # Ya lo lleva el helpdesk: solo se registra el mensaje.
            await touch_handoff_human_activity(conn, tenant_id, active.id)
            outcome = "helpdesk_handoff_active"
        elif active is not None:
            await touch_handoff_human_activity(conn, tenant_id, active.id, expires_at=hold_until)
            outcome = "device_hold_renewed"
        else:
            try:
                async with conn.transaction():  # savepoint: la carrera no aborta el resto
                    await insert_handoff(
                        conn,
                        tenant_id=tenant_id,
                        conversation_id=conversation.id,
                        target="device",
                        reason=provider,
                        expires_at=hold_until,
                        last_human_at=datetime.now(UTC),
                    )
                outcome = "device_hold_opened"
            except asyncpg.UniqueViolationError:
                # Otro camino abrió un handoff a la vez: ya hay un humano; basta el registro.
                outcome = "handoff_opened_concurrently"
    logger.info(
        "device_takeover",
        extra={
            "tenant_id": str(tenant_id),
            "outcome": outcome,
            "hold_until": hold_until.isoformat(),
        },
    )
    return {"received": True, "processed": True, "outcome": outcome}
