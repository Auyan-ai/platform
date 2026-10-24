"""Gate de message cap por conversación.

Si una conversación supera el límite de mensajes inbound configurados,
el sistema escala automáticamente sin invocar el grafo LangGraph.

Flujo cuando se supera el cap:
  1. Inserta mensaje de cortesía del agente explicando el traspaso.
  2. Crea la escalación (pending) con razón explícita.
  3. Actualiza el status de la conversación a 'escalated'.
  4. Devuelve un AgentOutcome equivalente al de una escalación normal.

Si no se supera el cap, devuelve None → el caller continúa con el grafo.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.agents.service import AgentOutcome
from apps.api.db.queries import (
    count_inbound_messages,
    get_open_escalation_for_conversation,
    insert_escalation,
    insert_message,
    update_conversation_status,
)
from apps.api.services.fixed_texts import fixed_text
from apps.api.services.language import conversation_text_languages

if TYPE_CHECKING:
    import asyncpg
    from apps.api.core.config import Settings
    from apps.api.db.models import TenantConfiguration

logger = logging.getLogger(__name__)

_CAP_REASON = "message_cap_exceeded"


async def enforce_message_cap(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    inbound_message_id: UUID,
    tenant_config: TenantConfiguration | None,
    settings: Settings,
) -> AgentOutcome | None:
    """Verifica el message cap y escala automáticamente si se superó.

    Debe llamarse después de insertar el mensaje inbound, de modo que el conteo
    ya incluye el mensaje actual.

    Retorna AgentOutcome si se aplicó el cap (el grafo NO debe correr).
    Retorna None si el cap no se superó (continuar normalmente).
    """
    cap: int = settings.max_inbound_messages_per_conversation
    if tenant_config is not None:
        override = tenant_config.extra.get("max_inbound_messages")
        if isinstance(override, int) and override > 0:
            cap = override

    if cap <= 0:
        return None

    count = await count_inbound_messages(conn, tenant_id=tenant_id, conversation_id=conversation_id)
    if count <= cap:
        return None

    logger.info(
        "message_cap_exceeded",
        extra={
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation_id),
            "count": count,
            "cap": cap,
        },
    )

    # Reutilizar escalación activa si ya existe (idempotente ante reintentos).
    existing = await get_open_escalation_for_conversation(conn, tenant_id, conversation_id)
    if existing is not None:
        return AgentOutcome(
            decision="escalate",
            response_text=None,
            escalation_reason=_CAP_REASON,
            output_message_id=None,
            escalation_id=str(existing.id),
            resolves_on_delivery=False,
            trace_id=None,
            confidence=None,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            model_used=None,
            error=None,
        )

    language, tenant_default = await conversation_text_languages(
        conn, tenant_id, conversation_id, tenant_config.extra if tenant_config else None
    )
    cap_message = fixed_text(
        "message_cap",
        language,
        tenant_default=tenant_default,
        overrides={"message_cap": tenant_config.extra.get("cap_message")}
        if tenant_config
        else None,
    )
    courtesy_msg = await insert_message(
        conn,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="agent_ai",
        direction="outbound",
        content=cap_message,
        metadata={"reason": _CAP_REASON},
    )

    escalation = await insert_escalation(
        conn,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        reason=_CAP_REASON,
        triggered_by_message_id=inbound_message_id,
    )

    await update_conversation_status(conn, tenant_id, conversation_id, "escalated")

    return AgentOutcome(
        decision="escalate",
        response_text=cap_message,
        escalation_reason=_CAP_REASON,
        output_message_id=str(courtesy_msg.id),
        escalation_id=str(escalation.id),
        resolves_on_delivery=False,
        trace_id=None,
        confidence=None,
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.0,
        model_used=None,
        error=None,
        escalation_created=True,
    )
