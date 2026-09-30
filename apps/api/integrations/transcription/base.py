"""Interfaz `Transcriber` + utilidades deterministas (duración de OGG/Opus).

Criterio eliminatorio (plan del Sprint 2): la transcripción tiene que ser LITERAL. Un
número de pedido o un email reescrito es un error de integración. El proveedor sale del
mini-benchmark de C0 (`scripts/benchmark_stt.py`) → ADR 0011.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from apps.api.core.config import Settings


class TranscriptionError(RuntimeError):
    """El proveedor no pudo transcribir el audio."""


@dataclass(frozen=True)
class Transcript:
    text: str
    duration_s: float | None
    provider: str
    model: str
    cost_usd: float


class Transcriber(Protocol):
    provider: str
    model: str

    async def transcribe(
        self, audio: bytes, mime_type: str, language: str = "es"
    ) -> Transcript: ...


def ogg_duration_seconds(data: bytes) -> float | None:
    """Duración de un OGG/Opus leyendo el granule position de la última página.

    Opus en OGG usa reloj de 48 kHz y un `pre-skip` en la cabecera OpusHead. None si no
    es un OGG válido (el llamador aplica entonces solo el límite de tamaño).
    """
    if not data.startswith(b"OggS"):
        return None
    last = data.rfind(b"OggS")
    if last < 0 or last + 14 > len(data):
        return None
    granule = struct.unpack_from("<q", data, last + 6)[0]
    if granule <= 0:
        return None
    pre_skip = 0
    head = data.find(b"OpusHead")
    if head >= 0 and head + 12 <= len(data):
        pre_skip = struct.unpack_from("<H", data, head + 10)[0]
        return max(granule - pre_skip, 0) / 48000.0
    # Vorbis: la tasa de muestreo está en la cabecera de identificación.
    vorbis = data.find(b"\x01vorbis")
    if vorbis >= 0 and vorbis + 16 <= len(data):
        rate = struct.unpack_from("<I", data, vorbis + 12)[0]
        return granule / rate if rate else None
    return None


def get_transcriber(settings: Settings) -> Transcriber | None:
    """El transcriptor configurado, o None (sin proveedor no se transcribe)."""
    provider = (getattr(settings, "transcription_provider", None) or "").strip().lower()
    if not provider:
        return None
    if provider == "openai":
        from apps.api.integrations.transcription.openai_transcriber import OpenAITranscriber

        return OpenAITranscriber(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.transcription_model,
            cost_per_minute_usd=settings.transcription_cost_per_minute_usd,
        )
    raise ValueError(f"unknown_transcription_provider: {provider}")
