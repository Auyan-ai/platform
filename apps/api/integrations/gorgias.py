"""Adapter HTTP para Gorgias.

Dos capas:
- `GorgiasClient`: cliente HTTP con estado (domain + token en __init__).
- `GorgiasAdapter`: adapter stateless registrado en IntegrationRegistry. Recibe
  IntegrationContext por llamada — habilita multi-tenant real (un adapter, N accounts).

Credentials esperadas en IntegrationContext (uno de los dos modos de auth):
    OAuth2 (vía /oauth/gorgias):   {"oauth_token": "..."}              # Authorization: Bearer
    API Key / Basic (managed):     {"email": "...", "api_key": "..."}  # Authorization: Basic
    {
        "webhook_signing_secret": "..."   # opcional — valida X-Gorgias-Hmac-Sha256
    }

Config esperada en IntegrationContext:
    {
        "domain":              "mycompany",  # {domain}.gorgias.com
        "escalation_team_id": "123"          # opcional — equipo al que asignar escalaciones
    }

Verificación de firma HMAC:
    - Header X-Gorgias-Hmac-Sha256 (base64-HMAC-SHA256 del raw body)
    - Si webhook_signing_secret no está en credentials, se acepta sin firma.

Estructura del webhook de Gorgias (evento ticket-message-created):
    {
        "event": {"type": "ticket-message-created"},
        "data": {
            "ticket": {"id": 123, "subject": "...", "status": "open", "channel": "email"},
            "message": {
                "id": 456, "body_text": "...", "from_agent": false,
                "sender": {"email": "...", "name": "..."}
            }
        },
        "meta": {"domain": "mycompany"}
    }
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Any

import httpx
from apps.api.integrations.base import (
    ExternalTicketRef,
    HelpdeskProvider,
    InboundMessage,
    IntegrationContext,
)
from apps.api.integrations.registry import IntegrationRegistry

logger = logging.getLogger(__name__)


# ─── Verificación de firma ─────────────────────────────────────────────────────


def verify_gorgias_signature(raw_body: bytes, secret: str, received_sig: str) -> bool:
    """Verifica la firma HMAC-SHA256 base64 del webhook de Gorgias."""
    mac = hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode()
    return hmac.compare_digest(expected, received_sig)


# ─── Cliente HTTP con estado ───────────────────────────────────────────────────


class GorgiasClient:
    def __init__(
        self,
        domain: str,
        *,
        oauth_token: str | None = None,
        email: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Acepta dos modos de auth: OAuth2 (oauth_token → Bearer) o
        API Key (email + api_key → Basic). Exactamente uno debe venir poblado.
        """
        if oauth_token is None and not (email and api_key):
            raise ValueError(
                "GorgiasClient requiere oauth_token (OAuth2) o email+api_key (Basic auth)"
            )
        self._domain = domain
        self._oauth_token = oauth_token
        self._email = email
        self._api_key = api_key

    @property
    def base_url(self) -> str:
        return f"https://{self._domain}.gorgias.com/api"

    def _headers(self) -> dict[str, str]:
        if self._oauth_token is not None:
            authorization = f"Bearer {self._oauth_token}"
        else:
            raw = f"{self._email}:{self._api_key}".encode()
            authorization = f"Basic {base64.b64encode(raw).decode()}"
        return {
            "Authorization": authorization,
            "Content-Type": "application/json",
        }

    # ── Mensajes ──────────────────────────────────────────────────────────────

    async def send_message(self, ticket_id: int, body_text: str) -> dict[str, Any]:
        """Envía un mensaje público outbound al cliente en el ticket."""
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/tickets/{ticket_id}/messages",
                headers=self._headers(),
                json={
                    "body_text": body_text,
                    "channel": "email",
                    "from_agent": True,
                    "source": {"type": "agent", "from": {}, "to": []},
                },
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def send_internal_note(self, ticket_id: int, body_text: str) -> dict[str, Any]:
        """Añade una nota interna al ticket (channel=note, no visible al cliente)."""
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/tickets/{ticket_id}/messages",
                headers=self._headers(),
                json={
                    "body_text": body_text,
                    "channel": "note",
                    "from_agent": True,
                },
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    # ── Gestión de ticket ─────────────────────────────────────────────────────

    async def update_status(self, ticket_id: int, status: str) -> None:
        """Cambia el status del ticket (open | closed)."""
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.put(
                f"{self.base_url}/tickets/{ticket_id}",
                headers=self._headers(),
                json={"status": status},
            )
            response.raise_for_status()

    async def assign_to_team(self, ticket_id: int, team_id: int) -> None:
        """Asigna el ticket a un equipo."""
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.put(
                f"{self.base_url}/tickets/{ticket_id}",
                headers=self._headers(),
                json={"assignee_team": {"id": team_id}},
            )
            response.raise_for_status()


# ─── Adapter stateless — implementa HelpdeskProvider ──────────────────────────


@IntegrationRegistry.register(kind="helpdesk", provider="gorgias")
class GorgiasAdapter:
    """HelpdeskProvider stateless para Gorgias.

    Crea un GorgiasClient por llamada a partir de las credenciales en IntegrationContext.
    """

    def _client(self, ctx: IntegrationContext) -> GorgiasClient:
        creds = ctx.credentials
        return GorgiasClient(
            domain=ctx.config["domain"],
            oauth_token=creds.get("oauth_token"),
            email=creds.get("email"),
            api_key=creds.get("api_key"),
        )

    # ── MessageProvider ───────────────────────────────────────────────────────

    async def parse_inbound_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        """Normaliza un webhook Gorgias ticket-message-created en InboundMessage.

        Debe llamarse solo para payloads con event.type=ticket-message-created
        y message.from_agent=false (verificado en el router antes de llegar aquí).
        """
        data = payload.get("data") or {}
        message = data.get("message") or {}
        ticket = data.get("ticket") or {}
        sender = message.get("sender") or {}

        ticket_id = str(ticket.get("id", ""))
        message_id = str(message.get("id", ""))
        external_id = f"{ticket_id}:{message_id}" if message_id else ticket_id

        return InboundMessage(
            external_id=external_id,
            channel="gorgias",
            content=message.get("body_text") or "",
            sender_email=sender.get("email"),
            sender_name=sender.get("name"),
            subject=ticket.get("subject"),
            raw_payload=payload,
        )

    async def send_outbound(
        self,
        ctx: IntegrationContext,
        conversation_ref: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        """Envía un mensaje público al cliente en el ticket."""
        await self._client(ctx).send_message(int(conversation_ref), content)

    # ── HelpdeskProvider ──────────────────────────────────────────────────────

    async def add_internal_note(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        content: str,
    ) -> None:
        """Añade una nota interna al ticket (channel=note)."""
        await self._client(ctx).send_internal_note(int(ticket_ref), content)

    async def assign_to_human(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        reason: str,
    ) -> None:
        """Asigna al equipo de escalación configurado. No-op si no hay team_id."""
        team_id_str = ctx.config.get("escalation_team_id")
        if team_id_str:
            await self._client(ctx).assign_to_team(int(ticket_ref), int(team_id_str))

    async def update_status(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        status: str,
    ) -> None:
        """Cambia el status del ticket en Gorgias."""
        await self._client(ctx).update_status(int(ticket_ref), status)

    async def push_escalation(
        self,
        ctx: IntegrationContext,
        conversation_ref: str,
        reason: str,
        agent_context: dict[str, Any],
    ) -> ExternalTicketRef:
        """Escala el ticket: nota interna + asignación al equipo.

        1. Añade nota interna con el motivo y contexto del agente.
        2. Asigna al equipo de escalación si está configurado.
        """
        client = self._client(ctx)
        ticket_id = int(conversation_ref)

        summary_parts = [f"🚨 Escalado a soporte humano: {reason}"]
        if agent_context:
            ctx_json = json.dumps(agent_context, ensure_ascii=False, indent=2)
            summary_parts.append(f"Contexto del agente:\n{ctx_json}")
        await client.send_internal_note(ticket_id, "\n\n".join(summary_parts))

        team_id_str = ctx.config.get("escalation_team_id")
        if team_id_str:
            await client.assign_to_team(ticket_id, int(team_id_str))

        domain = ctx.config["domain"]
        return ExternalTicketRef(
            provider="gorgias",
            ticket_id=conversation_ref,
            url=f"https://{domain}.gorgias.com/app/ticket/{conversation_ref}",
        )


# Satisface el type-checker: GorgiasAdapter implementa HelpdeskProvider estructuralmente.
_: HelpdeskProvider = GorgiasAdapter()  # type: ignore[assignment]
