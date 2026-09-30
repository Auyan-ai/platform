"""Transcripción de notas de voz (Sprint 2, PR-7). Ver ADR 0011."""

from apps.api.integrations.transcription.base import (
    Transcriber,
    Transcript,
    TranscriptionError,
    get_transcriber,
    ogg_duration_seconds,
)

__all__ = [
    "Transcriber",
    "Transcript",
    "TranscriptionError",
    "get_transcriber",
    "ogg_duration_seconds",
]
