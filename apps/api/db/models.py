"""Modelos Pydantic que reflejan filas de Supabase.

Sólo incluyen los campos que el código de la API y el grafo realmente usan.
Si más adelante hace falta un campo, se agrega aquí — no expongas columnas
"por las dudas".
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Enums espejados desde supabase/migrations/20260513000000_initial_schema.sql
MessageRole = Literal["customer", "agent_ai", "agent_human", "system"]
MessageDirection = Literal["inbound", "outbound"]
ConversationStatus = Literal[
    "open", "pending", "resolved", "escalated", "closed", "closed_abandoned"
]
EscalationStatus = Literal["pending", "claimed", "resolved"]
ChannelType = Literal[
    "email", "chat", "widget", "whatsapp", "instagram", "zendesk", "intercom", "chatwoot"
]
UserRole = Literal["super_admin", "tenant_admin", "tenant_agent"]


class _BaseModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Tenant(_BaseModel):
    id: UUID
    slug: str
    name: str
    status: str


class TenantConfiguration(_BaseModel):
    tenant_id: UUID
    agent_model: str
    escalation_threshold: float
    active_channels: list[ChannelType] = Field(default_factory=list)
    branding: dict = Field(default_factory=dict)
    extra: dict = Field(default_factory=dict)


class EndCustomer(_BaseModel):
    id: UUID
    tenant_id: UUID
    email: str | None = None
    phone: str | None = None
    external_id: str | None = None
    full_name: str | None = None
    metadata: dict = Field(default_factory=dict)


class Conversation(_BaseModel):
    id: UUID
    tenant_id: UUID
    end_customer_id: UUID
    channel: ChannelType
    external_id: str | None = None
    subject: str | None = None
    status: ConversationStatus
    assigned_user_id: UUID | None = None
    last_message_at: datetime | None = None
    created_at: datetime | None = None


class Message(_BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    role: MessageRole
    direction: MessageDirection
    author_user_id: UUID | None = None
    content: str
    attachments: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class Escalation(_BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    reason: str
    triggered_by_message_id: UUID | None = None
    status: EscalationStatus
    assigned_user_id: UUID | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class KnowledgeChunk(_BaseModel):
    """Resultado de búsqueda RAG. No mapea 1:1 a la tabla — incluye similitud + título del doc."""

    id: UUID
    document_id: UUID
    document_title: str
    content: str
    similarity: float  # 0.0 - 1.0 (1.0 = idéntico)


# ─── AOPs ────────────────────────────────────────────────────────────────────

AopWorkspace = Literal["production", "staging"]


class Aop(_BaseModel):
    id: UUID
    tenant_id: UUID
    slug: str
    workspace: AopWorkspace
    current_version: int
    is_active: bool
    created_at: datetime | None = None


class AopVersion(_BaseModel):
    id: UUID
    aop_id: UUID
    tenant_id: UUID
    version: int
    yaml_frontmatter: dict
    body_markdown: str
    raw_source: str
    created_by: UUID | None = None
    created_at: datetime


class AopWithContent(_BaseModel):
    """AOP + contenido de su versión actual — lo que el compiler y select_aop necesitan."""

    id: UUID
    tenant_id: UUID
    slug: str
    workspace: AopWorkspace
    current_version: int
    is_active: bool = True
    yaml_frontmatter: dict
    body_markdown: str
    raw_source: str


class IntentClassifierRun(_BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    turn_number: int
    primary_slug: str
    primary_confidence: float
    alternative_slug: str | None = None
    alternative_confidence: float | None = None
    ambiguity_detected: bool
    was_reclassification: bool
    human_correction: str | None = None
    created_at: datetime
