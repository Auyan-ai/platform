"""Tests del módulo de sampling."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from apps.api.db.models import Conversation
from apps.api.slow_agent.sampling import (
    filter_candidates,
    should_judge,
)

TENANT = uuid.uuid4()
NOW = datetime(2026, 5, 19, 12, 0, 0)


def _conv(status: str, conv_id: uuid.UUID | None = None) -> Conversation:
    return Conversation(
        id=conv_id or uuid.uuid4(),
        tenant_id=TENANT,
        end_customer_id=uuid.uuid4(),
        channel="chat",
        status=status,  # type: ignore[arg-type]
        created_at=NOW,
    )


# ─── should_judge ─────────────────────────────────────────────────────────────


def test_escalated_always_judged():
    conv = _conv("escalated")
    assert should_judge(conv, set()) is True


def test_already_judged_skipped():
    conv = _conv("escalated")
    assert should_judge(conv, {conv.id}) is False


def test_open_not_judged():
    assert should_judge(_conv("open"), set()) is False


def test_pending_not_judged():
    assert should_judge(_conv("pending"), set()) is False


def test_resolved_sampled_deterministically():
    """El mismo conv_id + fecha siempre da el mismo resultado."""
    conv = _conv("resolved")
    d = date(2026, 5, 19)
    result1 = should_judge(conv, set(), reference_date=d)
    result2 = should_judge(conv, set(), reference_date=d)
    assert result1 == result2


def test_resolved_threshold_0_never_sampled():
    """Con threshold=0, nunca se samplea ningún resolved."""
    for _ in range(20):
        conv = _conv("resolved")
        assert should_judge(conv, set(), sample_threshold=0) is False


def test_resolved_threshold_256_always_sampled():
    """Con threshold=256, siempre se samplea todo resolved."""
    for _ in range(20):
        conv = _conv("resolved")
        assert should_judge(conv, set(), sample_threshold=256) is True


def test_closed_sampled():
    """closed y closed_abandoned también son elegibles."""
    # Con threshold máximo, deben samplearse
    conv_c = _conv("closed")
    conv_ca = _conv("closed_abandoned")
    assert should_judge(conv_c, set(), sample_threshold=256) is True
    assert should_judge(conv_ca, set(), sample_threshold=256) is True


# ─── filter_candidates ────────────────────────────────────────────────────────


def test_filter_caps_at_max():
    convs = [_conv("escalated") for _ in range(100)]
    result = filter_candidates(convs, set(), max_conversations=10)
    assert len(result) == 10


def test_filter_escalated_first():
    resolved = [_conv("resolved") for _ in range(10)]
    escalated = [_conv("escalated") for _ in range(5)]
    result = filter_candidates(
        resolved + escalated, set(), max_conversations=20, sample_threshold=256
    )
    # Las primeras 5 deben ser escalated
    assert all(c.status == "escalated" for c in result[:5])


def test_filter_already_judged_excluded():
    conv = _conv("escalated")
    result = filter_candidates([conv], {conv.id})
    assert result == []


def test_filter_empty_input():
    assert filter_candidates([], set()) == []
