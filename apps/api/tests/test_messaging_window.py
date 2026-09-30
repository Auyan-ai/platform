"""Ventana de 24 h de WhatsApp (services/messaging_window)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from apps.api.services import messaging_window
from apps.api.services.messaging_window import (
    WINDOW_POLICIES,
    compute_window,
    window_state,
)

from tests.conftest import TENANT_ID, make_conversation

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
WA = WINDOW_POLICIES["whatsapp"]


def test_only_whatsapp_policy_exists() -> None:
    assert set(WINDOW_POLICIES) == {"whatsapp"}
    assert WA.duration == timedelta(hours=24)


def test_open_inside_window() -> None:
    state = compute_window(NOW - timedelta(hours=2), WA, NOW)
    assert state.open is True
    assert state.closes_at == NOW + timedelta(hours=22)


def test_closed_after_24h() -> None:
    assert compute_window(NOW - timedelta(hours=25), WA, NOW).open is False


def test_safety_margin_closes_at_23h50() -> None:
    assert compute_window(NOW - timedelta(hours=23, minutes=49), WA, NOW).open is True
    assert compute_window(NOW - timedelta(hours=23, minutes=51), WA, NOW).open is False


def test_never_written_is_closed() -> None:
    assert compute_window(None, WA, NOW) == messaging_window.WindowState(False, None)


def test_naive_datetime_is_utc() -> None:
    naive = (NOW - timedelta(hours=1)).replace(tzinfo=None)
    assert compute_window(naive, WA, NOW).open is True


async def test_window_state_uses_the_whole_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ventana es del chat de Zernio (todas las sesiones), no de la conversación."""
    last = AsyncMock(return_value=datetime.now(UTC) - timedelta(hours=1))
    monkeypatch.setattr(messaging_window, "get_last_customer_inbound_at", last)
    conv = make_conversation(channel="whatsapp", external_id="zconv-1")
    state = await window_state(AsyncMock(), tenant_id=TENANT_ID, conversation=conv)
    assert state.open is True
    assert last.await_args.args[1:] == (TENANT_ID, "whatsapp", "zconv-1")


async def test_helpdesk_has_no_window(monkeypatch: pytest.MonkeyPatch) -> None:
    last = AsyncMock()
    monkeypatch.setattr(messaging_window, "get_last_customer_inbound_at", last)
    conv = make_conversation(channel="zendesk", external_id="42")
    assert (await window_state(AsyncMock(), tenant_id=TENANT_ID, conversation=conv)).open
    last.assert_not_awaited()
