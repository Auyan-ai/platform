"""Tests del gate de message cap por conversación.

Cubre:
- enforce_message_cap: pasa si bajo el cap, escala si supera,
  respeta override per-tenant, reutiliza escalación existente (idempotencia)
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from apps.api.agents.service import AgentOutcome
from apps.api.db.models import Escalation, Message
from apps.api.services.message_cap import _CAP_REASON, enforce_message_cap

from tests.conftest import (
    CONVERSATION_ID,
    ESCALATION_ID,
    INBOUND_MSG_ID,
    OUTBOUND_MSG_ID,
    TENANT_ID,
    FakeSettings,
    make_tenant_configuration,
)

# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------


def make_escalation() -> Escalation:
    return Escalation(
        id=ESCALATION_ID,
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        reason=_CAP_REASON,
        triggered_by_message_id=INBOUND_MSG_ID,
        status="pending",
        assigned_user_id=None,
        metadata={},
        created_at=datetime.datetime(2026, 5, 19, tzinfo=datetime.UTC),
    )


def make_message(msg_id: UUID = OUTBOUND_MSG_ID) -> Message:
    return Message(
        id=msg_id,
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        role="agent_ai",
        direction="outbound",
        author_user_id=None,
        content="Hemos recibido muchos mensajes...",
        attachments=[],
        metadata={},
        created_at=datetime.datetime(2026, 5, 19, tzinfo=datetime.UTC),
    )


# ----------------------------------------------------------------
# enforce_message_cap — bajo el cap
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_under_cap_returns_none():
    """Si el conteo es <= cap, devuelve None (el grafo corre normalmente)."""
    conn = AsyncMock()
    with (
        pytest.MonkeyPatch().context() as mp,
    ):
        mp.setattr(
            "apps.api.services.message_cap.count_inbound_messages",
            AsyncMock(return_value=10),
        )
        result = await enforce_message_cap(
            conn,
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            inbound_message_id=INBOUND_MSG_ID,
            tenant_config=None,
            settings=FakeSettings(),  # type: ignore[arg-type]
        )
    assert result is None


@pytest.mark.asyncio
async def test_at_cap_boundary_returns_none():
    """Exactamente en el límite (count == cap) → pasa."""
    conn = AsyncMock()
    settings = FakeSettings()
    settings.max_inbound_messages_per_conversation = 50  # type: ignore[attr-defined]
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "apps.api.services.message_cap.count_inbound_messages",
            AsyncMock(return_value=50),
        )
        result = await enforce_message_cap(
            conn,
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            inbound_message_id=INBOUND_MSG_ID,
            tenant_config=None,
            settings=settings,  # type: ignore[arg-type]
        )
    assert result is None


# ----------------------------------------------------------------
# enforce_message_cap — supera el cap
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_over_cap_creates_escalation_and_returns_outcome():
    """Si count > cap, crea escalación, inserta mensaje de cortesía y devuelve outcome."""
    conn = AsyncMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "apps.api.services.message_cap.count_inbound_messages",
            AsyncMock(return_value=51),
        )
        mp.setattr(
            "apps.api.services.message_cap.get_open_escalation_for_conversation",
            AsyncMock(return_value=None),
        )
        mp.setattr(
            "apps.api.services.message_cap.insert_message",
            AsyncMock(return_value=make_message()),
        )
        mp.setattr(
            "apps.api.services.message_cap.insert_escalation",
            AsyncMock(return_value=make_escalation()),
        )
        mp.setattr(
            "apps.api.services.message_cap.update_conversation_status",
            AsyncMock(),
        )
        result = await enforce_message_cap(
            conn,
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            inbound_message_id=INBOUND_MSG_ID,
            tenant_config=None,
            settings=FakeSettings(),  # type: ignore[arg-type]
        )

    assert isinstance(result, AgentOutcome)
    assert result.decision == "escalate"
    assert result.escalation_reason == _CAP_REASON
    assert result.escalation_id == str(ESCALATION_ID)
    assert result.output_message_id == str(OUTBOUND_MSG_ID)
    assert result.tokens_in == 0
    assert result.cost_usd == 0.0
    # Escalación nueva por cap → el caller empuja la nota + asignación al helpdesk.
    assert result.escalation_created is True


@pytest.mark.asyncio
async def test_over_cap_updates_conversation_status_to_escalated():
    """Verifica que update_conversation_status se llama con 'escalated'."""
    conn = AsyncMock()
    status_mock = AsyncMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "apps.api.services.message_cap.count_inbound_messages",
            AsyncMock(return_value=100),
        )
        mp.setattr(
            "apps.api.services.message_cap.get_open_escalation_for_conversation",
            AsyncMock(return_value=None),
        )
        mp.setattr(
            "apps.api.services.message_cap.insert_message",
            AsyncMock(return_value=make_message()),
        )
        mp.setattr(
            "apps.api.services.message_cap.insert_escalation",
            AsyncMock(return_value=make_escalation()),
        )
        mp.setattr(
            "apps.api.services.message_cap.update_conversation_status",
            status_mock,
        )
        await enforce_message_cap(
            conn,
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            inbound_message_id=INBOUND_MSG_ID,
            tenant_config=None,
            settings=FakeSettings(),  # type: ignore[arg-type]
        )

    status_mock.assert_awaited_once()
    _, kwargs = status_mock.call_args
    assert kwargs.get("status", status_mock.call_args.args[-1]) == "escalated" or \
        status_mock.call_args.args[-1] == "escalated"


# ----------------------------------------------------------------
# Idempotencia — escalación existente
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_escalation_is_reused():
    """Si ya hay una escalación activa, la reutiliza sin crear duplicados."""
    conn = AsyncMock()
    insert_esc_mock = AsyncMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "apps.api.services.message_cap.count_inbound_messages",
            AsyncMock(return_value=99),
        )
        mp.setattr(
            "apps.api.services.message_cap.get_open_escalation_for_conversation",
            AsyncMock(return_value=make_escalation()),
        )
        mp.setattr(
            "apps.api.services.message_cap.insert_escalation",
            insert_esc_mock,
        )
        result = await enforce_message_cap(
            conn,
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            inbound_message_id=INBOUND_MSG_ID,
            tenant_config=None,
            settings=FakeSettings(),  # type: ignore[arg-type]
        )

    insert_esc_mock.assert_not_awaited()
    assert result is not None
    assert result.escalation_id == str(ESCALATION_ID)
    assert result.output_message_id is None  # no se insertó mensaje de cortesía
    # Reusa una escalación existente → NO se re-empuja al helpdesk (anti-duplicado).
    assert result.escalation_created is False


# ----------------------------------------------------------------
# Override per-tenant
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_override_used_instead_of_default():
    """Override per-tenant en extra.max_inbound_messages es respetado."""
    conn = AsyncMock()
    # count=10 supera el cap custom de 5, pero NO el default de 50
    tenant_config = make_tenant_configuration(extra={"max_inbound_messages": 5})
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "apps.api.services.message_cap.count_inbound_messages",
            AsyncMock(return_value=10),
        )
        mp.setattr(
            "apps.api.services.message_cap.get_open_escalation_for_conversation",
            AsyncMock(return_value=None),
        )
        mp.setattr(
            "apps.api.services.message_cap.insert_message",
            AsyncMock(return_value=make_message()),
        )
        mp.setattr(
            "apps.api.services.message_cap.insert_escalation",
            AsyncMock(return_value=make_escalation()),
        )
        mp.setattr(
            "apps.api.services.message_cap.update_conversation_status",
            AsyncMock(),
        )
        result = await enforce_message_cap(
            conn,
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            inbound_message_id=INBOUND_MSG_ID,
            tenant_config=tenant_config,
            settings=FakeSettings(),  # type: ignore[arg-type]
        )

    assert result is not None
    assert result.decision == "escalate"


@pytest.mark.asyncio
async def test_invalid_tenant_override_uses_default():
    """Override <= 0 es ignorado; se usa el default."""
    conn = AsyncMock()
    # count=10 NO supera el default de 50; el override de 0 se ignora
    tenant_config = make_tenant_configuration(extra={"max_inbound_messages": 0})
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "apps.api.services.message_cap.count_inbound_messages",
            AsyncMock(return_value=10),
        )
        result = await enforce_message_cap(
            conn,
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            inbound_message_id=INBOUND_MSG_ID,
            tenant_config=tenant_config,
            settings=FakeSettings(),  # type: ignore[arg-type]
        )

    assert result is None
