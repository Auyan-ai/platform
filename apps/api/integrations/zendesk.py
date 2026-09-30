"""Adapter HTTP para Zendesk.

Dos capas:
- `ZendeskClient`: cliente HTTP con estado (subdomain + token en __init__).
- `ZendeskAdapter`: adapter stateless registrado en IntegrationRegistry. Recibe
  IntegrationContext por llamada — habilita multi-tenant real (un adapter, N accounts).

Credentials esperadas en IntegrationContext (uno de los tres modos de auth):
    Client credentials (managed): {"client_id": "...", "client_secret": "..."}  # Bearer (auto)
    OAuth2 (authorization_code):  {"oauth_token": "..."}                        # Bearer
    API token (legacy):           {"email": "...", "api_token": "..."}          # Basic
    {
        "webhook_signing_secret": "..."   # opcional — valida X-Zendesk-Webhook-Signature
    }

Client credentials es el modo preferido para el modelo managed. Zendesk retira los
API tokens: las cuentas creadas desde el 2026-07-28 no pueden crearlos, desde el
2026-10-27 nadie puede crear nuevos y el 2027-04-30 dejan de funcionar todos. El
token de client_credentials caduca (30 min por defecto) y no trae refresh token:
se pide otro con las mismas credenciales. Se cachea en proceso por
(subdomain, client_id) y se invalida ante un 401. Las acciones quedan atribuidas
al usuario de Zendesk que creó el OAuth client.

Config esperada en IntegrationContext:
    {
        "subdomain":           "mycompany",  # {subdomain}.zendesk.com
        "escalation_group_id": "123"         # opcional — grupo al que asignar escalaciones
    }

Payload del webhook: ver `routers/webhooks_zendesk.py`. Solo IDs; el contenido,
el autor y el requester se leen de la API con `fetch_inbound_comment`.

Verificación de firma HMAC:
    - Header X-Zendesk-Webhook-Signature (base64-HMAC-SHA256)
    - Header X-Zendesk-Webhook-Signature-Timestamp (Unix timestamp string)
    - Mensaje firmado: timestamp_bytes + raw_body_bytes  (concatenación directa)
    - Si webhook_signing_secret no está en credentials, se acepta sin firma.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from apps.api.integrations.base import (
    ExternalTicketRef,
    HelpdeskProvider,
    InboundMessage,
    IntegrationContext,
)
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.services.inbound_text import clean_inbound_text

logger = logging.getLogger(__name__)


# ─── Token OAuth client_credentials (cache en proceso) ─────────────────────────

# Scopes mínimos: comentar/actualizar tickets + `users/me` para validar al registrar.
ZENDESK_OAUTH_SCOPES = "tickets:read tickets:write users:read"
# Se renueva el token este margen antes de su expiración real.
_TOKEN_REFRESH_MARGIN_S = 60
_DEFAULT_TOKEN_TTL_S = 1800


@dataclass(frozen=True)
class _CachedToken:
    access_token: str
    expires_at: float  # time.monotonic()


_token_cache: dict[tuple[str, str], _CachedToken] = {}
_token_locks: dict[tuple[str, str], asyncio.Lock] = {}


def clear_client_credentials_cache() -> None:
    """Vacía la cache de tokens (tests y rotación de credenciales)."""
    _token_cache.clear()
    _token_locks.clear()


async def fetch_client_credentials_token(
    subdomain: str,
    client_id: str,
    client_secret: str,
    *,
    scope: str = ZENDESK_OAUTH_SCOPES,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, int]:
    """Pide un access token con el grant client_credentials.

    Devuelve (access_token, expires_in en segundos). Lanza httpx.HTTPStatusError
    si Zendesk rechaza las credenciales o el scope.
    """
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post(
            f"https://{subdomain}.zendesk.com/oauth/tokens",
            json={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
            },
            timeout=10,
        )
    response.raise_for_status()
    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise ValueError("zendesk_oauth_token_response_without_access_token")
    return str(access_token), int(payload.get("expires_in") or _DEFAULT_TOKEN_TTL_S)


# ─── Cliente HTTP con estado ───────────────────────────────────────────────────


class ZendeskClient:
    def __init__(
        self,
        subdomain: str,
        *,
        oauth_token: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Acepta tres modos de auth: client credentials (client_id + client_secret
        → Bearer renovado solo), OAuth2 (oauth_token → Bearer) o API token legacy
        (email + api_token → Basic, username `{email}/token`).
        """
        if (client_id is None) != (client_secret is None):
            raise ValueError("ZendeskClient requiere client_id y client_secret juntos")
        if client_id is None and oauth_token is None and not (email and api_token):
            raise ValueError(
                "ZendeskClient requiere client_id+client_secret, oauth_token (OAuth2) "
                "o email+api_token (API token)"
            )
        self._subdomain = subdomain
        self._oauth_token = oauth_token
        self._email = email
        self._api_token = api_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport

    @property
    def base_url(self) -> str:
        return f"https://{self._subdomain}.zendesk.com/api/v2"

    @property
    def _uses_client_credentials(self) -> bool:
        return self._client_id is not None

    async def _client_credentials_token(self) -> str:
        assert self._client_id is not None and self._client_secret is not None
        key = (self._subdomain, self._client_id)
        lock = _token_locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = _token_cache.get(key)
            if cached is not None and cached.expires_at > time.monotonic():
                return cached.access_token
            access_token, expires_in = await fetch_client_credentials_token(
                self._subdomain,
                self._client_id,
                self._client_secret,
                transport=self._transport,
            )
            _token_cache[key] = _CachedToken(
                access_token=access_token,
                expires_at=time.monotonic() + expires_in - _TOKEN_REFRESH_MARGIN_S,
            )
            return access_token

    def _invalidate_token(self) -> None:
        if self._client_id is not None:
            _token_cache.pop((self._subdomain, self._client_id), None)

    async def _headers(self) -> dict[str, str]:
        if self._uses_client_credentials:
            authorization = f"Bearer {await self._client_credentials_token()}"
        elif self._oauth_token is not None:
            authorization = f"Bearer {self._oauth_token}"
        else:
            raw = f"{self._email}/token:{self._api_token}".encode()
            authorization = f"Basic {base64.b64encode(raw).decode()}"
        return {
            "Authorization": authorization,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Request a la API v2. Con client credentials, un 401 invalida el token
        cacheado (revocado o rotado) y reintenta una sola vez con uno nuevo."""
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.request(
                method,
                url,
                headers=await self._headers(),
                json=json_body,
                params=params,
                timeout=10,
            )
            if response.status_code == 401 and self._uses_client_credentials:
                logger.warning(
                    "zendesk_token_rejected_retrying",
                    extra={"subdomain": self._subdomain},
                )
                self._invalidate_token()
                response = await client.request(
                    method,
                    url,
                    headers=await self._headers(),
                    json=json_body,
                    params=params,
                    timeout=10,
                )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def _put_ticket(self, ticket_id: str, ticket: dict[str, Any]) -> dict[str, Any]:
        data = await self._request(
            "PUT", f"/tickets/{ticket_id}.json", json_body={"ticket": ticket}
        )
        return data["ticket"]  # type: ignore[no-any-return]

    async def get_ticket_with_users(self, ticket_id: str) -> dict[str, Any]:
        """Ticket + usuarios relacionados (requester, etc.) en una llamada."""
        return await self._request("GET", f"/tickets/{ticket_id}.json", params={"include": "users"})

    async def list_comments_desc(self, ticket_id: str) -> list[dict[str, Any]]:
        """Comentarios del ticket, el más reciente primero (primera página)."""
        data = await self._request(
            "GET",
            f"/tickets/{ticket_id}/comments.json",
            params={"sort_order": "desc", "per_page": 100},
        )
        return list(data.get("comments") or [])

    # ── Comentarios / respuestas ──────────────────────────────────────────────

    async def add_comment(self, ticket_id: str, body: str, public: bool = True) -> dict[str, Any]:
        """Agrega un comentario público o privado (nota interna) al ticket."""
        return await self._put_ticket(ticket_id, {"comment": {"body": body, "public": public}})

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

        return await self._put_ticket(ticket_id, ticket_update)


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


# ─── Comentario inbound leído de la API ────────────────────────────────────────


@dataclass(frozen=True)
class ZendeskInboundComment:
    """Comentario que disparó el webhook, con datos autoritativos de la API."""

    ticket_id: str
    comment_id: str
    author_id: str
    public: bool
    content: str
    requester_id: str
    requester_email: str | None
    requester_name: str | None
    subject: str | None

    @property
    def from_requester(self) -> bool:
        return self.author_id == self.requester_id


def select_inbound_comment(
    comments_desc: list[dict[str, Any]], comment_id: str | None
) -> dict[str, Any] | None:
    """El comentario indicado por el Trigger; si no viene (o no se encuentra), el
    público más reciente."""
    if comment_id is not None:
        for comment in comments_desc:
            if str(comment.get("id")) == comment_id:
                return comment
        logger.warning("zendesk_comment_id_not_found", extra={"comment_id": comment_id})
    for comment in comments_desc:
        if comment.get("public"):
            return comment
    return None


# ─── Adapter stateless — implementa HelpdeskProvider ──────────────────────────


@IntegrationRegistry.register(kind="helpdesk", provider="zendesk")
class ZendeskAdapter:
    """HelpdeskProvider stateless para Zendesk.

    Crea un ZendeskClient por llamada a partir de las credenciales en IntegrationContext.
    """

    def _client(self, ctx: IntegrationContext) -> ZendeskClient:
        creds = ctx.credentials
        return ZendeskClient(
            subdomain=ctx.config["subdomain"],
            oauth_token=creds.get("oauth_token"),
            email=creds.get("email"),
            api_token=creds.get("api_token"),
            client_id=creds.get("client_id"),
            client_secret=creds.get("client_secret"),
        )

    async def fetch_inbound_comment(
        self, ctx: IntegrationContext, ticket_id: str, comment_id: str | None
    ) -> ZendeskInboundComment | None:
        """Lee de la API el comentario que disparó el webhook + su requester.

        El payload del Trigger solo trae IDs: el texto libre rompe el JSON del
        webhook (Zendesk no escapa los placeholders) y la API es la fuente de
        verdad para el autor (anti-loop). None si el ticket no tiene comentarios.
        """
        client = self._client(ctx)
        ticket_data = await client.get_ticket_with_users(ticket_id)
        comment = select_inbound_comment(await client.list_comments_desc(ticket_id), comment_id)
        if comment is None:
            return None

        ticket = ticket_data.get("ticket") or {}
        requester_id = str(ticket.get("requester_id", ""))
        requester = next(
            (u for u in ticket_data.get("users") or [] if str(u.get("id")) == requester_id),
            {},
        )
        return ZendeskInboundComment(
            ticket_id=ticket_id,
            comment_id=str(comment.get("id", "")),
            author_id=str(comment.get("author_id", "")),
            public=bool(comment.get("public")),
            content=clean_inbound_text(
                str(comment.get("body") or comment.get("plain_body") or ""),
                sender_name=requester.get("name"),
            ),
            requester_id=requester_id,
            requester_email=requester.get("email"),
            requester_name=requester.get("name"),
            subject=ticket.get("subject") or None,
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
        idempotency_key: str | None = None,  # sin uso: los helpdesks no lo soportan
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
            await self._client(ctx).update_ticket(ticket_ref, group_id=int(group_id_str))

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
