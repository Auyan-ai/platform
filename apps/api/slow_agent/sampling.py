"""Estrategia de sampling para el slow agent.

Reglas (Sprint 11 — fase skeleton):
- Siempre juzgar conversaciones escaladas.
- Sample ~10% de resueltas/cerradas: determinístico por (conv_id, fecha),
  para que el mismo batch semanal no re-juzgue las mismas si se corre dos veces.
- Nunca re-juzgar conversaciones ya juzgadas en los últimos N días.
- Caps configurables: max_conversations y sample_rate.
"""

from __future__ import annotations

import hashlib
from datetime import date
from uuid import UUID

from apps.api.db.models import Conversation

# 25/256 ≈ 9.8% → ~10% sample
_DEFAULT_SAMPLE_THRESHOLD = 25
_DEFAULT_MAX_CONVERSATIONS = 50
_DEFAULT_SINCE_DAYS = 7


def _hash_sample(conv_id: UUID, sample_date: date) -> int:
    """Byte 0 del SHA-256 de (conv_id, fecha) — determinístico."""
    key = f"{conv_id}:{sample_date.isoformat()}".encode()
    return hashlib.sha256(key).digest()[0]


def should_judge(
    conv: Conversation,
    already_judged: set[UUID],
    sample_threshold: int = _DEFAULT_SAMPLE_THRESHOLD,
    reference_date: date | None = None,
) -> bool:
    """Retorna True si esta conversación debe pasar por el judge."""
    if conv.id in already_judged:
        return False

    if conv.status == "escalated":
        return True

    if conv.status in ("resolved", "closed", "closed_abandoned"):
        d = reference_date or date.today()
        return _hash_sample(conv.id, d) < sample_threshold

    return False


def filter_candidates(
    conversations: list[Conversation],
    already_judged: set[UUID],
    max_conversations: int = _DEFAULT_MAX_CONVERSATIONS,
    sample_threshold: int = _DEFAULT_SAMPLE_THRESHOLD,
    reference_date: date | None = None,
) -> list[Conversation]:
    """Filtra y acota la lista de conversaciones candidatas."""
    candidates = [
        c for c in conversations
        if should_judge(c, already_judged, sample_threshold, reference_date)
    ]
    # Escaladas primero, luego resueltas
    candidates.sort(key=lambda c: (0 if c.status == "escalated" else 1, c.created_at or date.min))
    return candidates[:max_conversations]
