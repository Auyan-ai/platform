"""Lógica de negocio de conversaciones.

Sin imports de FastAPI. Lanza excepciones de dominio; el handler global las traduce a HTTP.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.core.errors import ConflictError, NotFoundError
from apps.api.db.models import Conversation, ConversationStatus, Escalation, Message
from apps.api.db.queries import (
    get_conversation,
    get_messages_for_conversation,
    insert_escalation,
    insert_message,
    list_conversations,
    reopen_conversation,
    update_conversation_last_message,
    update_conversation_status,
)

if TYPE_CHECKING:
    import asyncpg

_CLOSED_CONVERSATION_STATUSES = {"closed", "closed_abandoned", "resolved"}


async def reopen_if_resolved(
    conn: asyncpg.Connection, tenant_id: UUID, conversation: Conversation
) -> Conversation:
    """Reabre la conversación si estaba resuelta (el cliente volvió a escribir).

    El agente resuelve y cierra el ticket; cuando el cliente responde en el mismo
    thread hay que reactivarla (status 'open', resolved_at limpio) para procesar el
    nuevo mensaje. Un tema NUEVO suele llegar como thread nuevo del helpdesk (otro
    external_id → conversación nueva), así que aquí solo tratamos la reapertura del
    mismo thread. No-op si no estaba resuelta.
    """
    if conversation.status != "resolved":
        return conversation
    await reopen_conversation(conn, tenant_id, conversation.id)
    return conversation.model_copy(update={"status": "open", "resolved_at": None})


async def list_tenant_conversations(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    status: ConversationStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Conversation]:
    return await list_conversations(conn, tenant_id, status=status, limit=limit, offset=offset)


async def get_conversation_detail(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
    *,
    include_system: bool = False,
) -> tuple[Conversation, list[Message]]:
    conv = await get_conversation(conn, tenant_id, conversation_id)
    if conv is None:
        raise NotFoundError(
            f"conversation {conversation_id} not found", code="conversation_not_found"
        )
    messages = await get_messages_for_conversation(
        conn, tenant_id, conversation_id, include_system=include_system
    )
    return conv, messages


async def reply_to_conversation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
    author_user_id: UUID,
    content: str,
) -> Message:
    conv = await get_conversation(conn, tenant_id, conversation_id)
    if conv is None:
        raise NotFoundError(
            f"conversation {conversation_id} not found", code="conversation_not_found"
        )
    if conv.status == "closed":
        raise ConflictError(
            "cannot reply to a closed conversation", code="conversation_closed"
        )
    msg = await insert_message(
        conn,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="agent_human",
        direction="outbound",
        content=content,
        author_user_id=author_user_id,
    )
    await update_conversation_last_message(conn, tenant_id, conversation_id)
    return msg


async def escalate_conversation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
    reason: str,
) -> Escalation:
    conv = await get_conversation(conn, tenant_id, conversation_id)
    if conv is None:
        raise NotFoundError(
            f"conversation {conversation_id} not found", code="conversation_not_found"
        )
    if conv.status == "escalated":
        raise ConflictError(
            "conversation is already escalated", code="already_escalated"
        )
    if conv.status == "closed":
        raise ConflictError(
            "cannot escalate a closed conversation", code="conversation_closed"
        )
    escalation = await insert_escalation(
        conn, tenant_id=tenant_id, conversation_id=conversation_id, reason=reason
    )
    await update_conversation_status(conn, tenant_id, conversation_id, "escalated")
    return escalation


async def close_conversation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
) -> Conversation:
    conv = await get_closable_conversation(conn, tenant_id, conversation_id)
    await update_conversation_status(conn, tenant_id, conversation_id, "closed")
    return conv.model_copy(update={"status": "closed"})


async def get_closable_conversation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
) -> Conversation:
    conv = await get_conversation(conn, tenant_id, conversation_id)
    if conv is None:
        raise NotFoundError(
            f"conversation {conversation_id} not found", code="conversation_not_found"
        )
    if conv.status in _CLOSED_CONVERSATION_STATUSES:
        raise ConflictError("conversation is already closed", code="already_closed")
    return conv
