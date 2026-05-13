import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from supabase import Client

from db.client import get_supabase
from db.models import ChannelType
from services import tickets as ticket_service

router = APIRouter()


class InboundTicketRequest(BaseModel):
    tenant_id: uuid.UUID
    channel: ChannelType
    content: str
    customer_email: str | None = None
    customer_external_id: str | None = None
    subject: str | None = None
    external_conversation_id: str | None = None
    metadata: dict[str, Any] | None = None


class InboundTicketResponse(BaseModel):
    conversation_id: str
    message_id: str
    action: str | None
    response: str | None


@router.post("/inbound", response_model=InboundTicketResponse)
async def receive_ticket(
    payload: InboundTicketRequest,
    db: Client = Depends(get_supabase),
) -> InboundTicketResponse:
    result = await ticket_service.process_inbound_ticket(
        db=db,
        tenant_id=payload.tenant_id,
        channel=payload.channel,
        customer_email=payload.customer_email,
        customer_external_id=payload.customer_external_id,
        content=payload.content,
        subject=payload.subject,
        external_conversation_id=payload.external_conversation_id,
        metadata=payload.metadata,
    )
    return InboundTicketResponse(**result)
