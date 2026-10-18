"""Adapter HTTP para Chatwoot Cloud / self-hosted.

Dos capas:
- `ChatwootClient`: cliente HTTP con estado (base_url + token + account_id en __init__).
- `ChatwootAdapter`: adapter stateless registrado en IntegrationRegistry. Recibe
  IntegrationContext por llamada — habilita multi-tenant real (un adapter, N accounts).

Credentials esperadas en IntegrationContext:
    {
        "api_access_token": "...",
        "webhook_secret_token": "..."   # opcional — valida HMAC de webhooks Chatwoot
    }

Config esperada en IntegrationContext:
    {
        "base_url": "https://app.chatwoot.com",
        "account_id": "1",              # int como string (JSON keys son strings)
        "escalation_team_id": "5"       # opcional — team al que asignar escalaciones
    }
"""

from __future__ import annotations

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


def verify_chatwoot_signature(
    *,
    signing_secret: str,
    timestamp: str,
    raw_body: bytes,
    signature_header: str,
) -> bool:
    """Valida la firma HMAC-SHA256 de webhooks Chatwoot Cloud.

    Chatwoot firma `"{timestamp}.{raw_body}"` y envía el digest como
    `X-Chatwoot-Signature: sha256=<hex>`.
    """
    if not signature_header.startswith("sha256=") or not timestamp:
        return False

    message = timestamp.encode() + b"." + raw_body
    expected = "sha256=" + hmac.new(signing_secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# ─── Cliente HTTP con estado ───────────────────────────────────────────────────


class ChatwootClient:
    def __init__(self, base_url: str, api_access_token: str, account_id: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = api_access_token
        self._account_id = account_id

    def _headers(self) -> dict[str, str]:
        return {"api_access_token": self._token, "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return f"{self._base_url}/api/v1/accounts/{self._account_id}{path}"

    # ── Validación y registro de webhook ──────────────────────────────────────

    async def validate(self) -> dict[str, Any]:
        """Verifica token + account_id contra la cuenta. Devuelve el objeto account.

        Lanza httpx.HTTPStatusError si las credenciales son inválidas.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(self._url(""), headers=self._headers(), timeout=10)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def list_webhooks(self) -> list[dict[str, Any]]:
        """Lista los webhooks de cuenta ya registrados (para evitar duplicados)."""
        async with httpx.AsyncClient() as client:
            response = await client.get(self._url("/webhooks"), headers=self._headers(), timeout=10)
            response.raise_for_status()
            payload = response.json()
        # Chatwoot devuelve {"payload": [...]} o una lista plana según versión.
        if isinstance(payload, dict):
            webhooks = payload.get("payload", [])
            return webhooks if isinstance(webhooks, list) else []
        return payload if isinstance(payload, list) else []

    async def create_webhook(self, url: str, subscriptions: list[str]) -> dict[str, Any]:
        """Registra un webhook de cuenta que apunta a Auyan.

        Chatwoot no expone vía API un secreto de firma usable (bug chatwoot#13809),
        así que el handler entrante acepta este webhook sin verificar HMAC.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._url("/webhooks"),
                headers=self._headers(),
                json={"url": url, "subscriptions": subscriptions},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    # ── Mensajes ─────────────────────────────────────────────────────────────

    async def send_message(self, conversation_id: int, content: str) -> dict[str, Any]:
        """Envía un mensaje público outbound al cliente."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._url(f"/conversations/{conversation_id}/messages"),
                headers=self._headers(),
                json={"content": content, "message_type": "outgoing", "private": False},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def send_internal_note(self, conversation_id: int, content: str) -> dict[str, Any]:
        """Añade una nota interna (private) visible solo para agentes."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._url(f"/conversations/{conversation_id}/messages"),
                headers=self._headers(),
                json={"content": content, "message_type": "outgoing", "private": True},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    # ── Gestión de conversación ───────────────────────────────────────────────

    async def update_status(self, conversation_id: int, status: str) -> None:
        """Cambia el status de la conversación (open, resolved, pending)."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._url(f"/conversations/{conversation_id}/toggle_status"),
                headers=self._headers(),
                json={"status": status},
                timeout=10,
            )
            response.raise_for_status()

    async def assign_to_team(self, conversation_id: int, team_id: int) -> dict[str, Any]:
        """Asigna la conversación a un equipo."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._url(f"/conversations/{conversation_id}/assignments"),
                headers=self._headers(),
                json={"team_id": team_id},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]


# ─── Adapter stateless — implementa HelpdeskProvider ──────────────────────────


@IntegrationRegistry.register(kind="helpdesk", provider="chatwoot")
class ChatwootAdapter:
    """HelpdeskProvider stateless para Chatwoot.

    Crea un ChatwootClient por llamada a partir de las credenciales en IntegrationContext.
    """

    def _client(self, ctx: IntegrationContext) -> ChatwootClient:
        return ChatwootClient(
            base_url=ctx.config["base_url"],
            api_access_token=ctx.credentials["api_access_token"],
            account_id=int(ctx.config["account_id"]),
        )

    # ── MessageProvider ───────────────────────────────────────────────────────

    async def parse_inbound_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        """Normaliza un webhook Chatwoot message_created en InboundMessage.

        Debe llamarse solo para payloads con event=message_created y
        message_type=incoming (verificado en el router antes de llegar aquí).
        """
        sender = payload.get("sender") or {}
        return InboundMessage(
            external_id=str(payload["id"]),
            channel="chatwoot",
            content=payload.get("content") or "",
            sender_email=sender.get("email"),
            sender_name=sender.get("name"),
            raw_payload=payload,
        )

    async def send_outbound(
        self,
        ctx: IntegrationContext,
        conversation_ref: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,  # sin uso: los helpdesks no lo soportan
    ) -> None:
        """Envía un mensaje público al cliente en la conversación."""
        await self._client(ctx).send_message(int(conversation_ref), content)

    # ── HelpdeskProvider ──────────────────────────────────────────────────────

    async def add_internal_note(
        self,
        ctx: IntegrationContext,
        ticket_ref: str,
        content: str,
    ) -> None:
        """Publica una nota interna (private: true) en la conversación."""
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
        """Cambia el status de la conversación en Chatwoot."""
        await self._client(ctx).update_status(int(ticket_ref), status)

    async def push_escalation(
        self,
        ctx: IntegrationContext,
        conversation_ref: str,
        reason: str,
        agent_context: dict[str, Any],
    ) -> ExternalTicketRef:
        """Escala la conversación: nota interna + asignación a equipo.

        1. Añade nota interna con el motivo y contexto del agente.
        2. Asigna al equipo de escalación si está configurado.
        """
        client = self._client(ctx)
        conv_id = int(conversation_ref)

        summary_parts = [f"🚨 Escalado a soporte humano: {reason}"]
        if agent_context:
            ctx_json = json.dumps(agent_context, ensure_ascii=False, indent=2)
            summary_parts.append(f"Contexto del agente:\n{ctx_json}")
        await client.send_internal_note(conv_id, "\n\n".join(summary_parts))

        team_id_str = ctx.config.get("escalation_team_id")
        if team_id_str:
            await client.assign_to_team(conv_id, int(team_id_str))

        base = ctx.config["base_url"].rstrip("/")
        account_id = ctx.config["account_id"]
        return ExternalTicketRef(
            provider="chatwoot",
            ticket_id=conversation_ref,
            url=f"{base}/app/accounts/{account_id}/conversations/{conversation_ref}",
        )


# Satisface el type-checker: ChatwootAdapter implementa HelpdeskProvider estructuralmente.
_: HelpdeskProvider = ChatwootAdapter()  # type: ignore[assignment]
