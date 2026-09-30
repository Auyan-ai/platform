"""Empuja un escalado al helpdesk del cliente: nota interna + asignación al equipo CX.

Cuando el agente escala, el cliente recibe el mensaje de cortesía vía `send_outbound`,
pero la conversación quedaba **sin** nota de contexto y **sin asignar** en el helpdesk
→ el equipo del cliente no la veía. Esto cablea `push_escalation` (nota con razón +
contexto del agente + asignación al `escalation_team_id` configurado en la integración).

Modelo Auyan: el equipo CX del propio cliente atiende los escalados; Auyan solo enruta.

Best-effort: `_safe` nunca lanza. El estado interno (`escalations` + status `escalated`)
ya es la fuente de verdad y no debe tumbarse si el helpdesk está caído.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.core.config import get_settings
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    get_active_integration,
    get_integration_credentials_encrypted,
)
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.services.channel_routing import is_messaging_channel
from apps.api.services.integrations_crypto import (
    decrypt_credentials,
    get_integration_crypto_key,
)

if TYPE_CHECKING:
    from apps.api.db.models import Conversation

logger = logging.getLogger(__name__)


async def push_escalation_to_helpdesk(
    *,
    tenant_id: UUID,
    conversation: Conversation,
    reason: str,
) -> bool:
    """Publica la nota interna del escalado + asigna al equipo CX del cliente.

    La nota es el `reason` en lenguaje natural (lo genera el agente, ya trae el
    contexto: motivo, nº de pedido, urgencia). No se inyecta contexto estructurado
    (confianza/trace/etc.): el agente humano ya ve el hilo y eso vive en LangSmith.

    Devuelve True si se empujó. False (sin lanzar) si el canal no es un helpdesk
    (widget de prueba), no hay integración activa o faltan credenciales. Lanza si la
    llamada al helpdesk falla — usar el wrapper `_safe` en caminos best-effort.
    """
    provider = conversation.channel
    external_id = conversation.external_id
    if not external_id:
        return False
    if is_messaging_channel(provider):
        # WhatsApp y otros canales de mensajería no escalan en su propio adapter: van
        # por el handoff al helpdesk del cliente (ADR 0010).
        logger.info(
            "escalation_push_skipped_messaging_channel tenant_id=%s channel=%s conversation_id=%s",
            tenant_id,
            provider,
            conversation.id,
        )
        return False
    try:
        adapter_cls = IntegrationRegistry.get("helpdesk", provider)
    except ValueError:
        # Canal sin helpdesk (chat/widget de prueba): no hay a dónde enrutar.
        return False

    async with tenant_scope(tenant_id) as conn:
        integration = await get_active_integration(
            conn, tenant_id=tenant_id, kind="helpdesk", provider=provider
        )
        if integration is None:
            logger.warning(
                "escalation_push_no_integration tenant_id=%s provider=%s",
                tenant_id,
                provider,
            )
            return False
        encrypted = await get_integration_credentials_encrypted(
            conn, tenant_id=tenant_id, integration_id=integration.id
        )
    if encrypted is None:
        return False

    key = get_integration_crypto_key(get_settings())
    creds = json.loads(decrypt_credentials(encrypted, key).decode())
    ctx = IntegrationContext(
        tenant_id=tenant_id, credentials=creds, config=integration.config or {}
    )
    # Sin contexto estructurado: la nota es solo el motivo en lenguaje natural.
    await adapter_cls().push_escalation(ctx, external_id, reason, {})
    logger.info(
        "escalation_pushed_to_helpdesk tenant_id=%s provider=%s conversation_id=%s",
        tenant_id,
        provider,
        conversation.id,
    )
    return True


async def push_escalation_to_helpdesk_safe(
    *,
    tenant_id: UUID,
    conversation: Conversation,
    reason: str,
) -> bool:
    """Versión best-effort de `push_escalation_to_helpdesk`: nunca lanza.

    Para el camino post-grafo del webhook: el escalado interno ya quedó registrado;
    si el helpdesk falla, se loguea y se sigue (no tumba la request del webhook).
    """
    try:
        return await push_escalation_to_helpdesk(
            tenant_id=tenant_id,
            conversation=conversation,
            reason=reason,
        )
    except Exception:
        logger.warning(
            "escalation_push_best_effort_failed tenant_id=%s conversation_id=%s",
            tenant_id,
            conversation.id,
        )
        return False
