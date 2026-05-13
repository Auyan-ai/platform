import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, EmailStr


class UserRole(str, Enum):
    super_admin = "super_admin"
    tenant_admin = "tenant_admin"
    tenant_agent = "tenant_agent"


class ChannelType(str, Enum):
    email = "email"
    chat = "chat"
    widget = "widget"
    whatsapp = "whatsapp"
    instagram = "instagram"
    zendesk = "zendesk"
    intercom = "intercom"
    chatwoot = "chatwoot"


class ConversationStatus(str, Enum):
    open = "open"
    pending = "pending"
    resolved = "resolved"
    escalated = "escalated"
    closed = "closed"


class MessageRole(str, Enum):
    customer = "customer"
    agent_ai = "agent_ai"
    agent_human = "agent_human"
    system = "system"


class MessageDirection(str, Enum):
    inbound = "inbound"
    outbound = "outbound"


class EscalationStatus(str, Enum):
    pending = "pending"
    claimed = "claimed"
    resolved = "resolved"


class Tenant(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class User(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    email: EmailStr
    full_name: str | None
    role: UserRole
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class EndCustomer(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str | None
    phone: str | None
    external_id: str | None
    full_name: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class Conversation(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    end_customer_id: uuid.UUID
    channel: ChannelType
    external_id: str | None
    subject: str | None
    status: ConversationStatus
    assigned_user_id: uuid.UUID | None
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class Message(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    direction: MessageDirection
    author_user_id: uuid.UUID | None
    content: str
    attachments: list[Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class Escalation(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    reason: str
    triggered_by_message_id: uuid.UUID | None
    status: EscalationStatus
    assigned_user_id: uuid.UUID | None
    claimed_at: datetime | None
    resolved_at: datetime | None
    resolution_notes: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class TenantConfiguration(BaseModel):
    tenant_id: uuid.UUID
    agent_model: str
    escalation_threshold: float
    active_channels: list[ChannelType]
    branding: dict[str, Any]
    extra: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TenantPrompt(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    version: int
    content: str
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime
    deleted_at: datetime | None = None
