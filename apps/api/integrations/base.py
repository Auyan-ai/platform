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


# ─── Protocols ────────────────────────────────────────────────────────────────


class MessageProvider(Protocol):
    """Canal bidireccional básico: recibe webhooks y envía mensajes."""

    async def parse_inbound_webhook(
        self, payload: dict[str, Any]
    ) -> InboundMessage: ...

    async def send_outbound(
        self,
        ctx: IntegrationContext,
        conversation_ref: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None: ...


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

    async def get_customer_by_email(
        self,
        ctx: IntegrationContext,
        email: str,
    ) -> dict[str, Any] | None: ...
