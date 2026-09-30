"""Adjuntos del comprador en WhatsApp: descarga, Storage, transcripción y mensajes fijos.

Pre-paso del worker en canales de mensajería (antes de pendientes y handoff). Por cada
mensaje del turno con adjuntos de Zernio:

1. `ZernioClient.download_media` → `store_attachment` (bucket privado) → `messages.attachments`.
   Hay que bajarlos al procesar: Meta borra la media entrante.
2. **Audio** → `Transcriber` (máx. `transcription_max_seconds`). El contenido pasa a
   `"[Nota de voz] <transcripción>"`, con `metadata.transcription` y coste al uso del tenant.
3. **Imagen/archivo con texto** → el grafo corre sobre el texto con la marca
   `[adjuntó 1 imagen que no puedes ver; no describas su contenido]` (sin visión).
4. **Sin texto útil** (solo imagen/archivo, sticker, audio no transcrito o demasiado largo,
   descarga fallida) → MENSAJE FIJO del tenant, sin grafo (lo decide el worker).

Determinista (regla dura del Sprint 2). Si algo falla → `logger.error`; nunca se
reintenta el job por esto. Idempotente: un mensaje ya procesado (`metadata.media_processed`)
no se vuelve a descargar ni transcribir.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from apps.api.db.client import tenant_scope
from apps.api.db.inbound_jobs import get_inbound_messages, update_inbound_message_media
from apps.api.integrations.base import StoredAttachment
from apps.api.integrations.transcription import get_transcriber, ogg_duration_seconds
from apps.api.services.channel_routing import load_delivery_client
from apps.api.services.media_storage import store_attachment

if TYPE_CHECKING:
    from uuid import UUID

    from apps.api.core.config import Settings
    from apps.api.db.inbound_jobs import ClaimedInboundJob
    from apps.api.db.models import Conversation, Message
    from apps.api.integrations.transcription import Transcriber

logger = logging.getLogger(__name__)

FallbackKind = str  # audio_too_long | audio_unavailable | download_failed | media_without_text
#                     | unsupported
FALLBACK_PRIORITY = (
    "audio_too_long",
    "audio_unavailable",
    "download_failed",
    "media_without_text",
    "unsupported",
)
DEFAULT_FALLBACK_MESSAGES: dict[str, str] = {
    "media_without_text": (
        "¡Gracias! Hemos recibido tu archivo, pero no podemos verlo. ¿Nos cuentas por "
        "escrito en qué te podemos ayudar?"
    ),
    "audio_unavailable": (
        "No hemos podido escuchar tu nota de voz. ¿Nos escribes tu consulta, por favor?"
    ),
    "audio_too_long": (
        "Tu nota de voz es demasiado larga para procesarla. ¿Nos escribes tu consulta en un "
        "mensaje, por favor?"
    ),
    "download_failed": (
        "No hemos podido abrir lo que nos enviaste. ¿Puedes escribirnos tu consulta, por favor?"
    ),
    "unsupported": "¿En qué te podemos ayudar? Escríbenos tu consulta, por favor.",
}
_DOWNLOADABLE = frozenset({"image", "audio", "video", "file"})


@dataclass
class MediaOutcome:
    """Resultado del pre-paso para el turno."""

    texts: list[str] = field(default_factory=list)  # contenido útil, en orden
    attachments: list[StoredAttachment] = field(default_factory=list)
    fallback_kind: FallbackKind | None = None  # solo si NINGÚN mensaje tiene texto útil
    transcription_cost_usd: float = 0.0


def fallback_message(kind: FallbackKind, config: dict[str, Any] | None) -> str:
    """Mensaje fijo del tenant (`config.media_fallback_messages`) o el default en español."""
    custom = ((config or {}).get("media_fallback_messages") or {}).get(kind)
    if isinstance(custom, str) and custom.strip():
        return custom.strip()
    return DEFAULT_FALLBACK_MESSAGES.get(kind, DEFAULT_FALLBACK_MESSAGES["unsupported"])


def unseen_media_marker(images: int, files: int) -> str:
    parts = []
    if images:
        parts.append(f"{images} {'imagen' if images == 1 else 'imágenes'}")
    if files:
        parts.append(f"{files} {'archivo' if files == 1 else 'archivos'}")
    what = " y ".join(parts)
    return f"[adjuntó {what} que no puedes ver; no describas su contenido]"


def _attachment_kind(item: dict[str, Any]) -> str:
    kind = str(item.get("type") or "file").lower()
    mime = str(item.get("mime_type") or "").lower()
    if kind == "file" and mime.startswith("audio/"):
        return "audio"
    if kind == "file" and mime.startswith("image/"):
        return "image"
    return kind


def _stored_from_dict(item: dict[str, Any]) -> StoredAttachment:
    return StoredAttachment(
        path=str(item["path"]),
        mime_type=str(item.get("mime_type") or "application/octet-stream"),
        size=int(item.get("size") or 0),
        filename=str(item.get("filename") or str(item["path"]).rsplit("/", 1)[-1]),
        kind=str(item.get("kind") or "file"),
    )


def _stored_to_dict(stored: StoredAttachment) -> dict[str, Any]:
    return {
        "path": stored.path,
        "mime_type": stored.mime_type,
        "size": stored.size,
        "filename": stored.filename,
        "kind": stored.kind,
    }


@dataclass
class _MessageResult:
    content: str
    useful: bool
    attachments: list[StoredAttachment]
    fallback_kind: FallbackKind | None
    metadata_patch: dict[str, Any]
    cost_usd: float = 0.0


async def process_inbound_media(
    *,
    job: ClaimedInboundJob,
    conversation: Conversation,
    settings: Settings,
    observability: Any | None = None,
) -> MediaOutcome:
    """Procesa los adjuntos del turno. Nunca lanza por un adjunto (solo `logger.error`)."""
    message_ids = [*job.absorbed_message_ids, job.inbound_message_id]
    async with tenant_scope(job.tenant_id) as conn:
        messages = await get_inbound_messages(
            conn,
            tenant_id=job.tenant_id,
            conversation_id=job.conversation_id,
            message_ids=message_ids,
        )
        needs_client = any(
            m.metadata.get("zernio_attachments") and not m.metadata.get("media_processed")
            for m in messages
        )
        client = None
        if needs_client:
            try:
                loaded = await load_delivery_client(
                    conn, tenant_id=job.tenant_id, conversation=conversation
                )
                if loaded is not None:
                    adapter, ctx = loaded
                    client = adapter.client(ctx)
            except Exception:
                logger.error(
                    "inbound_media_client_failed",
                    extra={"tenant_id": str(job.tenant_id), "job_id": str(job.id)},
                    exc_info=True,
                )

    transcriber = get_transcriber(settings)
    outcome = MediaOutcome()
    kinds: list[FallbackKind] = []
    for message in messages:
        result = await _process_message(
            message,
            job=job,
            client=client,
            transcriber=transcriber,
            settings=settings,
            observability=observability,
        )
        if result.metadata_patch:
            async with tenant_scope(job.tenant_id) as conn:
                await update_inbound_message_media(
                    conn,
                    tenant_id=job.tenant_id,
                    message_id=message.id,
                    content=result.content,
                    attachments=[_stored_to_dict(a) for a in result.attachments],
                    metadata_patch=result.metadata_patch,
                )
        outcome.attachments.extend(result.attachments)
        outcome.transcription_cost_usd += result.cost_usd
        if result.useful:
            outcome.texts.append(result.content)
        elif result.fallback_kind:
            kinds.append(result.fallback_kind)
    if not outcome.texts:
        outcome.fallback_kind = next(
            (k for k in FALLBACK_PRIORITY if k in kinds), "unsupported" if messages else None
        )
    return outcome


async def _process_message(
    message: Message,
    *,
    job: ClaimedInboundJob,
    client: Any,
    transcriber: Transcriber | None,
    settings: Settings,
    observability: Any | None,
) -> _MessageResult:
    text = message.content.strip()
    raw_items = [i for i in message.metadata.get("zernio_attachments") or [] if isinstance(i, dict)]
    if not raw_items or message.metadata.get("media_processed"):
        # Sin adjuntos, o ya procesado en un intento anterior del job (idempotente).
        stored = [_stored_from_dict(a) for a in message.attachments or [] if a.get("path")]
        prior_kind = message.metadata.get("media_fallback")
        return _MessageResult(
            content=text,
            useful=bool(text),
            attachments=stored,
            fallback_kind=prior_kind if not text else None,
            metadata_patch={},
        )

    stored: list[StoredAttachment] = []
    images = files = 0
    transcripts: list[str] = []
    flags: set[FallbackKind] = set()
    transcription_meta: list[dict[str, Any]] = []
    cost = 0.0
    for idx, item in enumerate(raw_items):
        kind = _attachment_kind(item)
        if kind not in _DOWNLOADABLE:
            flags.add("unsupported")  # sticker, share, reacción…
            continue
        url = item.get("url")
        if client is None or not url:
            flags.add("download_failed")
            continue
        try:
            content, mime = await client.download_media(str(url))
            attachment = await store_attachment(
                tenant_id=job.tenant_id,
                conversation_id=job.conversation_id,
                message_id=message.id,
                idx=idx,
                content=content,
                mime_type=item.get("mime_type") or mime,
                kind=kind,
            )
        except Exception:
            logger.error(
                "inbound_media_download_failed",
                extra={"tenant_id": str(job.tenant_id), "message_id": str(message.id)},
                exc_info=True,
            )
            flags.add("download_failed")
            continue
        stored.append(attachment)
        if kind == "audio":
            transcript, meta, flag = await _transcribe(
                content,
                attachment.mime_type,
                job=job,
                message=message,
                transcriber=transcriber,
                settings=settings,
                observability=observability,
            )
            if transcript:
                transcripts.append(transcript)
                transcription_meta.append(meta)
                cost += float(meta.get("cost_usd") or 0.0)
            if flag:
                flags.add(flag)
        elif kind == "image":
            images += 1
        else:
            files += 1

    parts = [text] if text else []
    parts += [f"[Nota de voz] {t}" for t in transcripts]
    useful = bool(parts)
    if useful and (images or files):
        parts.append(unseen_media_marker(images, files))
    if not useful and (images or files):
        flags.add("media_without_text")
    fallback_kind = None if useful else next((k for k in FALLBACK_PRIORITY if k in flags), None)
    patch: dict[str, Any] = {"media_processed": True}
    if transcription_meta:
        patch["transcription"] = transcription_meta
    if fallback_kind:
        patch["media_fallback"] = fallback_kind
    return _MessageResult(
        content="\n\n".join(parts),
        useful=useful,
        attachments=stored,
        fallback_kind=fallback_kind,
        metadata_patch=patch,
        cost_usd=cost,
    )


async def _transcribe(
    audio: bytes,
    mime_type: str,
    *,
    job: ClaimedInboundJob,
    message: Message,
    transcriber: Transcriber | None,
    settings: Settings,
    observability: Any | None,
) -> tuple[str | None, dict[str, Any], FallbackKind | None]:
    """(texto, metadata, flag). Sin proveedor, audio largo o error → sin texto + flag."""
    if transcriber is None:
        return None, {}, "audio_unavailable"
    duration = ogg_duration_seconds(audio)
    if duration is not None and duration > settings.transcription_max_seconds:
        return None, {}, "audio_too_long"
    started = datetime.now(UTC)
    t0 = time.monotonic()
    error: str | None = None
    try:
        transcript = await transcriber.transcribe(audio, mime_type, language="es")
    except Exception as exc:
        logger.error(
            "inbound_media_transcription_failed",
            extra={"tenant_id": str(job.tenant_id), "message_id": str(message.id)},
            exc_info=True,
        )
        error = type(exc).__name__
        transcript = None
    latency_ms = int((time.monotonic() - t0) * 1000)
    meta: dict[str, Any] = {}
    if transcript is not None:
        meta = {
            "provider": transcript.provider,
            "model": transcript.model,
            "duration_s": transcript.duration_s,
            "cost_usd": transcript.cost_usd,
        }
    _record_transcription_run(
        observability,
        tenant_id=job.tenant_id,
        conversation_id=job.conversation_id,
        message_id=message.id,
        started=started,
        outputs={**meta, "latency_ms": latency_ms},
        error=error,
    )
    if transcript is None or not transcript.text.strip():
        return None, meta, "audio_unavailable"
    return transcript.text.strip(), meta, None


def _record_transcription_run(
    observability: Any | None,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    started: datetime,
    outputs: dict[str, Any],
    error: str | None,
) -> None:
    """Run `transcribe_audio` en LangSmith: proveedor, duración, latencia y coste.

    NUNCA el audio ni el texto (el texto entra como contenido del turno, con sus reglas
    de PII). Best-effort: si falla, se loguea.
    """
    if observability is None or not hasattr(observability, "record_standalone_run"):
        return
    try:
        observability.record_standalone_run(
            name="transcribe_audio",
            run_type="tool",
            metadata={
                "tenant_id": str(tenant_id),
                "conversation_id": str(conversation_id),
                "message_id": str(message_id),
            },
            start_time=started,
            end_time=datetime.now(UTC),
            outputs=outputs,
            error=error,
        )
    except Exception:
        logger.warning("transcription_trace_failed", exc_info=True)
