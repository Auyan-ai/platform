"""Entrega un mensaje saliente al canal de la conversación (helpdesk o mensajería).

Lo usa el flujo de approvals (approve/reject de skills L3): el webhook solo
entrega cuando el agente responde en línea, pero los mensajes de aprobación se
generan FUERA del webhook (en el endpoint de approvals) y antes nunca llegaban
al cliente. Resuelve por canal (`channel_routing`) → adapter → send_outbound.

Best-effort: loguea y devuelve False si algo falla; nunca lanza (no debe tumbar
la request de aprobación si el helpdesk está caído).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.services.channel_delivery import deliver_to_customer
from apps.api.services.channel_routing import is_messaging_channel, load_delivery_client

if TYPE_CHECKING:
    import asyncpg
    from apps.api.db.models import Conversation

logger = logging.getLogger(__name__)

# Alias histórico: el resolutor vive en `channel_routing` (ya no asume canal == helpdesk).
load_helpdesk_client = load_delivery_client


async def deliver_message_to_helpdesk(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation: Conversation,
    content: str,
    message_id: UUID | None = None,
) -> bool:
    """Empuja `content` al canal del cliente para esta conversación.

    En canales de mensajería (WhatsApp) la entrega respeta la ventana de 24 h
    (`services.channel_delivery`): con la ventana cerrada el mensaje queda pendiente
    (`message_id` obligatorio para marcarlo) y devuelve False — pendiente NO es entregado.

    Devuelve True si se entregó. False (sin lanzar) si el canal no es un helpdesk
    (ej. `chat`/`widget` de prueba), no hay integración activa, o la llamada falla.
    Debe llamarse con un `conn` ya dentro de su `tenant_scope`.
    """
    if is_messaging_channel(conversation.channel):
        result = await deliver_to_customer(
            conn,
            tenant_id=tenant_id,
            conversation=conversation,
            content=content,
            message_id=message_id,
        )
        return result == "delivered"
    try:
        client = await load_delivery_client(conn, tenant_id=tenant_id, conversation=conversation)
        if client is None:
            return False
        adapter, ctx = client
        await adapter.send_outbound(ctx, conversation.external_id, content)
        return True
    except Exception:
        logger.error(
            "helpdesk_delivery_failed tenant_id=%s provider=%s conversation_id=%s",
            tenant_id,
            conversation.channel,
            conversation.id,
            exc_info=True,
        )
        return False
