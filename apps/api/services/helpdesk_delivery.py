"""Entrega un mensaje saliente al helpdesk del cliente para una conversación.

Lo usa el flujo de approvals (approve/reject de skills L3): el webhook solo
entrega cuando el agente responde en línea, pero los mensajes de aprobación se
generan FUERA del webhook (en el endpoint de approvals) y antes nunca llegaban
al cliente. Resuelve por canal → adapter de helpdesk → send_outbound.

Best-effort: loguea y devuelve False si algo falla; nunca lanza (no debe tumbar
la request de aprobación si el helpdesk está caído).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apps.api.core.config import get_settings
from apps.api.db.queries import get_active_integration, get_integration_credentials_encrypted
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.services.integrations_crypto import decrypt_credentials, get_integration_crypto_key

if TYPE_CHECKING:
    import asyncpg
    from apps.api.db.models import Conversation

logger = logging.getLogger(__name__)


async def load_helpdesk_client(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation: Conversation,
) -> tuple[Any, IntegrationContext] | None:
    """Adapter + contexto (credenciales descifradas) del helpdesk de la conversación.

    None si el canal no es un helpdesk (`chat`/`widget` de prueba), la conversación no
    tiene `external_id`, o no hay integración activa con credenciales. Lanza si las
    credenciales no se pueden descifrar. `conn` ya dentro de su `tenant_scope`.
    """
    provider = conversation.channel
    if not conversation.external_id:
        return None
    try:
        adapter_cls = IntegrationRegistry.get("helpdesk", provider)
    except ValueError:
        # Canal sin helpdesk (chat/widget de prueba): no hay a dónde entregar.
        return None

    integration = await get_active_integration(
        conn, tenant_id=tenant_id, kind="helpdesk", provider=provider
    )
    if integration is None:
        logger.warning(
            "helpdesk_delivery_no_integration tenant_id=%s provider=%s", tenant_id, provider
        )
        return None
    encrypted = await get_integration_credentials_encrypted(
        conn, tenant_id=tenant_id, integration_id=integration.id
    )
    if encrypted is None:
        return None

    key = get_integration_crypto_key(get_settings())
    creds = json.loads(decrypt_credentials(encrypted, key).decode())
    ctx = IntegrationContext(
        tenant_id=tenant_id, credentials=creds, config=integration.config or {}
    )
    return adapter_cls(), ctx


async def deliver_message_to_helpdesk(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation: Conversation,
    content: str,
) -> bool:
    """Empuja `content` al helpdesk del cliente para esta conversación.

    Devuelve True si se entregó. False (sin lanzar) si el canal no es un helpdesk
    (ej. `chat`/`widget` de prueba), no hay integración activa, o la llamada falla.
    Debe llamarse con un `conn` ya dentro de su `tenant_scope`.
    """
    try:
        client = await load_helpdesk_client(conn, tenant_id=tenant_id, conversation=conversation)
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
