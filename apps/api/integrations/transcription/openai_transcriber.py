"""Transcriptor OpenAI (`/v1/audio/transcriptions`).

Adapter PROVISIONAL detrás de `Transcriber`, apagado por defecto
(`TRANSCRIPTION_PROVIDER` vacío). El proveedor definitivo lo decide el benchmark de C0
(ADR 0011). OpenAI ya es subprocesador de Auyan (embeddings). `prompt` pide transcripción
literal: sin corregir, resumir ni reformular números de pedido o emails.
"""

from __future__ import annotations

import logging
import time

import httpx
from apps.api.integrations.transcription.base import (
    Transcript,
    TranscriptionError,
    ogg_duration_seconds,
)

logger = logging.getLogger(__name__)

OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
LITERAL_PROMPT = (
    "Transcripción literal de una nota de voz de un cliente de una tienda online. "
    "No corrijas, no resumas ni reformules. Escribe los números de pedido y los emails "
    "tal como se dicen."
)


class OpenAITranscriber:
    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-transcribe",
        cost_per_minute_usd: float = 0.006,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._cost_per_minute = cost_per_minute_usd
        self._transport = transport

    async def transcribe(self, audio: bytes, mime_type: str, language: str = "es") -> Transcript:
        filename = "voice." + ("ogg" if "ogg" in mime_type or "opus" in mime_type else "bin")
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                response = await client.post(
                    OPENAI_TRANSCRIPTIONS_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data={
                        "model": self.model,
                        "language": language,
                        "response_format": "json",
                        "prompt": LITERAL_PROMPT,
                    },
                    files={"file": (filename, audio, mime_type or "application/octet-stream")},
                    timeout=60,
                )
        except httpx.HTTPError as exc:
            raise TranscriptionError(f"openai transport error: {type(exc).__name__}") from exc
        if not response.is_success:
            raise TranscriptionError(f"openai HTTP {response.status_code}")
        text = str((response.json() or {}).get("text") or "").strip()
        duration = ogg_duration_seconds(audio)
        cost = round((duration or 0.0) / 60.0 * self._cost_per_minute, 6)
        logger.info(
            "transcription_done",
            extra={
                "provider": self.provider,
                "model": self.model,
                "latency_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return Transcript(
            text=text,
            duration_s=duration,
            provider=self.provider,
            model=self.model,
            cost_usd=cost,
        )
