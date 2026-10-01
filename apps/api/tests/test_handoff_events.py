"""Vuelta del handoff (Zendesk → WhatsApp), cierre sin facturar y toma desde el móvil."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import asyncpg
import pytest
from apps.api.db.models import ConversationHandoff
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.zendesk import ZendeskAgentComment
from apps.api.integrations.zernio import parse_zernio_event
from apps.api.scripts import setup_zendesk_handoff_triggers as triggers
from apps.api.services import handoff_events
from apps.api.services.handoff_events import (
    device_hold_hours,
    handle_device_takeover,
    handle_helpdesk_event,
    is_human_send,
)

from tests.conftest import (
    CONVERSATION_ID,
    TENANT_ID,
    make_conversation,
    make_fake_tenant_scope,
    make_message,
    make_tenant_configuration,
)

MOD = "apps.api.services.handoff_events"
HANDOFF_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")
MSG_ID = UUID("aaaaaaaa-0000-0000-0000-000000000009")


def _handoff(**overrides: Any) -> ConversationHandoff:
    data: dict[str, Any] = {
        "id": HANDOFF_ID,
        "tenant_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "target": "helpdesk",
        "helpdesk_provider": "zendesk",
        "external_ticket_id": "555",
        "status": "active",
        "reason": "persona",
        "opened_at": datetime.now(UTC),
    }
    data.update(overrides)
    return ConversationHandoff(**data)


def _comment(**overrides: Any) -> ZendeskAgentComment:
    data: dict[str, Any] = {
        "ticket_id": "555",
        "comment_id": "9001",
        "author_id": "42",
        "author_name": "Laura (Marea)",
        "author_role": "agent",
        "public": True,
        "content": "Hola Ana, ya te hicimos el cambio.",
        "requester_id": "777",
    }
    data.update(overrides)
    return ZendeskAgentComment(**data)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    conv = make_conversation(channel="whatsapp", external_id="zconv-1")
    m: dict[str, Any] = {
        "get_handoff_by_ticket": AsyncMock(return_value=_handoff()),
        "claim_webhook_idempotency_key": AsyncMock(return_value=True),
        "get_conversation": AsyncMock(return_value=conv),
        "find_conversation_by_external": AsyncMock(return_value=conv),
        "reopen_handoff_row": AsyncMock(return_value=True),
        "insert_message": AsyncMock(return_value=make_message(id=MSG_ID)),
        "update_conversation_last_message": AsyncMock(),
        "touch_handoff_human_activity": AsyncMock(),
        "deliver_to_customer": AsyncMock(return_value="delivered"),
        "add_handoff_note": AsyncMock(return_value=True),
        "close_handoff": AsyncMock(return_value=True),
        "resolve_open_escalations_for_conversation": AsyncMock(return_value=1),
        "reactivate_escalated_conversation": AsyncMock(return_value=True),
        "mark_conversation_resolved": AsyncMock(return_value=True),
        "find_outbound_message_by_platform_id": AsyncMock(return_value=None),
        "get_active_handoff_for_chat": AsyncMock(return_value=None),
        "insert_handoff": AsyncMock(),
    }
    for name, mock in m.items():
        monkeypatch.setattr(f"{MOD}.{name}", mock)
    conn = MagicMock()
    savepoint = MagicMock()
    savepoint.__aenter__ = AsyncMock(return_value=None)
    savepoint.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=savepoint)
    monkeypatch.setattr(f"{MOD}.tenant_scope", make_fake_tenant_scope(conn))
    adapter = MagicMock()
    adapter.fetch_handoff_comment = AsyncMock(return_value=_comment())
    m["adapter"] = adapter
    m["conv"] = conv
    return m


async def _event(env: dict[str, Any], event: str | None = "handoff_reply", **config: Any) -> dict:
    ctx = IntegrationContext(
        tenant_id=TENANT_ID, credentials={}, config={"api_user_id": "1", **config}
    )
    return await handle_helpdesk_event(
        tenant_id=TENANT_ID,
        provider="zendesk",
        adapter=env["adapter"],
        ctx=ctx,
        ticket_id="555",
        comment_id="9001",
        event=event,
    )


# ─── handoff_reply ────────────────────────────────────────────────────────────


async def test_public_agent_reply_reaches_whatsapp(env: dict[str, Any]) -> None:
    result = await _event(env)
    assert result == {"received": True, "processed": True, "delivery": "delivered"}
    key = env["claim_webhook_idempotency_key"].await_args.kwargs["key"]
    assert key == "zendesk_handoff:555:9001"
    msg = env["insert_message"].await_args.kwargs
    assert msg["role"] == "agent_human" and msg.get("author_user_id") is None
    assert msg["metadata"]["external_author"] == {
        "provider": "zendesk",
        "id": "42",
        "name": "Laura (Marea)",
    }
    deliver = env["deliver_to_customer"].await_args.kwargs
    assert deliver["message_id"] == MSG_ID
    assert deliver["content"] == "Hola Ana, ya te hicimos el cambio."
    env["touch_handoff_human_activity"].assert_awaited_once()


@pytest.mark.parametrize(
    ("comment", "reason"),
    [
        ({"public": False}, "private_comment"),
        ({"author_id": "777"}, "requester_comment"),
        ({"author_id": "1"}, "api_user_comment"),
        ({"content": ""}, "empty_content"),
    ],
)
async def test_comments_that_never_reach_the_customer(
    env: dict[str, Any], comment: dict[str, Any], reason: str
) -> None:
    env["adapter"].fetch_handoff_comment.return_value = _comment(**comment)
    assert (await _event(env))["ignored"] == reason
    env["insert_message"].assert_not_awaited()
    env["deliver_to_customer"].assert_not_awaited()


async def test_zendesk_retry_is_not_duplicated(env: dict[str, Any]) -> None:
    env["claim_webhook_idempotency_key"].return_value = False
    assert (await _event(env))["duplicate"] is True
    env["deliver_to_customer"].assert_not_awaited()


async def test_closed_window_is_pending_not_failed(env: dict[str, Any]) -> None:
    env["deliver_to_customer"].return_value = "pending_window"
    assert (await _event(env))["delivery"] == "pending_window"
    env["add_handoff_note"].assert_not_awaited()  # la nota la deja channel_delivery


async def test_failed_delivery_warns_in_the_ticket(env: dict[str, Any]) -> None:
    env["deliver_to_customer"].return_value = "failed"
    assert (await _event(env))["delivery"] == "failed"
    assert "NO la recibió" in env["add_handoff_note"].await_args.kwargs["content"]


async def test_reply_on_solved_ticket_reopens_the_handoff(env: dict[str, Any]) -> None:
    env["get_handoff_by_ticket"].return_value = _handoff(
        status="closed", closed_at=datetime.now(UTC), closed_reason="helpdesk_solved"
    )
    await _event(env)
    env["reopen_handoff_row"].assert_awaited_once()
    env["deliver_to_customer"].assert_awaited_once()


async def test_ticket_without_handoff_is_ignored(env: dict[str, Any]) -> None:
    env["get_handoff_by_ticket"].return_value = None
    assert (await _event(env))["ignored"] == "handoff_not_found"


# ─── handoff_solved ───────────────────────────────────────────────────────────


async def test_solved_closes_handoff_and_resolves_without_billing(env: dict[str, Any]) -> None:
    result = await _event(env, event="handoff_solved")
    assert result["event"] == "handoff_solved"
    assert env["close_handoff"].await_args.kwargs["reason"] == "helpdesk_solved"
    env["resolve_open_escalations_for_conversation"].assert_awaited_once()
    env["mark_conversation_resolved"].assert_awaited_once()
    assert not hasattr(handoff_events, "insert_resolution_event")
    env["deliver_to_customer"].assert_not_awaited()


async def test_solved_twice_is_idempotent(env: dict[str, Any]) -> None:
    env["get_handoff_by_ticket"].return_value = _handoff(
        status="closed", closed_at=datetime.now(UTC)
    )
    assert (await _event(env, event="handoff_solved"))["ignored"] == "handoff_already_closed"
    env["close_handoff"].assert_not_awaited()


# ─── Toma desde el móvil ──────────────────────────────────────────────────────


def _sent(source: str | None = "whatsapp_business_app", sent_via: str | None = None) -> Any:
    return parse_zernio_event(
        {
            "id": "evt_s",
            "event": "message.sent",
            "message": {
                "id": "m1",
                "conversationId": "zconv-1",
                "platform": "whatsapp",
                "platformMessageId": "wamid.PHONE",
                "direction": "outgoing",
                "text": "Te escribo yo, Ana",
                "source": source,
                "sentVia": sent_via,
            },
            "conversation": {"id": "zconv-1"},
            "account": {"id": "acc-1"},
        }
    )


def test_human_send_detection() -> None:
    assert is_human_send(_sent())
    assert is_human_send(_sent(source="cloud_api", sent_via="human"))
    assert not is_human_send(_sent(source="cloud_api", sent_via="api"))
    assert not is_human_send(_sent(source="meta_business_agent"))


def test_device_hold_hours_default_and_override() -> None:
    assert device_hold_hours(None) == 12
    cfg = make_tenant_configuration(extra={"whatsapp_device_hold_hours": 4})
    assert device_hold_hours(cfg) == 4


async def test_phone_reply_opens_12h_device_hold(env: dict[str, Any]) -> None:
    before = datetime.now(UTC)
    result = await handle_device_takeover(_sent(), tenant_id=TENANT_ID, tenant_config=None)
    assert result["outcome"] == "device_hold_opened"
    msg = env["insert_message"].await_args.kwargs
    assert msg["metadata"]["external_author"] == {"provider": "whatsapp_business_app"}
    handoff = env["insert_handoff"].await_args.kwargs
    assert handoff["target"] == "device"
    assert handoff["expires_at"] >= before + timedelta(hours=12)


async def test_our_own_api_send_is_ignored(env: dict[str, Any]) -> None:
    env["find_outbound_message_by_platform_id"].return_value = make_message()
    result = await handle_device_takeover(_sent(), tenant_id=TENANT_ID, tenant_config=None)
    assert result["ignored"] == "own_message"
    env["insert_handoff"].assert_not_awaited()


async def test_phone_reply_with_helpdesk_handoff_only_records(env: dict[str, Any]) -> None:
    env["get_active_handoff_for_chat"].return_value = _handoff()
    result = await handle_device_takeover(_sent(), tenant_id=TENANT_ID, tenant_config=None)
    assert result["outcome"] == "helpdesk_handoff_active"
    env["insert_handoff"].assert_not_awaited()


async def test_phone_reply_renews_device_hold(env: dict[str, Any]) -> None:
    env["get_active_handoff_for_chat"].return_value = _handoff(
        target="device",
        helpdesk_provider=None,
        external_ticket_id=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    result = await handle_device_takeover(_sent(), tenant_id=TENANT_ID, tenant_config=None)
    assert result["outcome"] == "device_hold_renewed"
    assert env["touch_handoff_human_activity"].await_args.kwargs["expires_at"] > datetime.now(
        UTC
    ) + timedelta(hours=11)


async def test_concurrent_handoff_does_not_break(env: dict[str, Any]) -> None:
    env["insert_handoff"].side_effect = asyncpg.UniqueViolationError("dup")
    result = await handle_device_takeover(_sent(), tenant_id=TENANT_ID, tenant_config=None)
    assert result["outcome"] == "handoff_opened_concurrently"


async def test_duplicate_sent_event(env: dict[str, Any]) -> None:
    env["claim_webhook_idempotency_key"].return_value = False
    result = await handle_device_takeover(_sent(), tenant_id=TENANT_ID, tenant_config=None)
    assert result["duplicate"] is True
    env["insert_message"].assert_not_awaited()


# ─── Triggers de Zendesk (definiciones) ───────────────────────────────────────


def test_reply_trigger_definition() -> None:
    t = triggers.reply_trigger("wh-1", "acme")
    fields = {(c["field"], c["operator"], c["value"]) for c in t["conditions"]["all"]}
    assert ("current_tags", "includes", "auyan_handoff") in fields
    assert ("comment_is_public", "is", "true") in fields
    assert ("role", "is", "agent") in fields
    webhook_id, body = t["actions"][0]["value"]
    assert webhook_id == "wh-1"
    assert '"event": "handoff_reply"' in body and '"subdomain": "acme"' in body
    assert "comment_id" in body


def test_solved_trigger_definition() -> None:
    t = triggers.solved_trigger("wh-1", "acme")
    assert {"field": "status", "operator": "value", "value": "solved"} in t["conditions"][
        "all"
    ]
    assert "comment_id" not in t["actions"][0]["value"][1]


def test_inbound_trigger_gets_not_handoff_condition_once() -> None:
    inbound = {
        "id": 1,
        "conditions": {"all": [{"field": "role", "operator": "is", "value": "end_user"}]},
        "actions": [{"field": "notification_webhook", "value": ["wh-1", '{"ticket_id": 1}']}],
    }
    handoff = {
        "id": 2,
        "actions": [{"field": "notification_webhook", "value": ["wh-1", "handoff_reply"]}],
    }
    other = {"id": 3, "actions": [{"field": "notification_webhook", "value": ["wh-9", "{}"]}]}
    assert triggers.find_inbound_triggers([inbound, handoff, other], "wh-1") == [inbound]
    conditions = triggers.with_not_handoff_condition(inbound)
    assert conditions is not None and triggers.NOT_HANDOFF_CONDITION in conditions["all"]
    inbound["conditions"] = conditions
    assert triggers.with_not_handoff_condition(inbound) is None


def test_find_auyan_webhook() -> None:
    webhooks = [
        {"id": "a", "endpoint": "https://otro.example/hook"},
        {"id": "b", "endpoint": "https://api.auyan.es/webhooks/zendesk"},
    ]
    assert triggers.find_auyan_webhook(webhooks, None)["id"] == "b"
    assert triggers.find_auyan_webhook(webhooks, "https://staging.example") is None


# ─── Enrutado en los webhooks ─────────────────────────────────────────────────


async def test_zernio_message_sent_from_phone_goes_to_takeover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.services import zernio_events

    from tests.conftest import make_fake_bootstrap_connection

    takeover = AsyncMock(return_value={"processed": True})
    monkeypatch.setattr(zernio_events, "handle_device_takeover", takeover)
    monkeypatch.setattr(zernio_events, "bootstrap_connection", make_fake_bootstrap_connection())
    monkeypatch.setattr(zernio_events, "get_tenant_configuration", AsyncMock(return_value=None))
    await zernio_events.handle_zernio_status_event(
        _sent(), tenant_id=TENANT_ID, integration=MagicMock()
    )
    takeover.assert_awaited_once()
    takeover.reset_mock()
    await zernio_events.handle_zernio_status_event(
        _sent(source="cloud_api", sent_via="api"), tenant_id=TENANT_ID, integration=MagicMock()
    )
    takeover.assert_not_awaited()


class TestZendeskRouterHandoff:
    MODULE = "apps.api.routers.webhooks_zendesk"

    def _setup(self, monkeypatch: pytest.MonkeyPatch, *, is_handoff: bool) -> dict[str, Any]:
        from tests.test_inbound_intake import _patch_router_bootstrap

        intake = _patch_router_bootstrap(
            monkeypatch, self.MODULE, "get_integration_by_zendesk_subdomain"
        )
        handler = AsyncMock(return_value={"received": True, "processed": True})
        monkeypatch.setattr(f"{self.MODULE}.handle_helpdesk_event", handler)
        monkeypatch.setattr(f"{self.MODULE}._is_handoff_ticket", AsyncMock(return_value=is_handoff))
        fetch = AsyncMock()
        monkeypatch.setattr(f"{self.MODULE}.ZendeskAdapter.fetch_inbound_comment", fetch)
        return {"intake": intake, "handler": handler, "fetch": fetch}

    def _post(self, payload: dict[str, Any]) -> Any:
        from apps.api.routers.webhooks_zendesk import router
        from fastapi.testclient import TestClient

        from tests.test_inbound_intake import _app

        app, _ = _app(router)
        with TestClient(app) as client:
            return client.post("/webhooks/zendesk", json=payload)

    def test_handoff_event_never_enters_intake(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = self._setup(monkeypatch, is_handoff=False)
        r = self._post(
            {"ticket_id": "555", "comment_id": "9", "subdomain": "acme", "event": "handoff_reply"}
        )
        assert r.status_code == 200
        kwargs = m["handler"].await_args.kwargs
        assert (kwargs["ticket_id"], kwargs["comment_id"], kwargs["event"]) == (
            "555",
            "9",
            "handoff_reply",
        )
        m["intake"].assert_not_awaited()
        m["fetch"].assert_not_awaited()

    def test_ticket_of_a_handoff_never_enters_intake(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Aunque llegue por el trigger de inbound (sin `event`), anti-loop en código."""
        m = self._setup(monkeypatch, is_handoff=True)
        r = self._post({"ticket_id": "555", "comment_id": "9", "subdomain": "acme"})
        assert r.status_code == 200
        m["handler"].assert_awaited_once()
        m["intake"].assert_not_awaited()
