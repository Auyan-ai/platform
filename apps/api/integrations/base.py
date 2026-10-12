"""Protocols base para todos los adapters de integración.

Jerarquía:
- MessageProvider  → cualquier canal que puede recibir/enviar mensajes.
- HelpdeskProvider → extends MessageProvider con operaciones propias de helpdesk.
- CommerceProvider → operaciones de lectura/escritura sobre plataformas commerce.

Los adapters concretos (chatwoot.py, zendesk.py, ...) implementan estos Protocols
sin herencia explícita — Python structural typing los valida en tiempo de type-check.

IntegrationContext encapsula las credenciales descifradas + config del tenant
para esa integración específica. Los adapters son stateless; reciben ctx por llamada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

# ─── Tipos de datos compartidos ───────────────────────────────────────────────


@dataclass(frozen=True)
class InboundMessage:
    """Mensaje entrante normalizado desde cualquier canal."""

    external_id: str
    channel: str
    content: str
    sender_email: str | None = None
    sender_name: str | None = None
    subject: str | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalTicketRef:
    """Referencia a un ticket creado en el helpdesk externo tras push_escalation."""

    provider: str
    ticket_id: str
    url: str | None = None


@dataclass(frozen=True)
class IntegrationContext:
    """Credenciales descifradas + config para un tenant/integración específicos.

    Construido por el service layer antes de llamar a cualquier método del adapter.
    Nunca persiste credenciales en plaintext más allá del scope de la request.
    """

    tenant_id: UUID
    credentials: dict[str, Any]
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredAttachment:
    """Adjunto del comprador ya guardado en Storage (bucket privado `conversation-media`)."""

    path: str
    mime_type: str
    size: int
    filename: str
    kind: str = "file"  # image | audio | video | file | sticker
    # Bytes cargados por el service layer justo antes de subirlos al helpdesk.
    content: bytes | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class HandoffRequest:
    """Datos para abrir el ticket de handoff en el helpdesk del cliente (ADR 0010).

    Todo es literal y formateado por código: la transcripción son los mensajes tal cual
    y el único texto del LLM es `reason` (el motivo del escalado).
    """

    conversation_id: UUID
    customer_name: str | None
    customer_phone: str | None
    customer_email: str | None
    customer_ref: str  # "auyan:<end_customer_id>" → external_id del usuario en el helpdesk
    subject: str
    reason: str
    transcript: str
    window_closes_at: datetime | None
    attachments: list[StoredAttachment]
    channel_label: str  # "WhatsApp"


# ─── Protocols ────────────────────────────────────────────────────────────────


class MessageProvider(Protocol):
    """Canal bidireccional básico: recibe webhooks y envía mensajes."""

    async def parse_inbound_webhook(self, payload: dict[str, Any]) -> InboundMessage: ...

    async def send_outbound(
        self,
        ctx: IntegrationContext,
        conversation_ref: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
    ) -> Any: ...


class HelpdeskProvider(MessageProvider, Protocol):
    """Helpdesk bidireccional completo: extiende MessageProvider con ops de ticket."""

    async def add_internal_note(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        content: str,
    ) -> None: ...

    async def assign_to_human(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        reason: str,
    ) -> None: ...

    async def update_status(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        status: str,
    ) -> None: ...

    async def push_escalation(
        self,
        ctx: IntegrationContext,
        conversation_ref: str,
        reason: str,
        agent_context: dict[str, Any],
    ) -> ExternalTicketRef: ...


class CommerceProvider(Protocol):
    """Plataforma commerce: lectura de pedidos, clientes, productos."""

    async def get_order(
        self,
        ctx: IntegrationContext,
        order_id: str,
    ) -> dict[str, Any]: ...

    async def search_orders_by_email(
        self,
        ctx: IntegrationContext,
        email: str,
    ) -> list[dict[str, Any]]: ...

    async def search_orders_by_phone(
        self,
        ctx: IntegrationContext,
        phone: str,
    ) -> list[dict[str, Any]]: ...


class HandoffTarget(Protocol):
    """Helpdesk que puede recibir un handoff desde un canal de mensajería.

    Zendesk es la primera implementación; Gorgias/Chatwoot usarán la misma interfaz.
    """

    async def open_handoff_ticket(
        self, ctx: IntegrationContext, req: HandoffRequest
    ) -> ExternalTicketRef: ...

    async def append_customer_message(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        content: str,
        attachments: list[StoredAttachment],
        *,
        requester_ref: str | None = None,
    ) -> None: ...

    async def add_internal_note(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        content: str,
    ) -> None: ...
