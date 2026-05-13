import uuid
from typing import Any

from supabase import Client

from db import queries
from db.models import ConversationStatus


async def escalate_conversation(
    db: Client,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    reason: str,
    triggered_by_message_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    escalation = await queries.create_escalation(
        db,
        {
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation_id),
            "reason": reason,
            "triggered_by_message_id": str(triggered_by_message_id) if triggered_by_message_id else None,
            "status": "pending",
            "metadata": metadata or {},
        },
    )

    await queries.update_conversation(
        db, tenant_id, conversation_id, {"status": ConversationStatus.escalated}
    )

    return escalation
