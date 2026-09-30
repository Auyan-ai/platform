"""Handoff modular: un humano de la marca toma una conversación de mensajería (ADR 0010).

- **helpdesk**: se abre un ticket en el helpdesk PRIMARIO del tenant (hoy Zendesk) vía la
  interfaz `HandoffTarget`. Mientras está activo, la IA calla y los mensajes del comprador
  se reenvían al ticket. Se cierra cuando el ticket se resuelve (PR-5).
- **device**: la marca contestó desde la app de WhatsApp Business (coexistence). La IA calla
  hasta `expires_at` (PR-5).

Determinista (regla dura del Sprint 2): abrir, reenviar y cerrar son código. La
transcripción son los mensajes literales formateados aquí; el único texto del LLM que
llega al ticket es el motivo del escalado.

Best-effort en los caminos del turno: `open_handoff_safe` nunca lanza. Sin helpdesk
primario (o si falla) se registra `logger.error` y la escalación interna sigue visible en
el dashboard de Auyan.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

import asyncpg
from apps.api.core.config import get_settings
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    close_handoff_row,
    get_active_handoff,
    get_end_customer,
    get_integration_credentials_encrypted,
    get_primary_integration_for_kind,
    insert_handoff,
    insert_message,
    list_recent_messages,
)
from apps.api.integrations.base import HandoffRequest, IntegrationContext, StoredAttachment
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.services.integrations_crypto import decrypt_credentials, get_integration_crypto_key
from apps.api.services.media_storage import download_attachment
from apps.api.services.messaging_window import window_state

if TYPE_CHECKING:
    from apps.api.db.models import Conversation, ConversationHandoff, Message

logger = logging.getLogger(__name__)

TRANSCRIPT_MESSAGES = 20
CHANNEL_LABELS = {"whatsapp": "WhatsApp"}
_ROLE_LABELS = {"customer": "Cliente", "agent_ai": "Agente IA", "agent_human": "Equipo"}
APPROVAL_GATE_PREFIX = "awaiting_human_approval:"


class HandoffUnavailableError(RuntimeError):
    """El tenant no tiene un helpdesk primario que admita handoff."""


def is_approval_gate(reason: str | None) -> bool:
    """La puerta L3 no abre handoff: se decide en el dashboard de Auyan y la IA sigue."""
    return bool(reason) and str(reason).startswith(APPROVAL_GATE_PREFIX)


def format_transcript(messages: list[Message]) -> str:
    """Mensajes literales, en orden, con quién habló. Sin resúmenes."""
    lines: list[str] = []
    for message in messages:
        label = _ROLE_LABELS.get(message.role, message.role)
        if message.role == "agent_human" and message.metadata.get("external_author"):
            label = "Equipo de la marca"
        stamp = f"[{message.created_at:%d/%m %H:%M}] " if message.created_at else ""
        content = message.content.strip() or "(sin texto)"
        attachments = message.attachments or message.metadata.get("zernio_attachments") or []
        suffix = f" [+{len(attachments)} adjunto(s)]" if attachments else ""
        lines.append(f"{stamp}{label}: {content}{suffix}")
    return "\n".join(lines)


def stored_attachments_of(message: Message) -> list[StoredAttachment]:
    """Adjuntos ya guardados en Storage (PR-7) de un mensaje."""
    result: list[StoredAttachment] = []
    for item in message.attachments or []:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        result.append(
            StoredAttachment(
                path=str(item["path"]),
                mime_type=str(item.get("mime_type") or "application/octet-stream"),
                size=int(item.get("size") or 0),
                filename=str(item.get("filename") or item["path"].rsplit("/", 1)[-1]),
                kind=str(item.get("kind") or "file"),
            )
        )
    return result


async def _load_attachment_bytes(attachments: list[StoredAttachment]) -> list[StoredAttachment]:
    """Carga de Storage los bytes de cada adjunto para subirlo al helpdesk (best-effort)."""
    if not attachments:
        return []
    loaded: list[StoredAttachment] = []
    for attachment in attachments:
        try:
            content = await download_attachment(attachment.path)
        except Exception:
            logger.error("handoff_attachment_download_failed", exc_info=True)
            continue
        loaded.append(
            StoredAttachment(
                path=attachment.path,
                mime_type=attachment.mime_type,
                size=attachment.size,
                filename=attachment.filename,
                kind=attachment.kind,
                content=content,
            )
        )
    return loaded


async def _load_handoff_target(
    conn: asyncpg.Connection, tenant_id: UUID
) -> tuple[Any, IntegrationContext, str]:
    """Adapter + contexto del helpdesk PRIMARIO del tenant, si implementa HandoffTarget."""
    integration = await get_primary_integration_for_kind(conn, tenant_id=tenant_id, kind="helpdesk")
    if integration is None:
        raise HandoffUnavailableError("no_primary_helpdesk")
    try:
        adapter_cls = IntegrationRegistry.get("helpdesk", integration.provider)
    except ValueError as exc:
        raise HandoffUnavailableError(f"no_adapter:{integration.provider}") from exc
    adapter = adapter_cls()
    if not hasattr(adapter, "open_handoff_ticket"):
        raise HandoffUnavailableError(f"handoff_not_supported:{integration.provider}")
    encrypted = await get_integration_credentials_encrypted(
        conn, tenant_id=tenant_id, integration_id=integration.id
    )
    if encrypted is None:
        raise HandoffUnavailableError("helpdesk_credentials_not_found")
    creds = json.loads(
        decrypt_credentials(encrypted, get_integration_crypto_key(get_settings())).decode()
    )
    ctx = IntegrationContext(tenant_id=tenant_id, credentials=creds, config=integration.config)
    return adapter, ctx, integration.provider


async def open_handoff(
    *,
    tenant_id: UUID,
    conversation: Conversation,
    reason: str,
) -> ConversationHandoff:
    """Abre (o devuelve el ya activo) el handoff al helpdesk primario del tenant.

    Lanza HandoffUnavailableError si no hay helpdesk que lo admita y la excepción del
    helpdesk si la llamada falla. Usar `open_handoff_safe` en caminos best-effort.
    """
    async with tenant_scope(tenant_id) as conn:
        active = await get_active_handoff(conn, tenant_id, conversation.id)
        if active is not None:
            logger.info(
                "handoff_already_active",
                extra={"tenant_id": str(tenant_id), "conversation_id": str(conversation.id)},
            )
            return active
        adapter, ctx, provider = await _load_handoff_target(conn, tenant_id)
        messages = await list_recent_messages(
            conn, tenant_id, conversation.id, limit=TRANSCRIPT_MESSAGES
        )
        window = await window_state(conn, tenant_id=tenant_id, conversation=conversation)
        customer = await get_end_customer(conn, tenant_id, conversation.end_customer_id)

    attachments: list[StoredAttachment] = []
    for message in messages:
        if message.role == "customer":
            attachments.extend(stored_attachments_of(message))
    channel_label = CHANNEL_LABELS.get(conversation.channel, conversation.channel)
    display_name = customer.full_name if customer and customer.full_name else "Cliente"
    request = HandoffRequest(
        conversation_id=conversation.id,
        customer_name=customer.full_name if customer else None,
        customer_phone=customer.phone if customer else None,
        customer_email=customer.email if customer else None,
        customer_ref=f"auyan:{conversation.end_customer_id}",
        subject=f"{channel_label} · {display_name}",
        reason=reason,
        transcript=format_transcript(messages),
        window_closes_at=window.closes_at if window.open else None,
        attachments=await _load_attachment_bytes(attachments),
        channel_label=channel_label,
    )
    ticket = await adapter.open_handoff_ticket(ctx, request)

    async with tenant_scope(tenant_id) as conn:
        try:
            handoff = await insert_handoff(
                conn,
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                target="helpdesk",
                reason=reason,
                helpdesk_provider=provider,
                external_ticket_id=ticket.ticket_id,
            )
        except asyncpg.UniqueViolationError:
            # Carrera: otro camino abrió el handoff a la vez. Se queda el primero.
            logger.error(
                "handoff_duplicate_ticket_opened",
                extra={"tenant_id": str(tenant_id), "ticket_id": ticket.ticket_id},
            )
            existing = await get_active_handoff(conn, tenant_id, conversation.id)
            if existing is None:
                raise
            return existing
        await insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="system",
            direction="outbound",
            content=f"Conversación derivada a {provider} (ticket {ticket.ticket_id}).",
            metadata={
                "event": "handoff_opened",
                "handoff_id": str(handoff.id),
                "helpdesk_provider": provider,
                "external_ticket_id": ticket.ticket_id,
                "ticket_url": ticket.url,
                "reason": reason,
            },
        )
    logger.info(
        "handoff_opened",
        extra={
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation.id),
            "handoff_id": str(handoff.id),
            "provider": provider,
            "ticket_id": ticket.ticket_id,
        },
    )
    return handoff


async def open_handoff_safe(
    *,
    tenant_id: UUID,
    conversation: Conversation,
    reason: str,
) -> ConversationHandoff | None:
    """`open_handoff` sin lanzar nunca: el turno ya registró la escalación interna."""
    try:
        return await open_handoff(tenant_id=tenant_id, conversation=conversation, reason=reason)
    except HandoffUnavailableError as exc:
        logger.error(
            "handoff_unavailable",
            extra={
                "tenant_id": str(tenant_id),
                "conversation_id": str(conversation.id),
                "cause": str(exc),
            },
        )
    except Exception:
        logger.error(
            "handoff_open_failed",
            extra={"tenant_id": str(tenant_id), "conversation_id": str(conversation.id)},
            exc_info=True,
        )
    return None


async def forward_customer_message(
    *,
    tenant_id: UUID,
    handoff: ConversationHandoff,
    content: str,
    attachments: list[StoredAttachment],
) -> bool:
    """Reenvía al ticket del handoff un mensaje del comprador. Nunca lanza."""
    extra = {"tenant_id": str(tenant_id), "handoff_id": str(handoff.id)}
    if handoff.target != "helpdesk" or not handoff.external_ticket_id:
        return False
    try:
        async with tenant_scope(tenant_id) as conn:
            adapter, ctx, _ = await _load_handoff_target(conn, tenant_id)
        await adapter.append_customer_message(
            ctx,
            handoff.external_ticket_id,
            content,
            await _load_attachment_bytes(attachments),
        )
    except Exception:
        logger.error("handoff_forward_failed", extra=extra, exc_info=True)
        return False
    logger.info("handoff_customer_message_forwarded", extra=extra)
    return True


async def add_handoff_note(
    *,
    tenant_id: UUID,
    handoff: ConversationHandoff,
    content: str,
) -> bool:
    """Nota interna en el ticket del handoff (p. ej. "ventana cerrada"). Nunca lanza."""
    if handoff.target != "helpdesk" or not handoff.external_ticket_id:
        return False
    try:
        async with tenant_scope(tenant_id) as conn:
            adapter, ctx, _ = await _load_handoff_target(conn, tenant_id)
        await adapter.add_internal_note(ctx, handoff.external_ticket_id, content)
    except Exception:
        logger.error(
            "handoff_note_failed",
            extra={"tenant_id": str(tenant_id), "handoff_id": str(handoff.id)},
            exc_info=True,
        )
        return False
    return True


async def close_handoff(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    handoff: ConversationHandoff,
    reason: str,
) -> bool:
    """Cierra el handoff (la IA vuelve a atender) y deja constancia en la conversación."""
    closed = await close_handoff_row(conn, tenant_id, handoff.id, reason)
    if closed:
        await insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=handoff.conversation_id,
            role="system",
            direction="outbound",
            content="El equipo de la marca terminó: Auyan vuelve a atender.",
            metadata={
                "event": "handoff_closed",
                "handoff_id": str(handoff.id),
                "closed_reason": reason,
            },
        )
        logger.info(
            "handoff_closed",
            extra={"tenant_id": str(tenant_id), "handoff_id": str(handoff.id), "reason": reason},
        )
    return closed
