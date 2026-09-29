"""Resolución autónoma del agente, condicionada a la entrega de la respuesta.

El nodo `respond` solo decide si la respuesta *resuelve* (`resolves_on_delivery`);
no marca nada. El caller post-grafo entrega la respuesta al canal y llama a
`finalize_agent_resolution` con el resultado: solo si se entregó se marca la
conversación `resolved`, se registra la resolución cobrable (billing) y se cierra
el ticket externo. Si la entrega falla, la conversación queda abierta, sin
resolución facturada y con el ticket abierto para el equipo del cliente.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apps.api.db.client import tenant_scope
from apps.api.db.queries import insert_resolution_event, mark_conversation_resolved
from apps.api.services.helpdesk_closure import close_external_helpdesk_ticket_safe

if TYPE_CHECKING:
    from apps.api.core.config import Settings
    from apps.api.db.models import Conversation

logger = logging.getLogger(__name__)


async def send_agent_reply(
    adapter: Any,
    ctx: Any,
    conversation_ref: str,
    content: str,
    *,
    tenant_id: UUID,
    provider: str,
) -> bool:
    """Envía la respuesta del agente vía `adapter.send_outbound`.

    Devuelve True si se entregó; False si falló (se loguea como error, no lanza:
    el webhook debe terminar y registrar uso/idempotencia igualmente).
    """
    try:
        await adapter.send_outbound(ctx, conversation_ref, content)
    except Exception:
        logger.error(
            "agent_reply_delivery_failed",
            extra={
                "tenant_id": str(tenant_id),
                "provider": provider,
                "conversation_ref": conversation_ref,
            },
            exc_info=True,
        )
        return False
    return True


async def finalize_agent_resolution(
    *,
    tenant_id: UUID,
    conversation: Conversation,
    delivered: bool,
    settings: Settings,
) -> bool:
    """Marca la resolución autónoma solo si la respuesta llegó al cliente.

    Devuelve True si la conversación quedó resuelta en esta llamada.
    """
    if not delivered:
        logger.error(
            "agent_resolution_blocked_undelivered",
            extra={"tenant_id": str(tenant_id), "conversation_id": str(conversation.id)},
        )
        return False

    async with tenant_scope(tenant_id) as conn:
        resolved = await mark_conversation_resolved(conn, tenant_id, conversation.id)
        if resolved:
            # Billing por resolución: log append-only de la resolución cobrable.
            await insert_resolution_event(conn, tenant_id, conversation.id)

    if not resolved:
        return False

    logger.info(
        "agent_resolution_confirmed",
        extra={"tenant_id": str(tenant_id), "conversation_id": str(conversation.id)},
    )
    await close_external_helpdesk_ticket_safe(
        tenant_id=tenant_id, conversation=conversation, settings=settings
    )
    return True
