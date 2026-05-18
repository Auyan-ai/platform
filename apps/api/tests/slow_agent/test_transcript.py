"""Tests del builder de transcript."""

from __future__ import annotations

import uuid
from datetime import datetime

from apps.api.db.models import (
    Conversation,
    Message,
    SkillAuditLog,
)
from apps.api.slow_agent.transcript import (
    build_transcript,
    format_for_judge,
    transcript_has_l2_l3_skills,
)

TENANT = uuid.uuid4()
CONV_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
NOW = datetime(2026, 5, 19, 12, 0, 0)


def _conv(status: str = "escalated") -> Conversation:
    return Conversation(
        id=CONV_ID,
        tenant_id=TENANT,
        end_customer_id=CUSTOMER_ID,
        channel="chat",
        status=status,  # type: ignore[arg-type]
        created_at=NOW,
    )


def _msg(role: str, content: str) -> Message:
    return Message(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        conversation_id=CONV_ID,
        role=role,  # type: ignore[arg-type]
        direction="inbound",
        content=content,
        created_at=NOW,
    )


def _audit(tier: str = "L1", status: str = "success") -> SkillAuditLog:
    return SkillAuditLog(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        conversation_id=CONV_ID,
        aop_slug="default",
        aop_version=1,
        skill_slug="shopify.get_order_status",
        skill_tier=tier,
        inputs_redacted={"email": "test@example.com"},
        outputs_redacted={"order_id": "1234"},
        inputs_hash="abc123",
        status=status,  # type: ignore[arg-type]
        created_at=NOW,
    )


def test_build_transcript_outcome_map():
    t = build_transcript(_conv("escalated"), [], [], None, None, "salt123")
    assert t.outcome == "escalado a humano"


def test_build_transcript_resolved():
    t = build_transcript(_conv("resolved"), [], [], None, None, "salt123")
    assert t.outcome == "resuelto"


def test_build_transcript_redacts_email_in_skill_inputs():
    audit = _audit()
    t = build_transcript(_conv(), [], [audit], None, None, "salt123")
    assert "@" not in str(t.skill_audit_entries[0].inputs_redacted.get("email", ""))


def test_build_transcript_preserves_messages_raw():
    msgs = [_msg("customer", "Hola, mi email es client@test.com")]
    t = build_transcript(_conv(), msgs, [], None, None, "salt123")
    # Mensajes del cliente NO se redactan — el judge necesita el texto completo
    assert "client@test.com" in t.messages[0].content


def test_format_for_judge_contains_sections():
    msgs = [_msg("customer", "¿Dónde está mi pedido?"), _msg("agent_ai", "Necesito tu email.")]
    audit = _audit("L2")
    t = build_transcript(_conv(), msgs, [audit], None, "## Procedimiento\nAyuda al cliente", "salt")
    text = format_for_judge(t)
    assert "## Transcript de mensajes" in text
    assert "## Skills ejecutadas" in text
    assert "## Prompt compilado del AOP" in text
    assert "Cliente" in text
    assert "Agente AI" in text


def test_format_for_judge_includes_outcome():
    t = build_transcript(_conv("escalated"), [], [], None, None, "salt")
    text = format_for_judge(t)
    assert "escalado a humano" in text


def test_format_for_judge_includes_escalation_reason():
    t = build_transcript(
        _conv("escalated"), [], [], None, None, "salt",
        escalation_reason="cliente frustrado"
    )
    text = format_for_judge(t)
    assert "cliente frustrado" in text


def test_transcript_has_l2_l3_true():
    t = build_transcript(_conv(), [], [_audit("L2")], None, None, "salt")
    assert transcript_has_l2_l3_skills(t) is True


def test_transcript_has_l2_l3_false():
    t = build_transcript(_conv(), [], [_audit("L1")], None, None, "salt")
    assert transcript_has_l2_l3_skills(t) is False


def test_transcript_has_l2_l3_empty():
    t = build_transcript(_conv(), [], [], None, None, "salt")
    assert transcript_has_l2_l3_skills(t) is False
