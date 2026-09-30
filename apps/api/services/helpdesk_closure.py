"""Sincroniza el cierre de conversaciones con el helpdesk externo."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apps.api.core.errors import ExternalIntegrationError
from apps.api.db.client import tenant_scope
from apps.api.db.models import Conversation
from apps.api.db.queries import (
    get_active_integration,
    get_integration_credentials_encrypted,
)
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.chatwoot import ChatwootAdapter
from apps.api.integrations.gorgias import GorgiasAdapter
from apps.api.integrations.zendesk import ZendeskAdapter
from apps.api.services.channel_routing import is_messaging_channel
from apps.api.services.integrations_crypto import (
    decrypt_credentials,
    get_integration_crypto_key,
)

if TYPE_CHECKING:
    from apps.api.core.config import Settings

logger = logging.getLogger(__name__)

_RESOLVED_STATUS_BY_PROVIDER = {
    "chatwoot": "resolved",
    "gorgias": "closed",
    "zendesk": "solved",
}

_ADAPTER_BY_PROVIDER: dict[str, type[Any]] = {
    "chatwoot": ChatwootAdapter,
    "gorgias": GorgiasAdapter,
    "zendesk": ZendeskAdapter,
}


async def close_external_helpdesk_ticket(
    *,
    tenant_id: UUID,
    conversation: Conversation,
    settings: Settings,
) -> bool:
    """Marca como resuelto/cerrado el ticket externo asociado a la conversación.

    Retorna False cuando no hay nada externo que sincronizar. Lanza
    ExternalIntegrationError cuando sí debería sincronizar y la integración falla.
    """
    provider = conversation.channel
    external_id = conversation.external_id
    if is_messaging_channel(provider):
        # En mensajería (WhatsApp) no hay ticket propio que cerrar: el cierre del
        # ticket de handoff lo gestiona el módulo de handoff (ADR 0010).
        logger.info(
            "external_helpdesk_close_skipped_messaging_channel",
            extra={"tenant_id": str(tenant_id), "conversation_id": str(conversation.id)},
        )
        return False
    external_status = _RESOLVED_STATUS_BY_PROVIDER.get(provider)

    if external_status is None or not external_id:
        return False

    async with tenant_scope(tenant_id) as conn:
        integration = await get_active_integration(
            conn,
            tenant_id=tenant_id,
            kind="helpdesk",
            provider=provider,
        )
        if integration is None:
            return False

        encrypted = await get_integration_credentials_encrypted(
            conn,
            tenant_id=tenant_id,
            integration_id=integration.id,
        )

    if encrypted is None:
        raise ExternalIntegrationError(
            f"credentials not found for {provider} integration",
            code="integration_credentials_not_found",
        )

    try:
        crypto_key = get_integration_crypto_key(settings)
        credentials = json.loads(decrypt_credentials(encrypted, crypto_key).decode())
        ctx = IntegrationContext(
            tenant_id=tenant_id,
            credentials=credentials,
            config=integration.config,
        )
        adapter = _ADAPTER_BY_PROVIDER[provider]()
        await adapter.update_status(ctx, external_id, external_status)
    except ExternalIntegrationError:
        raise
    except Exception as exc:
        logger.exception(
            "external_helpdesk_close_failed",
            extra={
                "tenant_id": str(tenant_id),
                "conversation_id": str(conversation.id),
                "provider": provider,
                "external_id": external_id,
            },
        )
        raise ExternalIntegrationError(
            f"failed to close external {provider} ticket",
            code="external_helpdesk_close_failed",
        ) from exc

    logger.info(
        "external_helpdesk_closed",
        extra={
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation.id),
            "provider": provider,
            "external_id": external_id,
            "external_status": external_status,
        },
    )
    return True


async def close_external_helpdesk_ticket_safe(
    *,
    tenant_id: UUID,
    conversation: Conversation,
    settings: Settings,
) -> bool:
    """Versión best-effort de close_external_helpdesk_ticket: nunca lanza.

    Para usar en caminos donde el cierre externo es secundario (resolución autónoma
    del agente, cleanup por inactividad) y no debe tumbar el flujo si el helpdesk
    falla. El estado interno de la conversación ya es la fuente de verdad.
    """
    try:
        return await close_external_helpdesk_ticket(
            tenant_id=tenant_id, conversation=conversation, settings=settings
        )
    except Exception:
        logger.warning(
            "external_helpdesk_close_best_effort_failed",
            extra={"tenant_id": str(tenant_id), "conversation_id": str(conversation.id)},
        )
        return False
