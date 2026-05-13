import uuid
from typing import Any

from supabase import Client

from db import queries
from db.models import ChannelType, Conversation, MessageDirection, MessageRole


async def process_inbound_ticket(
    db: Client,
    tenant_id: uuid.UUID,
    channel: ChannelType,
    customer_email: str | None,
    customer_external_id: str | None,
    content: str,
    subject: str | None = None,
    external_conversation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    customer = await queries.get_or_create_end_customer(
        db, tenant_id, email=customer_email, external_id=customer_external_id
    )

    conversation_data = await _get_or_create_conversation(
        db,
        tenant_id=tenant_id,
        end_customer_id=uuid.UUID(customer["id"]),
        channel=channel,
        subject=subject,
        external_id=external_conversation_id,
    )
    conversation = Conversation(**conversation_data)

    inbound_message = await queries.create_message(
        db,
        {
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation.id),
            "role": MessageRole.customer,
            "direction": MessageDirection.inbound,
            "content": content,
            "attachments": [],
            "metadata": metadata or {},
        },
    )

    # TODO: invocar agente LangGraph cuando esté implementado
    return {
        "conversation_id": str(conversation.id),
        "message_id": str(inbound_message["id"]),
        "action": None,
        "response": None,
    }


async def _get_or_create_conversation(
    db: Client,
    tenant_id: uuid.UUID,
    end_customer_id: uuid.UUID,
    channel: ChannelType,
    subject: str | None,
    external_id: str | None,
) -> dict:
    if external_id:
        existing = (
            db.table("conversations")
            .select("*")
            .eq("tenant_id", str(tenant_id))
            .eq("channel", channel)
            .eq("external_id", external_id)
            .is_("deleted_at", "null")
            .maybe_single()
            .execute()
        )
        if existing.data:
            return existing.data

    return await queries.create_conversation(
        db,
        {
            "tenant_id": str(tenant_id),
            "end_customer_id": str(end_customer_id),
            "channel": channel,
            "subject": subject,
            "external_id": external_id,
            "status": "open",
        },
    )
