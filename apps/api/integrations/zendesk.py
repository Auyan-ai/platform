"""Adapter HTTP para Zendesk.

Dos capas:
- `ZendeskClient`: cliente HTTP con estado (subdomain + token en __init__).
- `ZendeskAdapter`: adapter stateless registrado en IntegrationRegistry. Recibe
  IntegrationContext por llamada — habilita multi-tenant real (un adapter, N accounts).

Credentials esperadas en IntegrationContext:
    {
        "oauth_token":            "...",  # Bearer token OAuth (preferido)
        "webhook_signing_secret": "..."   # opcional — valida X-Zendesk-Webhook-Signature
    }

Config esperada en IntegrationContext:
    {
        "subdomain":           "mycompany",  # {subdomain}.zendesk.com
        "escalation_group_id": "123"         # opcional — grupo al que asignar escalaciones
    }

Payload esperado en el webhook de Zendesk (configurar en el Trigger de Zendesk):
    {
        "ticket_id":       "{{ticket.id}}",
        "subject":         "{{ticket.title}}",
        "content":         "{{ticket.latest_comment_html_stripped}}",
        "requester_email": "{{ticket.requester.email}}",
        "requester_name":  "{{ticket.requester.name}}",
        "subdomain":       "hardcoded-subdomain"
    }

    Nota: Zendesk no tiene variable {{subdomain}}.  El subdomain se hardcodea
    en la configuración del Trigger una sola vez por cuenta.

Verificación de firma HMAC:
    - Header X-Zendesk-Webhook-Signature (base64-HMAC-SHA256)
    - Header X-Zendesk-Webhook-Signature-Timestamp (Unix timestamp string)
    - Mensaje firmado: timestamp_bytes + raw_body_bytes  (concatenación directa)
    - Si webhook_signing_secret no está en credentials, se acepta sin firma.
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


# ─── Cliente HTTP con estado ───────────────────────────────────────────────────


class ZendeskClient:
    def __init__(self, subdomain: str, oauth_token: str) -> None:
        self._subdomain = subdomain
        self._token = oauth_token

    @property
    def base_url(self) -> str:
        return f"https://{self._subdomain}.zendesk.com/api/v2"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    # ── Comentarios / respuestas ──────────────────────────────────────────────

    async def add_comment(
        self, ticket_id: str, body: str, public: bool = True
    ) -> dict[str, Any]:
        """Agrega un comentario público o privado (nota interna) al ticket."""
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.base_url}/tickets/{ticket_id}.json",
                headers=self._headers(),
                json={"ticket": {"comment": {"body": body, "public": public}}},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["ticket"]  # type: ignore[no-any-return]

    # ── Gestión del ticket ────────────────────────────────────────────────────

    async def update_ticket(
        self,
        ticket_id: str,
        *,
        status: str | None = None,
        group_id: int | None = None,
        comment_body: str | None = None,
        comment_public: bool = False,
    ) -> dict[str, Any]:
        """Actualiza campos del ticket en una sola llamada (status, grupo, comentario)."""
        ticket_update: dict[str, Any] = {}
        if status is not None:
            ticket_update["status"] = status
        if group_id is not None:
            ticket_update["group_id"] = group_id
        if comment_body is not None:
            ticket_update["comment"] = {"body": comment_body, "public": comment_public}

        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.base_url}/tickets/{ticket_id}.json",
                headers=self._headers(),
                json={"ticket": ticket_update},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["ticket"]  # type: ignore[no-any-return]


# ─── Verificación de firma HMAC ────────────────────────────────────────────────


def verify_zendesk_signature(
    *,
    signing_secret: str,
    timestamp: str,
    raw_body: bytes,
    signature_header: str,
) -> bool:
    """Verifica la firma HMAC-SHA256 de un webhook de Zendesk.

    Zendesk firma el mensaje como HMAC-SHA256(signing_secret, timestamp + raw_body)
    y lo codifica en base64.
    """
    msg = timestamp.encode() + raw_body
    expected = base64.b64encode(
        hmac.new(
            key=signing_secret.encode(),
            msg=msg,
            digestmod=hashlib.sha256,
        ).digest()
    ).decode()
    return hmac.compare_digest(expected, signature_header)


# ─── Adapter stateless — implementa HelpdeskProvider ──────────────────────────


@IntegrationRegistry.register(kind="helpdesk", provider="zendesk")
class ZendeskAdapter:
    """HelpdeskProvider stateless para Zendesk.

    Crea un ZendeskClient por llamada a partir de las credenciales en IntegrationContext.
    """

    def _client(self, ctx: IntegrationContext) -> ZendeskClient:
        return ZendeskClient(
            subdomain=ctx.config["subdomain"],
            oauth_token=ctx.credentials["oauth_token"],
        )

    # ── MessageProvider ───────────────────────────────────────────────────────

    async def parse_inbound_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        """Normaliza un webhook Zendesk en InboundMessage.

        Espera el payload estándar documentado en el módulo (configurado en el Trigger).
        """
        return InboundMessage(
            external_id=str(payload["ticket_id"]),
            channel="zendesk",
            content=payload.get("content") or "",
            sender_email=payload.get("requester_email"),
            sender_name=payload.get("requester_name"),
            subject=payload.get("subject"),
            raw_payload=payload,
        )

    async def send_outbound(
        self,
        ctx: IntegrationContext,
        conversation_ref: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        """Envía una respuesta pública al requester del ticket."""
        await self._client(ctx).add_comment(conversation_ref, content, public=True)

    # ── HelpdeskProvider ──────────────────────────────────────────────────────

    async def add_internal_note(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        content: str,
    ) -> None:
        """Agrega una nota interna (privada) al ticket."""
        await self._client(ctx).add_comment(ticket_ref, content, public=False)

    async def assign_to_human(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        reason: str,
    ) -> None:
        """Asigna el ticket al grupo de escalación configurado. No-op si no hay group_id."""
        group_id_str = ctx.config.get("escalation_group_id")
        if group_id_str:
            await self._client(ctx).update_ticket(
                ticket_ref, group_id=int(group_id_str)
            )

    async def update_status(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        status: str,
    ) -> None:
        """Cambia el status del ticket en Zendesk (open, pending, solved, etc.)."""
        await self._client(ctx).update_ticket(ticket_ref, status=status)

    async def push_escalation(
        self,
        ctx: IntegrationContext,
        conversation_ref: str,
        reason: str,
        agent_context: dict[str, Any],
    ) -> ExternalTicketRef:
        """Escala el ticket: nota interna + status pending + asignación a grupo.

        Hace una sola llamada a la API combinando status + group_id + comment
        para minimizar la latencia.
        """
        summary_parts = [f"🚨 Escalado a soporte humano: {reason}"]
        if agent_context:
            ctx_json = json.dumps(agent_context, ensure_ascii=False, indent=2)
            summary_parts.append(f"Contexto del agente:\n{ctx_json}")
        note = "\n\n".join(summary_parts)

        group_id_str = ctx.config.get("escalation_group_id")
        group_id = int(group_id_str) if group_id_str else None

        await self._client(ctx).update_ticket(
            conversation_ref,
            status="pending",
            group_id=group_id,
            comment_body=note,
            comment_public=False,
        )

        subdomain = ctx.config["subdomain"]
        return ExternalTicketRef(
            provider="zendesk",
            ticket_id=conversation_ref,
            url=f"https://{subdomain}.zendesk.com/agent/tickets/{conversation_ref}",
        )


# Satisface el type-checker: ZendeskAdapter implementa HelpdeskProvider estructuralmente.
_: HelpdeskProvider = ZendeskAdapter()  # type: ignore[assignment]
