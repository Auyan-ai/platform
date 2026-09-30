"""Entrega consciente de la ventana (services/channel_delivery) + pendientes + failed."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from apps.api.core.errors import ExternalIntegrationError
from apps.api.integrations.zernio import ZernioEvent, ZernioSendResult, parse_zernio_event
from apps.api.services import channel_delivery, helpdesk_delivery, zernio_events
from apps.api.services.channel_delivery import deliver_to_customer, flush_pending_messages
from apps.api.services.messaging_window import WindowState

from tests.conftest import TENANT_ID, make_conversation, make_end_customer, make_message

MSG_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
OTHER_MSG = UUID("aaaaaaaa-0000-0000-0000-000000000002")
MOD = "apps.api.services.channel_delivery"


def _wa_conv() -> Any:
    return make_conversation(channel="whatsapp", external_id="zconv-1")


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    adapter = MagicMock()
    adapter.send_outbound = AsyncMock(
        return_value=[ZernioSendResult(message_id="wamid.1", conversation_id="zconv-1")]
    )
    adapter.send_reengagement_template = AsyncMock(
        return_value=ZernioSendResult(message_id="wamid.T", conversation_id="zconv-1")
    )
    m: dict[str, Any] = {
        "load_delivery_client": AsyncMock(return_value=(adapter, object())),
        "window_state": AsyncMock(return_value=WindowState(True, None)),
        "merge_message_metadata": AsyncMock(return_value=True),
        "list_pending_window_messages": AsyncMock(return_value=[]),
        "get_end_customer": AsyncMock(return_value=make_end_customer(full_name="Ana López")),
    }
    for name, mock in m.items():
        monkeypatch.setattr(f"{MOD}.{name}", mock)
    m["adapter"] = adapter
    return m


async def _deliver(message_id: UUID | None = MSG_ID, conv: Any = None) -> str:
    return await deliver_to_customer(
        AsyncMock(),
        tenant_id=TENANT_ID,
        conversation=conv or _wa_conv(),
        content="**Listo**, dirección cambiada.",
        message_id=message_id,
    )


async def test_open_window_sends_with_idempotency_key_and_stores_wamid(env: dict) -> None:
    assert await _deliver() == "delivered"
    call = env["adapter"].send_outbound.await_args
    assert call.args[1:] == ("zconv-1", "**Listo**, dirección cambiada.")
    assert call.kwargs == {"idempotency_key": str(MSG_ID)}
    patch = env["merge_message_metadata"].await_args.args[3]
    assert patch["delivery"] == "delivered"
    assert patch["zernio_platform_message_ids"] == ["wamid.1"]
    env["adapter"].send_reengagement_template.assert_not_awaited()


async def test_closed_window_sends_template_and_parks_message(env: dict) -> None:
    env["window_state"].return_value = WindowState(False, None)
    assert await _deliver() == "pending_window"
    env["adapter"].send_outbound.assert_not_awaited()
    tpl = env["adapter"].send_reengagement_template.await_args
    assert tpl.kwargs == {"first_name": "Ana", "idempotency_key": f"reengage:{MSG_ID}"}
    patch = env["merge_message_metadata"].await_args.args[3]
    assert patch["delivery"] == "pending_window"
    assert patch["reengagement_platform_message_ids"] == ["wamid.T"]


async def test_second_pending_message_does_not_resend_template(env: dict) -> None:
    env["window_state"].return_value = WindowState(False, None)
    env["list_pending_window_messages"].return_value = [make_message(id=OTHER_MSG)]
    assert await _deliver() == "pending_window"
    env["adapter"].send_reengagement_template.assert_not_awaited()


async def test_customer_without_name_uses_fallback(env: dict) -> None:
    env["window_state"].return_value = WindowState(False, None)
    env["get_end_customer"].return_value = make_end_customer(full_name=None)
    await _deliver()
    kwargs = env["adapter"].send_reengagement_template.await_args.kwargs
    assert kwargs["first_name"] == channel_delivery.REENGAGEMENT_FALLBACK_NAME


async def test_missing_template_fails_and_logs_error(
    env: dict, caplog: pytest.LogCaptureFixture
) -> None:
    env["window_state"].return_value = WindowState(False, None)
    env["adapter"].send_reengagement_template.side_effect = ExternalIntegrationError(
        "no template", code="zernio_no_reengagement_template"
    )
    assert await _deliver() == "failed"
    patch = env["merge_message_metadata"].await_args.args[3]
    assert patch["delivery"] == "failed"
    assert patch["delivery_error"]["code"] == "zernio_no_reengagement_template"
    assert any(r.levelname == "ERROR" for r in caplog.records)


async def test_closed_window_without_message_id_fails(env: dict) -> None:
    env["window_state"].return_value = WindowState(False, None)
    assert await _deliver(message_id=None) == "failed"


async def test_send_error_marks_failed(env: dict) -> None:
    env["adapter"].send_outbound.side_effect = ExternalIntegrationError("x", code="zernio_131056")
    assert await _deliver() == "failed"
    patch = env["merge_message_metadata"].await_args.args[3]
    assert patch == {"delivery": "failed", "delivery_error": {"code": "zernio_131056"}}


async def test_no_route_fails(env: dict) -> None:
    env["load_delivery_client"].return_value = None
    assert await _deliver() == "failed"


async def test_helpdesk_path_is_unchanged(env: dict) -> None:
    conv = make_conversation(channel="zendesk", external_id="42")
    assert await _deliver(conv=conv) == "delivered"
    assert env["adapter"].send_outbound.await_args.kwargs == {}
    env["window_state"].assert_not_awaited()


# ─── Pendientes ───────────────────────────────────────────────────────────────


async def test_flush_delivers_pending_in_order(env: dict) -> None:
    env["list_pending_window_messages"].return_value = [
        make_message(id=OTHER_MSG, content="primero", direction="outbound"),
        make_message(id=MSG_ID, content="segundo", direction="outbound"),
    ]
    n = await flush_pending_messages(AsyncMock(), tenant_id=TENANT_ID, conversation=_wa_conv())
    assert n == 2
    sent = [c.args[2] for c in env["adapter"].send_outbound.await_args_list]
    keys = [c.kwargs["idempotency_key"] for c in env["adapter"].send_outbound.await_args_list]
    assert sent == ["primero", "segundo"]
    assert keys == [str(OTHER_MSG), str(MSG_ID)]
    assert all(
        c.args[3]["delivery"] == "delivered" for c in env["merge_message_metadata"].await_args_list
    )


async def test_flush_continues_after_a_failure(env: dict) -> None:
    env["list_pending_window_messages"].return_value = [
        make_message(id=OTHER_MSG, content="a", direction="outbound"),
        make_message(id=MSG_ID, content="b", direction="outbound"),
    ]
    env["adapter"].send_outbound.side_effect = [ExternalIntegrationError("x", code="c"), []]
    assert (
        await flush_pending_messages(AsyncMock(), tenant_id=TENANT_ID, conversation=_wa_conv()) == 1
    )


async def test_flush_is_noop_for_helpdesk(env: dict) -> None:
    conv = make_conversation(channel="zendesk", external_id="42")
    assert await flush_pending_messages(AsyncMock(), tenant_id=TENANT_ID, conversation=conv) == 0
    env["list_pending_window_messages"].assert_not_awaited()


# ─── Aprobaciones L3 (deliver_message_to_helpdesk) ─────────────────────────────


async def test_approval_on_whatsapp_pending_is_not_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deliver = AsyncMock(return_value="pending_window")
    monkeypatch.setattr(helpdesk_delivery, "deliver_to_customer", deliver)
    ok = await helpdesk_delivery.deliver_message_to_helpdesk(
        AsyncMock(),
        tenant_id=TENANT_ID,
        conversation=_wa_conv(),
        content="hecho",
        message_id=MSG_ID,
    )
    assert ok is False
    assert deliver.await_args.kwargs["message_id"] == MSG_ID


async def test_approval_on_whatsapp_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        helpdesk_delivery, "deliver_to_customer", AsyncMock(return_value="delivered")
    )
    ok = await helpdesk_delivery.deliver_message_to_helpdesk(
        AsyncMock(),
        tenant_id=TENANT_ID,
        conversation=_wa_conv(),
        content="hecho",
        message_id=MSG_ID,
    )
    assert ok is True


# ─── message.failed ───────────────────────────────────────────────────────────


def _failed_event() -> ZernioEvent:
    return parse_zernio_event(
        {
            "id": "evt_f",
            "event": "message.failed",
            "message": {"id": "m9", "platformMessageId": "wamid.1", "direction": "outgoing"},
            "error": {"code": 131047, "title": "Re-engagement message", "explanation": "24h"},
            "account": {"id": "acc-1"},
            "statusAt": datetime.now(UTC).isoformat(),
        }
    )


async def test_message_failed_marks_our_message(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from tests.conftest import make_fake_tenant_scope

    found = make_message(id=MSG_ID, direction="outbound")
    finder = AsyncMock(return_value=found)
    merge = AsyncMock(return_value=True)
    monkeypatch.setattr(zernio_events, "tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(zernio_events, "find_outbound_message_by_platform_id", finder)
    monkeypatch.setattr(zernio_events, "merge_message_metadata", merge)
    result = await zernio_events.handle_zernio_status_event(
        _failed_event(), tenant_id=TENANT_ID, integration=MagicMock()
    )
    assert result["matched"] is True
    assert finder.await_args.args[1:] == (TENANT_ID, "wamid.1")
    patch = merge.await_args.args[3]
    assert patch["delivery"] == "failed"
    assert patch["delivery_error"]["code"] == 131047
    assert any(
        r.message == "zernio_message_failed" and r.levelname == "ERROR" for r in caplog.records
    )
