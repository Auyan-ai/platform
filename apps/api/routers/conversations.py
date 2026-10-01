"""Endpoints de conversaciones para agentes humanos."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from apps.api.core.config import Settings, get_settings
from apps.api.core.errors import NotFoundError
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id
from apps.api.db.client import tenant_scope
from apps.api.db.models import ChannelType, ConversationStatus, EscalationStatus, MessageRole
from apps.api.db.queries import get_active_handoff_for_chat, get_conversation_message
from apps.api.services.channel_routing import is_messaging_channel
from apps.api.services.conversations import (
    close_conversation,
    escalate_conversation,
    get_closable_conversation,
    get_conversation_detail,
    list_tenant_conversations,
    reply_to_conversation,
)
from apps.api.services.helpdesk_closure import close_external_helpdesk_ticket
from apps.api.services.media_storage import SIGNED_URL_SECONDS, create_signed_url
from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class MessageAttachmentOut(BaseModel):
    """Solo nombre y tipo: la vista previa (URL firmada) va aparte."""

    filename: str
    kind: str
    mime_type: str | None = None


class AttachmentUrlOut(BaseModel):
    """URL firmada de vida corta para ver un adjunto del bucket privado."""

    url: str
    expires_in: int
    filename: str
    kind: str
    mime_type: str | None = None


def _listed_attachments(raw: Any) -> list[dict[str, Any]]:
    """Adjuntos que muestra el inbox, en orden. Mismo listado para `MessageOut` y para la
    vista previa: el índice que manda la web apunta al mismo adjunto."""
    return [a for a in (raw or []) if isinstance(a, dict) and (a.get("path") or a.get("filename"))]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: MessageRole
    direction: str
    author_user_id: UUID | None
    content: str
    created_at: datetime
    # Autor de la marca fuera de Auyan (Zendesk, app de WhatsApp Business…): {provider, name}.
    external_author: dict[str, str | None] | None = None
    attachments: list[MessageAttachmentOut] = Field(default_factory=list)
    # Estado de entrega en mensajería: delivered | pending_window | failed.
    delivery: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _from_message(cls, data: Any) -> Any:
        metadata = getattr(data, "metadata", None)
        if not isinstance(metadata, dict):
            return data
        author = metadata.get("external_author")
        raw_attachments = getattr(data, "attachments", None) or []
        return {
            "id": data.id,
            "conversation_id": data.conversation_id,
            "role": data.role,
            "direction": data.direction,
            "author_user_id": data.author_user_id,
            "content": data.content,
            "created_at": data.created_at,
            "external_author": (
                {"provider": author.get("provider"), "name": author.get("name")}
                if isinstance(author, dict)
                else None
            ),
            "attachments": [
                {
                    "filename": a.get("filename") or str(a.get("path", "")).rsplit("/", 1)[-1],
                    "kind": a.get("kind") or "file",
                    "mime_type": a.get("mime_type"),
                }
                for a in _listed_attachments(raw_attachments)
            ],
            "delivery": metadata.get("delivery"),
        }


class ConversationListResponse(BaseModel):
    conversations: list[ConversationOut]
    limit: int
    offset: int


class HandoffOut(BaseModel):
    """Handoff activo: un humano de la marca lleva la conversación y la IA calla."""

    model_config = ConfigDict(from_attributes=True)

    target: Literal["helpdesk", "device"]
    helpdesk_provider: str | None
    external_ticket_id: str | None
    opened_at: datetime
    expires_at: datetime | None


class ConversationDetailResponse(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
    active_handoff: HandoffOut | None = None


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
        handoff = None
        if is_messaging_channel(conv.channel) and conv.external_id:
            handoff = await get_active_handoff_for_chat(
                conn, tenant_id, conv.channel, conv.external_id
            )
    return ConversationDetailResponse(
        conversation=ConversationOut.model_validate(conv),
        messages=[MessageOut.model_validate(m) for m in messages],
        active_handoff=HandoffOut.model_validate(handoff) if handoff else None,
    )


@router.get(
    "/{conversation_id}/messages/{message_id}/attachments/{index}",
    response_model=AttachmentUrlOut,
    summary="URL firmada (vida corta) para ver un adjunto del comprador",
)
async def get_attachment_url(
    conversation_id: UUID,
    message_id: UUID,
    tenant_id: TenantIdDep,
    index: Annotated[int, Path(ge=0)],
) -> AttachmentUrlOut:
    async with tenant_scope(tenant_id) as conn:
        message = await get_conversation_message(conn, tenant_id, conversation_id, message_id)
    attachments = _listed_attachments(message.attachments if message else None)
    item = attachments[index] if index < len(attachments) else None
    path = str(item.get("path") or "") if item else ""
    # La ruta del adjunto empieza siempre por el tenant y la conversación (media_storage):
    # defensa en profundidad para no firmar nunca un objeto de otro tenant.
    if not path.startswith(f"{tenant_id}/{conversation_id}/"):
        raise NotFoundError("attachment not found", code="attachment_not_found")
    url = await create_signed_url(path)
    return AttachmentUrlOut(
        url=url,
        expires_in=SIGNED_URL_SECONDS,
        filename=str(item.get("filename") or path.rsplit("/", 1)[-1]),
        kind=str(item.get("kind") or "file"),
        mime_type=item.get("mime_type"),
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
        escalation = await escalate_conversation(conn, tenant_id, conversation_id, body.reason)
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
