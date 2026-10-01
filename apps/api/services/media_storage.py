"""Adjuntos de los compradores en Supabase Storage (bucket privado `conversation-media`).

Solo la service role accede (Storage REST API). Ruta determinista y con el tenant al
principio: `{tenant_id}/{conversation_id}/{message_id}/{idx}.{ext}`.
"""

from __future__ import annotations

import logging
import mimetypes
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx
from apps.api.core.config import get_settings
from apps.api.core.errors import ExternalIntegrationError
from apps.api.integrations.base import StoredAttachment

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

MEDIA_BUCKET = "conversation-media"
MAX_ATTACHMENT_BYTES = 16 * 1024 * 1024
# Vida de las URLs firmadas para ver un adjunto en el dashboard: el bucket sigue privado.
SIGNED_URL_SECONDS = 300
_EXTENSIONS = {
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "application/pdf": "pdf",
}

# Transport inyectable para tests (sin red).
_transport: httpx.AsyncBaseTransport | None = None


def extension_for(mime_type: str) -> str:
    mime = (mime_type or "").split(";")[0].strip().lower()
    if mime in _EXTENSIONS:
        return _EXTENSIONS[mime]
    guessed = mimetypes.guess_extension(mime) if mime else None
    return guessed.lstrip(".") if guessed else "bin"


def attachment_path(
    tenant_id: UUID, conversation_id: UUID, message_id: UUID, idx: int, mime_type: str
) -> str:
    return f"{tenant_id}/{conversation_id}/{message_id}/{idx}.{extension_for(mime_type)}"


def _storage_base() -> tuple[str, dict[str, str]]:
    settings = get_settings()
    key = settings.supabase_service_role_key.get_secret_value()
    base = str(settings.supabase_url).rstrip("/")
    return f"{base}/storage/v1/object", {"Authorization": f"Bearer {key}", "apikey": key}


async def store_attachment(
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    idx: int,
    content: bytes,
    mime_type: str,
    kind: str,
) -> StoredAttachment:
    """Sube el adjunto al bucket privado. Lanza ExternalIntegrationError si falla."""
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ExternalIntegrationError("attachment exceeds 16 MB", code="media_too_large")
    path = attachment_path(tenant_id, conversation_id, message_id, idx, mime_type)
    base, headers = _storage_base()
    headers = {
        **headers,
        "Content-Type": mime_type or "application/octet-stream",
        "x-upsert": "true",
    }
    try:
        async with httpx.AsyncClient(transport=_transport) as client:
            response = await client.post(
                f"{base}/{MEDIA_BUCKET}/{quote(path)}", content=content, headers=headers, timeout=30
            )
    except httpx.HTTPError as exc:
        raise ExternalIntegrationError(
            f"storage upload transport error: {type(exc).__name__}", code="storage_transport"
        ) from exc
    if not response.is_success:
        logger.error(
            "media_storage_upload_failed",
            extra={"tenant_id": str(tenant_id), "status": response.status_code},
        )
        raise ExternalIntegrationError(
            f"storage upload failed: HTTP {response.status_code}", code="storage_upload_failed"
        )
    return StoredAttachment(
        path=path,
        mime_type=mime_type,
        size=len(content),
        filename=path.rsplit("/", 1)[-1],
        kind=kind,
    )


async def download_attachment(path: str) -> bytes:
    """Descarga un adjunto del bucket privado (para subirlo al ticket del handoff)."""
    base, headers = _storage_base()
    try:
        async with httpx.AsyncClient(transport=_transport) as client:
            response = await client.get(
                f"{base}/authenticated/{MEDIA_BUCKET}/{quote(path)}", headers=headers, timeout=30
            )
    except httpx.HTTPError as exc:
        raise ExternalIntegrationError(
            f"storage download transport error: {type(exc).__name__}", code="storage_transport"
        ) from exc
    if not response.is_success:
        raise ExternalIntegrationError(
            f"storage download failed: HTTP {response.status_code}",
            code="storage_download_failed",
        )
    return response.content


async def create_signed_url(path: str, expires_in: int = SIGNED_URL_SECONDS) -> str:
    """URL firmada de vida corta para ver un adjunto del bucket privado.

    Contrato verificado contra Supabase (s81): `POST /storage/v1/object/sign/{bucket}/{path}`
    con `{"expiresIn"}` → `{"signedURL": "/object/sign/…?token=…"}`, relativa a `/storage/v1`.
    """
    base, headers = _storage_base()
    try:
        async with httpx.AsyncClient(transport=_transport) as client:
            response = await client.post(
                f"{base}/sign/{MEDIA_BUCKET}/{quote(path)}",
                json={"expiresIn": expires_in},
                headers=headers,
                timeout=15,
            )
    except httpx.HTTPError as exc:
        raise ExternalIntegrationError(
            f"storage sign transport error: {type(exc).__name__}", code="storage_transport"
        ) from exc
    signed = response.json().get("signedURL") if response.is_success else None
    if not signed:
        logger.error("media_storage_sign_failed", extra={"status": response.status_code})
        raise ExternalIntegrationError(
            f"storage sign failed: HTTP {response.status_code}", code="storage_sign_failed"
        )
    return f"{base.removesuffix('/object')}{signed}"
