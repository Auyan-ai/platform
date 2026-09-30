"""Adapter de Zernio (WhatsApp) — canal de mensajería, no helpdesk (ADR 0010).

Dos capas, como Zendesk:
- `ZernioClient`: cliente HTTP con estado (API key del profile del tenant).
- `ZernioAdapter`: adapter stateless registrado como `("channel", "zernio")`.

Una cuenta de Zernio de Auyan, un **profile por tenant** y una API key **limitada a ese
profile** (nunca la key maestra en el runtime). Credenciales y config en
`tenant_integrations(kind='channel', provider='zernio')`:

    credentials = {"api_key": "...", "webhook_secret": "..."}
    config      = {"profile_id": "...", "account_id": "...", "webhook_id": "...",
                   "phone_number": "+34...", "reengagement_template": {"name", "language"}}

Webhook (`routers/webhooks_zernio.py`): `X-Zernio-Signature` es el HMAC-SHA256 en hex
(minúsculas) del body crudo con el secreto del webhook (documentación oficial de Zernio;
`X-Late-Signature` es el alias legacy con el mismo valor). El id del evento (`payload.id`
y `X-Zernio-Event-Id`) es estable entre reintentos: es la key de idempotencia.

Payload en camelCase. Identidad de WhatsApp: `sender.businessScopedUserId` (BSUID) es el
ancla recomendada; `sender.phoneNumber` (E.164) **puede faltar** desde abril de 2026.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from apps.api.core.errors import ExternalIntegrationError
from apps.api.integrations.base import InboundMessage, IntegrationContext, MessageProvider
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.services.identity import normalize_phone

logger = logging.getLogger(__name__)

ZERNIO_API_BASE_URL = "https://zernio.com/api/v1"
ZERNIO_TIMEOUT_S = 10.0
# WhatsApp admite 4 096 caracteres por texto; cortamos antes para dejar margen.
WHATSAPP_MAX_CHARS = 4000
# Límite de WhatsApp para media entrante.
MAX_MEDIA_BYTES = 16 * 1024 * 1024
BSUID_PREFIX = "wa:bsuid:"


# ─── Firma del webhook ────────────────────────────────────────────────────────


def verify_zernio_signature(raw_body: bytes, secret: str, header: str | None) -> bool:
    """HMAC-SHA256 hex del body crudo, comparado en tiempo constante.

    False si falta el secreto o la cabecera. Acepta el prefijo `sha256=` por robustez.
    """
    if not secret or not header:
        return False
    received = header.strip().lower()
    if received.startswith("sha256="):
        received = received[len("sha256=") :]
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)


def sign_zernio_body(raw_body: bytes, secret: str) -> str:
    """Firma que Zernio pondría en `X-Zernio-Signature` (tests y harness E2E)."""
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


# ─── Eventos tipados ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ZernioSender:
    id: str | None
    name: str | None
    phone_e164: str | None
    bsuid: str | None
    username: str | None

    @property
    def customer_external_id(self) -> str | None:
        """external_id del end_customer: el BSUID con prefijo, o None si no llega."""
        return f"{BSUID_PREFIX}{self.bsuid}" if self.bsuid else None


@dataclass(frozen=True)
class ZernioAttachment:
    type: str
    url: str | None
    mime_type: str | None

    def as_metadata(self) -> dict[str, Any]:
        return {"type": self.type, "url": self.url, "mime_type": self.mime_type}


@dataclass(frozen=True)
class ZernioMessage:
    id: str | None
    conversation_id: str | None
    platform: str | None
    platform_message_id: str | None
    direction: str | None
    text: str
    attachments: tuple[ZernioAttachment, ...]
    sender: ZernioSender
    sent_at: datetime | None
    source: str | None
    sent_via: str | None


@dataclass(frozen=True)
class ZernioEvent:
    event_id: str | None
    event: str
    account_id: str | None
    profile_id: str | None
    conversation_id: str | None
    message: ZernioMessage | None
    standby: bool
    error: dict[str, Any] | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(value: Any) -> datetime | None:
    text = _str_or_none(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("zernio_invalid_datetime", extra={"value_len": len(text)})
        return None


def _parse_sender(raw: Any) -> ZernioSender:
    data = raw if isinstance(raw, dict) else {}
    return ZernioSender(
        id=_str_or_none(data.get("id")),
        name=_str_or_none(data.get("name")),
        phone_e164=normalize_phone(_str_or_none(data.get("phoneNumber"))),
        bsuid=_str_or_none(data.get("businessScopedUserId")),
        username=_str_or_none(data.get("whatsappUsername") or data.get("username")),
    )


def _parse_message(raw: Any) -> ZernioMessage | None:
    if not isinstance(raw, dict):
        return None
    attachments = tuple(
        ZernioAttachment(
            type=str(a.get("type") or "file"),
            url=_str_or_none(a.get("url")),
            mime_type=_str_or_none(a.get("mimeType")),
        )
        for a in raw.get("attachments") or []
        if isinstance(a, dict)
    )
    return ZernioMessage(
        id=_str_or_none(raw.get("id")),
        conversation_id=_str_or_none(raw.get("conversationId")),
        platform=_str_or_none(raw.get("platform")),
        platform_message_id=_str_or_none(raw.get("platformMessageId")),
        direction=_str_or_none(raw.get("direction")),
        text=str(raw.get("text") or ""),
        attachments=attachments,
        sender=_parse_sender(raw.get("sender")),
        sent_at=_parse_datetime(raw.get("sentAt")),
        source=_str_or_none(raw.get("source")),
        sent_via=_str_or_none(raw.get("sentVia")),
    )


def parse_zernio_event(payload: dict[str, Any]) -> ZernioEvent:
    """Normaliza un webhook de Zernio. Tolera campos ausentes (nunca lanza por forma)."""
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    conversation = (
        payload.get("conversation") if isinstance(payload.get("conversation"), dict) else {}
    )
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    message = _parse_message(payload.get("message"))
    error = payload.get("error") if isinstance(payload.get("error"), dict) else None
    return ZernioEvent(
        event_id=_str_or_none(payload.get("id")),
        event=str(payload.get("event") or ""),
        account_id=_str_or_none(account.get("accountId") or account.get("id")),
        profile_id=_str_or_none(account.get("profileId")),
        conversation_id=_str_or_none(conversation.get("id"))
        or (message.conversation_id if message else None),
        message=message,
        standby=bool(metadata.get("standby")),
        error=error,
        raw=payload,
    )


# ─── Cliente HTTP ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ZernioSendResult:
    """Resultado de un envío: `message_id` es el wamid (= `platformMessageId` en webhooks)."""

    message_id: str | None
    conversation_id: str | None


class ZernioClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = ZERNIO_API_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("ZernioClient requiere api_key")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _raise_for_status(self, response: httpx.Response, *, op: str) -> None:
        request_id = response.headers.get("X-Request-Id")
        if response.is_success:
            logger.info(
                "zernio_request_ok",
                extra={"op": op, "status": response.status_code, "request_id": request_id},
            )
            return
        code = "unknown"
        try:
            body = response.json()
            if isinstance(body, dict):
                code = str(body.get("code") or body.get("error") or "unknown")
        except ValueError:
            pass
        logger.error(
            "zernio_request_failed",
            extra={
                "op": op,
                "status": response.status_code,
                "zernio_code": code,
                "request_id": request_id,
            },
        )
        raise ExternalIntegrationError(
            f"zernio {op} failed: HTTP {response.status_code} ({code})",
            code=f"zernio_{code}",
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        op: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=self._headers(idempotency_key),
                    json=json_body,
                    params=params,
                    timeout=ZERNIO_TIMEOUT_S,
                )
        except httpx.HTTPError as exc:
            logger.error("zernio_request_transport_error", extra={"op": op}, exc_info=True)
            raise ExternalIntegrationError(
                f"zernio {op} transport error: {type(exc).__name__}", code="zernio_transport"
            ) from exc
        self._raise_for_status(response, op=op)
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _send_result(data: dict[str, Any]) -> ZernioSendResult:
        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        return ZernioSendResult(
            message_id=_str_or_none(inner.get("messageId")),
            conversation_id=_str_or_none(inner.get("conversationId")),
        )

    async def send_text(
        self,
        conversation_id: str,
        account_id: str,
        text: str,
        idempotency_key: str | None = None,
    ) -> ZernioSendResult:
        data = await self._request(
            "POST",
            f"/inbox/conversations/{conversation_id}/messages",
            op="send_text",
            json_body={"accountId": account_id, "message": text},
            idempotency_key=idempotency_key,
        )
        return self._send_result(data)

    async def send_template(
        self,
        conversation_id: str,
        account_id: str,
        name: str,
        language: str,
        components: list[dict[str, Any]],
        idempotency_key: str | None = None,
    ) -> ZernioSendResult:
        data = await self._request(
            "POST",
            f"/inbox/conversations/{conversation_id}/messages",
            op="send_template",
            json_body={
                "accountId": account_id,
                "template": {
                    "elements": [{"name": name, "language": language, "components": components}]
                },
            },
            idempotency_key=idempotency_key,
        )
        return self._send_result(data)

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/inbox/conversations/{conversation_id}", op="get_conversation"
        )

    def _is_zernio_url(self, url: str) -> bool:
        base = urlparse(self._base_url)
        target = urlparse(url)
        return target.scheme == "https" and target.netloc == base.netloc

    async def download_media(self, url: str) -> tuple[bytes, str]:
        """Descarga un adjunto de WhatsApp (`GET /v1/whatsapp/media/{id}`, con Bearer).

        Solo acepta URLs del propio Zernio: nunca se manda la API key a otro host.
        Lanza ExternalIntegrationError si falla o supera `MAX_MEDIA_BYTES`.
        """
        if not self._is_zernio_url(url):
            raise ExternalIntegrationError(
                "zernio media url outside the Zernio API host", code="zernio_media_foreign_url"
            )
        try:
            async with (
                httpx.AsyncClient(transport=self._transport) as client,
                client.stream(
                    "GET",
                    url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=30.0,
                ) as response,
            ):
                if not response.is_success:
                    await response.aread()
                    self._raise_for_status(response, op="download_media")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_MEDIA_BYTES:
                        raise ExternalIntegrationError(
                            "zernio media exceeds size limit", code="zernio_media_too_large"
                        )
                    chunks.append(chunk)
                mime = response.headers.get("Content-Type", "application/octet-stream")
        except httpx.HTTPError as exc:
            logger.error("zernio_media_transport_error", exc_info=True)
            raise ExternalIntegrationError(
                f"zernio media transport error: {type(exc).__name__}", code="zernio_transport"
            ) from exc
        return b"".join(chunks), mime.split(";")[0].strip()


# ─── Cortes de texto ──────────────────────────────────────────────────────────


def split_for_whatsapp(text: str, limit: int = WHATSAPP_MAX_CHARS) -> list[str]:
    """Parte en trozos de ≤`limit` por párrafos (luego por líneas y, en último caso, duro)."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for block in _split_units(text, limit):
        sep = "\n\n" if current else ""
        if len(current) + len(sep) + len(block) <= limit:
            current = f"{current}{sep}{block}"
        else:
            if current:
                chunks.append(current)
            current = block
    if current:
        chunks.append(current)
    return chunks


def _split_units(text: str, limit: int) -> list[str]:
    units: list[str] = []
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= limit:
            units.append(paragraph)
            continue
        for line in paragraph.split("\n"):
            while len(line) > limit:
                units.append(line[:limit])
                line = line[limit:]
            if line.strip():
                units.append(line)
    return units


# ─── Adapter stateless ────────────────────────────────────────────────────────


@IntegrationRegistry.register(kind="channel", provider="zernio")
class ZernioAdapter:
    """MessageProvider de WhatsApp vía Zernio. `conversation_ref` es el id de conversación
    de Zernio (el `external_id` de la conversación de Auyan)."""

    transport: httpx.AsyncBaseTransport | None = None

    def client(self, ctx: IntegrationContext) -> ZernioClient:
        return ZernioClient(str(ctx.credentials.get("api_key") or ""), transport=self.transport)

    @staticmethod
    def account_id(ctx: IntegrationContext) -> str:
        account_id = ctx.config.get("account_id")
        if not account_id:
            raise ExternalIntegrationError(
                "zernio integration without account_id", code="zernio_missing_account_id"
            )
        return str(account_id)

    async def parse_inbound_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        event = parse_zernio_event(payload)
        message = event.message
        return InboundMessage(
            external_id=event.conversation_id or "",
            channel="whatsapp",
            content=message.text if message else "",
            sender_name=message.sender.name if message else None,
            attachments=[a.as_metadata() for a in message.attachments] if message else [],
            raw_payload=payload,
        )

    async def send_outbound(
        self,
        ctx: IntegrationContext,
        conversation_ref: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
    ) -> list[ZernioSendResult]:
        """Envía `content` con formato de WhatsApp, en uno o varios textos (≤4 000 c/u).

        `idempotency_key` (id del mensaje persistido) → `Idempotency-Key: {key}:{n}` por
        trozo: un reintento nunca duplica el mensaje en el móvil del comprador.
        """
        # Import local: zernio_format depende de este módulo (cortes y límites).
        from apps.api.integrations.zernio_format import to_whatsapp_messages

        client = self.client(ctx)
        account_id = self.account_id(ctx)
        results: list[ZernioSendResult] = []
        for n, chunk in enumerate(to_whatsapp_messages(content)):
            key = f"{idempotency_key}:{n}" if idempotency_key else None
            results.append(await client.send_text(conversation_ref, account_id, chunk, key))
        return results

    async def send_reengagement_template(
        self,
        ctx: IntegrationContext,
        conversation_ref: str,
        *,
        first_name: str,
        idempotency_key: str | None = None,
    ) -> ZernioSendResult:
        """Plantilla de re-enganche del tenant (`config.reengagement_template`), `{{1}}` =
        nombre. Lanza ExternalIntegrationError si el tenant no la tiene configurada."""
        template = ctx.config.get("reengagement_template") or {}
        name, language = template.get("name"), template.get("language")
        if not name or not language:
            raise ExternalIntegrationError(
                "tenant without reengagement template", code="zernio_no_reengagement_template"
            )
        components = [{"type": "body", "parameters": [{"type": "text", "text": first_name}]}]
        return await self.client(ctx).send_template(
            conversation_ref,
            self.account_id(ctx),
            str(name),
            str(language),
            components,
            idempotency_key=idempotency_key,
        )


_: MessageProvider = ZernioAdapter()  # type: ignore[assignment]
