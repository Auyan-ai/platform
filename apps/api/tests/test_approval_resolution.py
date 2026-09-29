"""Tests de la liberación de la escalación de una aprobación L3.

Bug visto en el E2E en vivo (pedido #1428): tras aprobar y ejecutar la
cancelación, la escalación `awaiting_human_approval:{id}` quedaba 'pending', la
conversación 'escalated' y el ticket abierto para siempre.
"""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock
from uuid import UUID

import pytest
from apps.api.services import approval_resolution
from apps.api.tests.conftest import CONVERSATION_ID, TENANT_ID

APPROVAL_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
MODULE = "apps.api.services.approval_resolution"


@pytest.fixture
def q(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "resolve": AsyncMock(return_value=True),
        "open_esc": AsyncMock(return_value=None),
        "reactivate": AsyncMock(return_value=True),
    }
    monkeypatch.setattr(f"{MODULE}.resolve_escalation_by_reason", mocks["resolve"])
    monkeypatch.setattr(f"{MODULE}.get_open_escalation_for_conversation", mocks["open_esc"])
    monkeypatch.setattr(f"{MODULE}.reactivate_escalated_conversation", mocks["reactivate"])
    return mocks


@pytest.mark.asyncio
async def test_resolves_its_escalation_and_reactivates_conversation(
    q: dict[str, AsyncMock],
) -> None:
    released = await approval_resolution.release_approval_escalation(
        AsyncMock(), tenant_id=TENANT_ID, conversation_id=CONVERSATION_ID, approval_id=APPROVAL_ID
    )

    assert released is True
    q["resolve"].assert_awaited_once_with(
        ANY, TENANT_ID, CONVERSATION_ID, f"awaiting_human_approval:{APPROVAL_ID}"
    )
    q["reactivate"].assert_awaited_once_with(ANY, TENANT_ID, CONVERSATION_ID)


@pytest.mark.asyncio
async def test_keeps_escalated_if_another_escalation_is_open(q: dict[str, AsyncMock]) -> None:
    """Otra escalación activa (p. ej. el cliente pidió un humano) → sigue escalada."""
    q["open_esc"].return_value = object()

    await approval_resolution.release_approval_escalation(
        AsyncMock(), tenant_id=TENANT_ID, conversation_id=CONVERSATION_ID, approval_id=APPROVAL_ID
    )

    q["reactivate"].assert_not_awaited()


@pytest.mark.asyncio
async def test_no_matching_escalation_is_noop(q: dict[str, AsyncMock]) -> None:
    q["resolve"].return_value = False

    released = await approval_resolution.release_approval_escalation(
        AsyncMock(), tenant_id=TENANT_ID, conversation_id=CONVERSATION_ID, approval_id=APPROVAL_ID
    )

    assert released is False
    q["reactivate"].assert_not_awaited()


class TestReplyDelivered:
    def test_helpdesk_channel_uses_delivery_result(self) -> None:
        assert approval_resolution.reply_delivered("zendesk", delivered=True) is True
        assert approval_resolution.reply_delivered("zendesk", delivered=False) is False

    def test_channel_without_helpdesk_counts_as_delivered(self) -> None:
        """chat/widget de prueba: el mensaje en DB es la entrega (no hay helpdesk)."""
        assert approval_resolution.reply_delivered("chat", delivered=False) is True
