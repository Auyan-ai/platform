"""Endpoints de conversaciones para agentes humanos."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from apps.api.core.config import Settings, get_settings
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id
from apps.api.db.client import tenant_scope
from apps.api.db.models import ChannelType, ConversationStatus, EscalationStatus, MessageRole
from apps.api.services.conversations import (
    close_conversation,
    escalate_conversation,
    get_closable_conversation,
    get_conversation_detail,
    list_tenant_conversations,
    reply_to_conversation,
)
from apps.api.services.helpdesk_closure import close_external_helpdesk_ticket
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/conversations", tags=["conversations"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# ----------------------------------------------------------------
# Response schemas
# ----------------------------------------------------------------


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    end_customer_id: UUID
    channel: ChannelType
    external_id: str | None
    subject: str | None
    status: ConversationStatus
    assigned_user_id: UUID | None
    last_message_at: datetime | None
    created_at: datetime | None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: MessageRole
    direction: str
    author_user_id: UUID | None
    content: str
    created_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationOut]
    limit: int
    offset: int


class ConversationDetailResponse(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]


class EscalationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    reason: str
    status: EscalationStatus
    assigned_user_id: UUID | None
    created_at: datetime | None


# ----------------------------------------------------------------
# Request schemas
# ----------------------------------------------------------------


class ReplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=20_000)


class EscalateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1_000)


# ----------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------


@router.get(
    "",
    response_model=ConversationListResponse,
    summary="Listar conversaciones del tenant",
)
async def list_conversations(
    tenant_id: TenantIdDep,
    status: Annotated[ConversationStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationListResponse:
    async with tenant_scope(tenant_id) as conn:
        convs = await list_tenant_conversations(
            conn, tenant_id, status=status, limit=limit, offset=offset
        )
    return ConversationListResponse(
        conversations=[ConversationOut.model_validate(c) for c in convs],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="Detalle de una conversación con sus mensajes",
)
async def get_conversation(
    conversation_id: UUID,
    tenant_id: TenantIdDep,
    include_system: Annotated[bool, Query()] = False,
) -> ConversationDetailResponse:
    async with tenant_scope(tenant_id) as conn:
        conv, messages = await get_conversation_detail(
            conn, tenant_id, conversation_id, include_system=include_system
        )
    return ConversationDetailResponse(
        conversation=ConversationOut.model_validate(conv),
        messages=[MessageOut.model_validate(m) for m in messages],
    )


@router.post(
    "/{conversation_id}/reply",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Agente humano responde a la conversación",
)
async def reply(
    conversation_id: UUID,
    body: ReplyBody,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> MessageOut:
    async with tenant_scope(tenant_id) as conn:
        msg = await reply_to_conversation(
            conn, tenant_id, conversation_id, auth.user_id, body.content
        )
    return MessageOut.model_validate(msg)


@router.post(
    "/{conversation_id}/escalate",
    response_model=EscalationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Escalar conversación manualmente",
)
async def escalate(
    conversation_id: UUID,
    body: EscalateBody,
    tenant_id: TenantIdDep,
) -> EscalationOut:
    async with tenant_scope(tenant_id) as conn:
        escalation = await escalate_conversation(
            conn, tenant_id, conversation_id, body.reason
        )
    return EscalationOut.model_validate(escalation)


@router.post(
    "/{conversation_id}/close",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cerrar conversación",
)
async def close(
    conversation_id: UUID,
    tenant_id: TenantIdDep,
    settings: SettingsDep,
) -> Response:
    async with tenant_scope(tenant_id) as conn:
        conversation = await get_closable_conversation(conn, tenant_id, conversation_id)

    await close_external_helpdesk_ticket(
        tenant_id=tenant_id,
        conversation=conversation,
        settings=settings,
    )

    async with tenant_scope(tenant_id) as conn:
        await close_conversation(conn, tenant_id, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
