"""Resolutor único del canal de entrega de una conversación.

Hasta el Sprint 2 todo el código asumía `conversation.channel == helpdesk`: el mismo
adapter recibía, entregaba, escalaba y cerraba. WhatsApp (vía Zernio) rompe esa
igualdad: la conversación vive en un canal de **mensajería** y el equipo CX del cliente
trabaja en su helpdesk (ADR 0010). Este módulo es el único sitio que traduce un canal a
la integración que entrega sus mensajes.

- `helpdesk`: el canal ES el helpdesk (Zendesk/Gorgias/Chatwoot). Entrega, escalado y
  cierre van al mismo adapter.
- `channel`: canal de mensajería (WhatsApp → Zernio). Entrega por el adapter del canal;
  escalado y cierre van por el handoff al helpdesk del cliente (no por este adapter).

Los canales sin ruta (`chat`/`widget` de prueba, `email`, `instagram`, `intercom`) no
tienen a dónde entregar: el mensaje persistido en DB es la entrega.
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
    from apps.api.db.models import ChannelType, Conversation, IntegrationKind

logger = logging.getLogger(__name__)

DELIVERY_ROUTES: dict[ChannelType, tuple[IntegrationKind, str]] = {
    "zendesk": ("helpdesk", "zendesk"),
    "gorgias": ("helpdesk", "gorgias"),
    "chatwoot": ("helpdesk", "chatwoot"),
    "whatsapp": ("channel", "zernio"),
}


def delivery_route(channel: str) -> tuple[IntegrationKind, str] | None:
    """(kind, provider) de la integración que entrega en `channel`; None si no hay."""
    return DELIVERY_ROUTES.get(channel)  # type: ignore[call-overload]


def is_messaging_channel(channel: str) -> bool:
    """True si el canal es de mensajería (no helpdesk): escalado y cierre van por handoff."""
    route = delivery_route(channel)
    return route is not None and route[0] == "channel"


async def load_delivery_client(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation: Conversation,
) -> tuple[Any, IntegrationContext] | None:
    """Adapter + contexto (credenciales descifradas) que entrega en el canal de la conversación.

    None si el canal no tiene ruta de entrega (`chat`/`widget` de prueba), la conversación
    no tiene `external_id`, el adapter no está registrado o no hay integración activa con
    credenciales. Lanza si las credenciales no se pueden descifrar. `conn` ya dentro de
    su `tenant_scope`.
    """
    route = delivery_route(conversation.channel)
    if route is None or not conversation.external_id:
        return None
    kind, provider = route
    try:
        adapter_cls = IntegrationRegistry.get(kind, provider)
    except ValueError:
        logger.warning(
            "channel_delivery_no_adapter tenant_id=%s kind=%s provider=%s",
            tenant_id,
            kind,
            provider,
        )
        return None

    integration = await get_active_integration(
        conn, tenant_id=tenant_id, kind=kind, provider=provider
    )
    if integration is None:
        logger.warning(
            "channel_delivery_no_integration tenant_id=%s kind=%s provider=%s",
            tenant_id,
            kind,
            provider,
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
