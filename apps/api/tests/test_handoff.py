"""Handoff modular (services/handoff) + enrutado del escalado + worker con handoff."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from apps.api.db.models import ConversationHandoff, TenantIntegration
from apps.api.integrations.base import (
    ExternalTicketRef,
    HandoffRequest,
    IntegrationContext,
    StoredAttachment,
)
from apps.api.integrations.zendesk import ZendeskAdapter, format_handoff_note
from apps.api.services import handoff as handoff_mod
from apps.api.services import helpdesk_escalation
from apps.api.services.handoff import (
    HandoffUnavailableError,
    format_transcript,
    is_approval_gate,
    open_handoff,
    open_handoff_safe,
)
from apps.api.services.messaging_window import WindowState

from tests.conftest import (
    CONVERSATION_ID,
    TENANT_ID,
    make_conversation,
    make_end_customer,
    make_fake_tenant_scope,
    make_message,
)

HANDOFF_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")
MOD = "apps.api.services.handoff"


def _handoff(**overrides: Any) -> ConversationHandoff:
    data: dict[str, Any] = {
        "id": HANDOFF_ID,
        "tenant_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "target": "helpdesk",
        "helpdesk_provider": "zendesk",
        "external_ticket_id": "555",
        "status": "active",
        "reason": "quiere hablar con una persona",
        "opened_at": datetime.now(UTC),
    }
    data.update(overrides)
    return ConversationHandoff(**data)


def _wa_conv() -> Any:
    return make_conversation(channel="whatsapp", external_id="zconv-1")


# ─── Utilidades puras ─────────────────────────────────────────────────────────


def test_approval_gate_detection() -> None:
    assert is_approval_gate("awaiting_human_approval:123")
    assert not is_approval_gate("cliente enfadado")
    assert not is_approval_gate(None)


def test_transcript_is_literal_and_labeled() -> None:
    at = datetime(2026, 10, 1, 10, 5, tzinfo=UTC)
    messages = [
        make_message(role="customer", content="¿Dónde está mi pedido?", created_at=at),
        make_message(role="agent_ai", content="Déjame revisarlo.", created_at=at),
        make_message(
            role="agent_human",
            content="Te escribo yo",
            created_at=at,
            metadata={"external_author": {"provider": "zendesk"}},
        ),
        make_message(role="customer", content="", created_at=at, attachments=[{"path": "a"}]),
    ]
    assert format_transcript(messages).split("\n") == [
        "[01/10 10:05] Cliente: ¿Dónde está mi pedido?",
        "[01/10 10:05] Agente IA: Déjame revisarlo.",
        "[01/10 10:05] Equipo de la marca: Te escribo yo",
        "[01/10 10:05] Cliente: (sin texto) [+1 adjunto(s)]",
    ]


def test_handoff_note_has_reason_window_and_transcript() -> None:
    req = HandoffRequest(
        conversation_id=CONVERSATION_ID,
        customer_name="Ana",
        customer_phone="+34600111222",
        customer_email=None,
        customer_ref="auyan:x",
        subject="WhatsApp · Ana",
        reason="Pide hablar con una persona",
        transcript="Cliente: hola",
        window_closes_at=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        attachments=[],
        channel_label="WhatsApp",
    )
    note = format_handoff_note(req)
    assert "Motivo: Pide hablar con una persona" in note
    assert "Ana · +34600111222" in note
    assert "abierta hasta el 01/10 12:00 (hora de Madrid)" in note
    assert note.endswith("Cliente: hola")


# ─── open_handoff ─────────────────────────────────────────────────────────────


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    adapter = MagicMock()
    adapter.open_handoff_ticket = AsyncMock(
        return_value=ExternalTicketRef(provider="zendesk", ticket_id="555", url="https://t/555")
    )
    m: dict[str, Any] = {
        "get_active_handoff": AsyncMock(return_value=None),
        "_load_handoff_target": AsyncMock(return_value=(adapter, object(), "zendesk")),
        "list_recent_messages": AsyncMock(
            return_value=[make_message(role="customer", content="quiero una persona")]
        ),
        "window_state": AsyncMock(
            return_value=WindowState(True, datetime(2026, 10, 2, tzinfo=UTC))
        ),
        "get_end_customer": AsyncMock(
            return_value=make_end_customer(full_name="Ana", phone="+34600111222", email=None)
        ),
        "insert_handoff": AsyncMock(return_value=_handoff()),
        "insert_message": AsyncMock(),
    }
    for name, mock in m.items():
        monkeypatch.setattr(f"{MOD}.{name}", mock)
    monkeypatch.setattr(f"{MOD}.tenant_scope", make_fake_tenant_scope())
    m["adapter"] = adapter
    return m


async def test_open_handoff_creates_ticket_and_row(db: dict[str, Any]) -> None:
    handoff = await open_handoff(
        tenant_id=TENANT_ID, conversation=_wa_conv(), reason="quiere una persona"
    )
    assert handoff.id == HANDOFF_ID
    req: HandoffRequest = db["adapter"].open_handoff_ticket.await_args.args[1]
    assert req.reason == "quiere una persona"
    assert req.customer_phone == "+34600111222"
    assert req.channel_label == "WhatsApp"
    assert "Cliente: quiero una persona" in req.transcript
    assert req.window_closes_at == datetime(2026, 10, 2, tzinfo=UTC)
    insert = db["insert_handoff"].await_args.kwargs
    assert (insert["target"], insert["helpdesk_provider"], insert["external_ticket_id"]) == (
        "helpdesk",
        "zendesk",
        "555",
    )
    system = db["insert_message"].await_args.kwargs
    assert system["role"] == "system"
    assert system["metadata"]["event"] == "handoff_opened"


async def test_second_escalation_reuses_active_handoff(db: dict[str, Any]) -> None:
    db["get_active_handoff"].return_value = _handoff()
    handoff = await open_handoff(tenant_id=TENANT_ID, conversation=_wa_conv(), reason="otra")
    assert handoff.id == HANDOFF_ID
    db["adapter"].open_handoff_ticket.assert_not_awaited()
    db["insert_handoff"].assert_not_awaited()


async def test_closed_window_is_not_announced_as_open(db: dict[str, Any]) -> None:
    db["window_state"].return_value = WindowState(False, datetime(2026, 9, 1, tzinfo=UTC))
    await open_handoff(tenant_id=TENANT_ID, conversation=_wa_conv(), reason="x")
    assert db["adapter"].open_handoff_ticket.await_args.args[1].window_closes_at is None


async def test_no_primary_helpdesk_is_logged_not_raised(
    db: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    db["_load_handoff_target"].side_effect = HandoffUnavailableError("no_primary_helpdesk")
    assert await open_handoff_safe(tenant_id=TENANT_ID, conversation=_wa_conv(), reason="x") is None
    assert any(
        r.message == "handoff_unavailable" and r.levelname == "ERROR" for r in caplog.records
    )


async def test_helpdesk_error_is_logged_not_raised(db: dict[str, Any]) -> None:
    db["adapter"].open_handoff_ticket.side_effect = httpx.ConnectError("down")
    assert await open_handoff_safe(tenant_id=TENANT_ID, conversation=_wa_conv(), reason="x") is None
    db["insert_handoff"].assert_not_awaited()


async def test_load_target_requires_primary_helpdesk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{MOD}.get_primary_integration_for_kind", AsyncMock(return_value=None))
    with pytest.raises(HandoffUnavailableError, match="no_primary_helpdesk"):
        await handoff_mod._load_handoff_target(AsyncMock(), TENANT_ID)


async def test_load_target_requires_handoff_support(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.integrations.chatwoot import ChatwootAdapter  # registra el adapter

    assert not hasattr(ChatwootAdapter, "open_handoff_ticket")
    integration = TenantIntegration(
        id=UUID(int=9),
        tenant_id=TENANT_ID,
        kind="helpdesk",
        provider="chatwoot",
        config={},
        is_active=True,
        is_primary_for_kind=True,
    )
    monkeypatch.setattr(
        f"{MOD}.get_primary_integration_for_kind", AsyncMock(return_value=integration)
    )
    with pytest.raises(HandoffUnavailableError, match="handoff_not_supported:chatwoot"):
        await handoff_mod._load_handoff_target(AsyncMock(), TENANT_ID)


# ─── Enrutado del escalado ────────────────────────────────────────────────────


async def test_whatsapp_escalation_opens_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = AsyncMock(return_value=_handoff())
    monkeypatch.setattr(helpdesk_escalation, "open_handoff_safe", opener)
    ok = await helpdesk_escalation.push_escalation_to_helpdesk_safe(
        tenant_id=TENANT_ID, conversation=_wa_conv(), reason="quiere una persona"
    )
    assert ok is True
    assert opener.await_args.kwargs["reason"] == "quiere una persona"


async def test_l3_gate_does_not_open_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = AsyncMock()
    monkeypatch.setattr(helpdesk_escalation, "open_handoff_safe", opener)
    ok = await helpdesk_escalation.push_escalation_to_helpdesk_safe(
        tenant_id=TENANT_ID,
        conversation=_wa_conv(),
        reason="awaiting_human_approval:9b0c",
    )
    assert ok is False
    opener.assert_not_awaited()


async def test_helpdesk_escalation_does_not_open_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = AsyncMock()
    push = AsyncMock(return_value=True)
    monkeypatch.setattr(helpdesk_escalation, "open_handoff_safe", opener)
    monkeypatch.setattr(helpdesk_escalation, "push_escalation_to_helpdesk", push)
    conv = make_conversation(channel="zendesk", external_id="42")
    assert await helpdesk_escalation.push_escalation_to_helpdesk_safe(
        tenant_id=TENANT_ID, conversation=conv, reason="x"
    )
    opener.assert_not_awaited()


# ─── Zendesk (transport mock) ─────────────────────────────────────────────────


class _ZendeskRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body: Any = request.content
        if request.content and request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            body = json.loads(request.content)
        self.calls.append((request.method, path, body))
        if path.endswith("/users/create_or_update.json"):
            return httpx.Response(200, json={"user": {"id": 777}})
        if path.endswith("/uploads.json"):
            return httpx.Response(201, json={"upload": {"token": "tok-1"}})
        if path.endswith("/tickets.json"):
            return httpx.Response(201, json={"ticket": {"id": 555}})
        if request.method == "GET":
            return httpx.Response(200, json={"ticket": {"requester_id": 777}, "users": []})
        return httpx.Response(200, json={"ticket": {"id": 555}})


def _zendesk(
    recorder: _ZendeskRecorder, **config: Any
) -> tuple[ZendeskAdapter, IntegrationContext]:
    from apps.api.integrations import zendesk as zmod

    adapter = ZendeskAdapter()
    original = zmod.ZendeskClient

    def factory(*args: Any, **kwargs: Any) -> Any:
        kwargs["transport"] = httpx.MockTransport(recorder)
        return original(*args, **kwargs)

    adapter._client = lambda ctx: factory(  # type: ignore[method-assign]
        subdomain=ctx.config["subdomain"], oauth_token="tok"
    )
    ctx = IntegrationContext(
        tenant_id=TENANT_ID,
        credentials={"oauth_token": "tok"},
        config={"subdomain": "acme", "escalation_group_id": "42", **config},
    )
    return adapter, ctx


async def test_zendesk_open_handoff_ticket_request_shape() -> None:
    recorder = _ZendeskRecorder()
    adapter, ctx = _zendesk(recorder)
    req = HandoffRequest(
        conversation_id=CONVERSATION_ID,
        customer_name="Ana",
        customer_phone="+34600111222",
        customer_email=None,
        customer_ref="auyan:cust-1",
        subject="WhatsApp · Ana",
        reason="Pide una persona",
        transcript="[01/10 10:05] Cliente: hola",
        window_closes_at=None,
        attachments=[
            StoredAttachment(
                path="t/c/m/0.jpg",
                mime_type="image/jpeg",
                size=3,
                filename="0.jpg",
                kind="image",
                content=b"abc",
            )
        ],
        channel_label="WhatsApp",
    )
    ref = await adapter.open_handoff_ticket(ctx, req)
    assert ref.ticket_id == "555"
    assert ref.url == "https://acme.zendesk.com/agent/tickets/555"
    user = recorder.calls[0][2]["user"]
    assert user == {
        "name": "Ana",
        "external_id": "auyan:cust-1",
        "role": "end-user",
        "phone": "+34600111222",
    }
    assert recorder.calls[1][1].endswith("/uploads.json") and recorder.calls[1][2] == b"abc"
    ticket = recorder.calls[2][2]["ticket"]
    assert ticket["requester_id"] == 777
    assert ticket["tags"] == ["auyan_handoff", "auyan_whatsapp"]
    assert ticket["group_id"] == 42
    assert ticket["comment"]["public"] is False
    assert ticket["comment"]["uploads"] == ["tok-1"]
    assert "Motivo: Pide una persona" in ticket["comment"]["body"]
    assert "Cliente: hola" in ticket["comment"]["body"]


async def test_zendesk_append_customer_message_is_public_from_requester() -> None:
    recorder = _ZendeskRecorder()
    adapter, ctx = _zendesk(recorder)
    await adapter.append_customer_message(ctx, "555", "sigo esperando", [])
    method, path, body = recorder.calls[-1]
    assert (method, path) == ("PUT", "/api/v2/tickets/555.json")
    assert body["ticket"]["comment"] == {
        "body": "sigo esperando",
        "public": True,
        "author_id": 777,
    }


async def test_zendesk_append_as_internal_note_flag() -> None:
    recorder = _ZendeskRecorder()
    adapter, ctx = _zendesk(recorder, handoff_customer_messages_as_internal_note=True)
    await adapter.append_customer_message(ctx, "555", "hola", [])
    comment = recorder.calls[-1][2]["ticket"]["comment"]
    assert comment == {"body": "💬 Cliente: hola", "public": False}


# ─── Worker con handoff activo ────────────────────────────────────────────────


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from tests.test_inbound_worker import _agent, _job

    wm = "apps.api.services.inbound_worker"
    m: dict[str, Any] = {
        "get_tenant_configuration": AsyncMock(return_value=None),
        "inbound_already_answered": AsyncMock(return_value=False),
        "get_conversation": AsyncMock(return_value=_wa_conv()),
        "get_inbound_message_contents": AsyncMock(return_value=["¿hay novedades?"]),
        "enforce_message_cap": AsyncMock(return_value=None),
        "flush_pending_messages": AsyncMock(return_value=0),
        "get_active_handoff_for_chat": AsyncMock(return_value=_handoff()),
        "forward_customer_message": AsyncMock(return_value=True),
        "close_handoff": AsyncMock(return_value=True),
        "deliver_to_customer": AsyncMock(return_value="delivered"),
        "finalize_agent_resolution": AsyncMock(return_value=True),
        "push_escalation_to_helpdesk_safe": AsyncMock(return_value=True),
    }
    for name, mock in m.items():
        monkeypatch.setattr(f"{wm}.{name}", mock)
    from tests.conftest import make_fake_bootstrap_connection

    monkeypatch.setattr(f"{wm}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{wm}.bootstrap_connection", make_fake_bootstrap_connection())
    monkeypatch.setattr(f"{wm}._usage_recorder", MagicMock())
    m["agent"] = _agent()
    m["job"] = _job(channel="whatsapp")
    return m


async def _run(m: dict[str, Any]) -> str:
    from apps.api.services.inbound_worker import run_inbound_turn

    from tests.conftest import FakeSettings

    return await run_inbound_turn(m["job"], agent_service=m["agent"], settings=FakeSettings())


async def test_active_helpdesk_handoff_forwards_and_skips_graph(worker: dict[str, Any]) -> None:
    assert await _run(worker) == "handoff_forwarded"
    worker["agent"].process_inbound.assert_not_awaited()
    worker["enforce_message_cap"].assert_not_awaited()
    assert worker["forward_customer_message"].await_args.kwargs["content"] == "¿hay novedades?"


async def test_forward_failure_is_visible(worker: dict[str, Any]) -> None:
    worker["forward_customer_message"].return_value = False
    assert await _run(worker) == "handoff_forward_failed"
    worker["agent"].process_inbound.assert_not_awaited()


async def test_device_hold_silences_ai(worker: dict[str, Any]) -> None:
    worker["get_active_handoff_for_chat"].return_value = _handoff(
        target="device",
        helpdesk_provider=None,
        external_ticket_id=None,
        expires_at=datetime.now(UTC) + timedelta(hours=3),
    )
    assert await _run(worker) == "human_hold"
    worker["forward_customer_message"].assert_not_awaited()
    worker["agent"].process_inbound.assert_not_awaited()


async def test_expired_device_hold_closes_and_runs_graph(worker: dict[str, Any]) -> None:
    worker["get_active_handoff_for_chat"].return_value = _handoff(
        target="device",
        helpdesk_provider=None,
        external_ticket_id=None,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert await _run(worker) == "respond"
    assert worker["close_handoff"].await_args.kwargs["reason"] == "device_hold_expired"
    worker["agent"].process_inbound.assert_awaited_once()
