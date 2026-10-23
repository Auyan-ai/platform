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


@pytest.mark.asyncio
async def test_executed_action_closes_all_open_escalations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acción ejecutada: se cierran todas (incluido un escalado previo por la misma
    petición que el gate reutilizó) y la conversación vuelve a 'open'."""
    resolve_all = AsyncMock(return_value=2)
    reactivate = AsyncMock(return_value=True)
    monkeypatch.setattr(f"{MODULE}.resolve_open_escalations_for_conversation", resolve_all)
    monkeypatch.setattr(f"{MODULE}.reactivate_escalated_conversation", reactivate)

    closed = await approval_resolution.release_escalations_after_executed_action(
        AsyncMock(), tenant_id=TENANT_ID, conversation_id=CONVERSATION_ID
    )

    assert closed == 2
    resolve_all.assert_awaited_once_with(ANY, TENANT_ID, CONVERSATION_ID)
    reactivate.assert_awaited_once_with(ANY, TENANT_ID, CONVERSATION_ID)


class TestReplyDelivered:
    def test_helpdesk_channel_uses_delivery_result(self) -> None:
        assert approval_resolution.reply_delivered("zendesk", delivered=True) is True
        assert approval_resolution.reply_delivered("zendesk", delivered=False) is False

    def test_channel_without_helpdesk_counts_as_delivered(self) -> None:
        """chat/widget de prueba: el mensaje en DB es la entrega (no hay helpdesk)."""
        assert approval_resolution.reply_delivered("chat", delivered=False) is True

    def test_messaging_channel_requires_delivery(self) -> None:
        """WhatsApp tiene ruta de entrega (Zernio): sin entrega confirmada no cuenta."""
        assert approval_resolution.reply_delivered("whatsapp", delivered=False) is False
        assert approval_resolution.reply_delivered("whatsapp", delivered=True) is True


# ----------------------------------------------------------------
# #318: acción ejecutada que el equipo tiene que rematar
# ----------------------------------------------------------------


def test_followup_reason_for_failed_refund_names_the_gateway_error() -> None:
    reason = approval_resolution.team_followup_reason(
        "shopify.refund_partial",
        {"order_id": 1001, "outcome": "refund_failed", "detail": "CARD_DECLINED"},
    )
    assert reason == (
        "El reembolso parcial del pedido 1001 se ejecutó en Shopify, pero el reembolso no "
        "se completó (CARD_DECLINED). Revisad el pago y devolvedlo a mano si hace falta."
    )


@pytest.mark.parametrize(
    "output",
    [{"outcome": "confirmed"}, {"outcome": "refund_pending"}, {"cancelled": True}],
    ids=["confirmed", "pending", "no-outcome"],
)
def test_no_followup_when_the_action_is_settled(output: dict) -> None:
    assert approval_resolution.team_followup_reason("shopify.cancel_order", output) is None


@pytest.mark.asyncio
async def test_hand_off_closes_the_gate_and_opens_an_escalation_with_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    escalation_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    resolve_all = AsyncMock(return_value=1)
    insert = AsyncMock(return_value=type("Esc", (), {"id": escalation_id})())
    set_status = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.resolve_open_escalations_for_conversation", resolve_all)
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", set_status)

    result = await approval_resolution.hand_approval_to_team(
        AsyncMock(),
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        approval_id=APPROVAL_ID,
        reason="Reembolso manual pendiente",
    )

    assert result == escalation_id
    resolve_all.assert_awaited_once_with(ANY, TENANT_ID, CONVERSATION_ID)
    assert insert.await_args.kwargs == {
        "tenant_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "reason": "Reembolso manual pendiente",
        "metadata": {"approval_id": str(APPROVAL_ID)},
    }
    set_status.assert_awaited_once_with(ANY, TENANT_ID, CONVERSATION_ID, "escalated")
