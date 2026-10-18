"""Worker de turnos inbound (#260): turno completo, reintentos, shutdown y ráfagas."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from apps.api.agents.service import AgentOutcome
from apps.api.db.inbound_jobs import ClaimedInboundJob
from apps.api.services.handoff import APPROVAL_GATE_PREFIX
from apps.api.services.inbound_media import MediaOutcome
from apps.api.services.inbound_worker import (
    InboundJobError,
    InboundWorker,
    retry_delay_seconds,
    run_inbound_turn,
)

from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    INBOUND_MSG_ID,
    TENANT_ID,
    FakeSettings,
    make_conversation,
    make_fake_bootstrap_connection,
    make_fake_tenant_scope,
)

MODULE = "apps.api.services.inbound_worker"
JOB_ID = UUID("88888888-8888-8888-8888-888888888888")
OLDER_MSG_ID = UUID("99999999-9999-9999-9999-999999999999")


def _job(**overrides: Any) -> ClaimedInboundJob:
    data: dict[str, Any] = {
        "id": JOB_ID,
        "tenant_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "inbound_message_id": INBOUND_MSG_ID,
        "end_customer_id": CUSTOMER_ID,
        "channel": "zendesk",
        "attempts": 1,
        "max_attempts": 3,
        "absorbed_message_ids": (),
        "is_retry": False,
        "enqueued_at": datetime.now(UTC),
    }
    data.update(overrides)
    return ClaimedInboundJob(**data)


def _outcome(**overrides: Any) -> AgentOutcome:
    data: dict[str, Any] = {
        "decision": "respond",
        "response_text": "Tu pedido va en camino.",
        "escalation_reason": None,
        "output_message_id": None,
        "escalation_id": None,
        "resolves_on_delivery": True,
        "trace_id": "trace-1",
        "confidence": 0.9,
        "tokens_in": 100,
        "tokens_out": 20,
        "cost_usd": 0.001,
        "model_used": "claude-sonnet-4-6",
        "error": None,
    }
    data.update(overrides)
    return AgentOutcome(**data)


@pytest.fixture
def turn_mocks(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    conversation = make_conversation(channel="zendesk", external_id="42")
    adapter = MagicMock()
    ctx = object()
    mocks: dict[str, Any] = {
        "get_tenant_configuration": AsyncMock(return_value=None),
        "inbound_already_answered": AsyncMock(return_value=False),
        "get_conversation": AsyncMock(return_value=conversation),
        "get_inbound_message_contents": AsyncMock(return_value=["¿dónde está mi pedido?"]),
        "enforce_message_cap": AsyncMock(return_value=None),
        "load_delivery_client": AsyncMock(return_value=(adapter, ctx)),
        "send_agent_reply": AsyncMock(return_value=True),
        "finalize_agent_resolution": AsyncMock(return_value=True),
        "push_escalation_to_helpdesk_safe": AsyncMock(return_value=True),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(f"{MODULE}.{name}", mock)
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.bootstrap_connection", make_fake_bootstrap_connection())
    monkeypatch.setattr(f"{MODULE}._usage_recorder", MagicMock())
    mocks["conversation"] = conversation
    mocks["adapter"] = adapter
    mocks["ctx"] = ctx
    return mocks


def _agent(outcome: AgentOutcome | None = None) -> AsyncMock:
    svc = AsyncMock()
    svc.process_inbound = AsyncMock(return_value=outcome or _outcome())
    return svc


# ─── run_inbound_turn ────────────────────────────────────────────────────────


async def test_turn_runs_graph_delivers_and_resolves(turn_mocks: dict[str, Any]) -> None:
    agent = _agent()
    decision = await run_inbound_turn(_job(), agent_service=agent, settings=FakeSettings())

    assert decision == "respond"
    kwargs = agent.process_inbound.await_args.kwargs
    assert kwargs["inbound_message_id"] == INBOUND_MSG_ID
    assert kwargs["inbound_message_content"] == "¿dónde está mi pedido?"
    assert kwargs["channel"] == "zendesk"
    turn_mocks["send_agent_reply"].assert_awaited_once()
    args = turn_mocks["send_agent_reply"].await_args
    assert args.args[:4] == (
        turn_mocks["adapter"],
        turn_mocks["ctx"],
        "42",
        "Tu pedido va en camino.",
    )
    assert turn_mocks["finalize_agent_resolution"].await_args.kwargs["delivered"] is True
    turn_mocks["push_escalation_to_helpdesk_safe"].assert_not_awaited()


async def test_burst_joins_absorbed_messages_in_one_turn(turn_mocks: dict[str, Any]) -> None:
    turn_mocks["get_inbound_message_contents"].return_value = [
        "hola",
        "mi pedido #1429",
        "¿dónde está?",
    ]
    agent = _agent()
    job = _job(absorbed_message_ids=(OLDER_MSG_ID,))

    await run_inbound_turn(job, agent_service=agent, settings=FakeSettings())

    ids = turn_mocks["get_inbound_message_contents"].await_args.kwargs["message_ids"]
    assert ids == [OLDER_MSG_ID, INBOUND_MSG_ID]
    content = agent.process_inbound.await_args.kwargs["inbound_message_content"]
    assert content == "hola\n\nmi pedido #1429\n\n¿dónde está?"
    assert agent.process_inbound.await_count == 1


async def test_retry_of_already_answered_turn_does_not_reply_twice(
    turn_mocks: dict[str, Any],
) -> None:
    turn_mocks["inbound_already_answered"].return_value = True
    agent = _agent()

    decision = await run_inbound_turn(
        _job(is_retry=True, attempts=2), agent_service=agent, settings=FakeSettings()
    )

    assert decision == "already_answered"
    agent.process_inbound.assert_not_awaited()
    turn_mocks["send_agent_reply"].assert_not_awaited()


async def test_first_attempt_skips_the_answered_check(turn_mocks: dict[str, Any]) -> None:
    await run_inbound_turn(_job(), agent_service=_agent(), settings=FakeSettings())
    turn_mocks["inbound_already_answered"].assert_not_awaited()


async def test_message_cap_skips_graph_and_delivers_cap_outcome(turn_mocks: dict[str, Any]) -> None:
    cap = _outcome(
        decision="escalate",
        response_text="Te paso con el equipo.",
        resolves_on_delivery=False,
        escalation_created=True,
        escalation_reason="message_cap",
    )
    turn_mocks["enforce_message_cap"].return_value = cap
    agent = _agent()

    decision = await run_inbound_turn(_job(), agent_service=agent, settings=FakeSettings())

    assert decision == "escalate"
    agent.process_inbound.assert_not_awaited()
    turn_mocks["send_agent_reply"].assert_awaited_once()
    turn_mocks["finalize_agent_resolution"].assert_not_awaited()
    turn_mocks["push_escalation_to_helpdesk_safe"].assert_awaited_once()


async def test_undelivered_reply_blocks_resolution(turn_mocks: dict[str, Any]) -> None:
    """Credencial mala / helpdesk caído: no se marca resuelta ni se cobra."""
    turn_mocks["send_agent_reply"].return_value = False
    decision = await run_inbound_turn(_job(), agent_service=_agent(), settings=FakeSettings())
    assert decision == "respond:undelivered"
    assert turn_mocks["finalize_agent_resolution"].await_args.kwargs["delivered"] is False


async def test_missing_helpdesk_is_logged_and_not_delivered(
    turn_mocks: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    turn_mocks["load_delivery_client"].return_value = None
    await run_inbound_turn(_job(), agent_service=_agent(), settings=FakeSettings())
    turn_mocks["send_agent_reply"].assert_not_awaited()
    assert turn_mocks["finalize_agent_resolution"].await_args.kwargs["delivered"] is False
    assert any(r.message == "agent_reply_no_helpdesk" for r in caplog.records)


async def test_post_graph_failures_never_raise(turn_mocks: dict[str, Any]) -> None:
    """Tras el grafo la respuesta puede haber salido: nada debe provocar un reintento."""
    turn_mocks["load_delivery_client"].side_effect = RuntimeError("bad creds")
    turn_mocks["finalize_agent_resolution"].side_effect = RuntimeError("db down")
    decision = await run_inbound_turn(_job(), agent_service=_agent(), settings=FakeSettings())
    assert decision == "respond:undelivered"


async def test_escalation_pushes_note_to_helpdesk(turn_mocks: dict[str, Any]) -> None:
    outcome = _outcome(
        decision="escalate",
        response_text="Lo reviso con el equipo.",
        resolves_on_delivery=False,
        escalation_created=True,
        escalation_reason="Pide reembolso fuera de política",
    )
    await run_inbound_turn(_job(), agent_service=_agent(outcome), settings=FakeSettings())
    kwargs = turn_mocks["push_escalation_to_helpdesk_safe"].await_args.kwargs
    assert kwargs["reason"] == "Pide reembolso fuera de política"


async def test_rejected_draft_goes_only_to_the_helpdesk_note(turn_mocks: dict[str, Any]) -> None:
    """#380: el borrador que el supervisor rechazó no se entrega; va en la nota interna."""
    outcome = _outcome(
        decision="escalate",
        response_text=None,
        resolves_on_delivery=False,
        escalation_created=True,
        escalation_reason="supervisor_rejected (structural): plazo sin respaldo",
        rejected_draft="Tu pedido llega mañana.",
    )
    await run_inbound_turn(_job(), agent_service=_agent(outcome), settings=FakeSettings())

    turn_mocks["send_agent_reply"].assert_not_awaited()
    kwargs = turn_mocks["push_escalation_to_helpdesk_safe"].await_args.kwargs
    assert kwargs["reason"] == (
        "supervisor_rejected (structural): plazo sin respaldo\n\n"
        "Borrador rechazado por el supervisor (no se envió al cliente):\n"
        "Tu pedido llega mañana."
    )


def _whatsapp_escalation(
    turn_mocks: dict[str, Any], monkeypatch: pytest.MonkeyPatch, *, delivered: str
) -> AsyncMock:
    turn_mocks["get_conversation"].return_value = make_conversation(
        channel="whatsapp", external_id="chat-1"
    )
    monkeypatch.setattr(
        f"{MODULE}._messaging_pre_graph", AsyncMock(return_value=(None, ["¿cuánto tarda?"]))
    )
    monkeypatch.setattr(f"{MODULE}.deliver_to_customer", AsyncMock(return_value=delivered))
    send_fixed = AsyncMock()
    monkeypatch.setattr(f"{MODULE}._send_fixed_message", send_fixed)
    return send_fixed


async def test_whatsapp_escalation_without_reply_sends_fixed_ack(
    turn_mocks: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """En un chat nadie ve un ticket `pending`: el cliente recibe un acuse fijo."""
    send_fixed = _whatsapp_escalation(turn_mocks, monkeypatch, delivered="delivered")
    outcome = _outcome(
        decision="escalate",
        response_text=None,
        resolves_on_delivery=False,
        escalation_created=True,
        escalation_reason="low_confidence: 0.50 < threshold 0.65",
    )
    await run_inbound_turn(
        _job(channel="whatsapp"), agent_service=_agent(outcome), settings=FakeSettings()
    )
    turn_mocks["push_escalation_to_helpdesk_safe"].assert_awaited_once()
    assert send_fixed.await_args.args[2] == "escalation_ack"


async def test_whatsapp_escalation_with_delivered_reply_sends_no_ack(
    turn_mocks: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    send_fixed = _whatsapp_escalation(turn_mocks, monkeypatch, delivered="delivered")
    outcome = _outcome(
        decision="escalate",
        response_text="Te paso con el equipo.",
        resolves_on_delivery=False,
        escalation_created=True,
        escalation_reason="Pide hablar con una persona",
    )
    await run_inbound_turn(
        _job(channel="whatsapp"), agent_service=_agent(outcome), settings=FakeSettings()
    )
    send_fixed.assert_not_awaited()


async def test_whatsapp_approval_gate_sends_no_ack(
    turn_mocks: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    send_fixed = _whatsapp_escalation(turn_mocks, monkeypatch, delivered="delivered")
    outcome = _outcome(
        decision="escalate",
        response_text=None,
        resolves_on_delivery=False,
        escalation_created=True,
        escalation_reason=f"{APPROVAL_GATE_PREFIX}cancel_order",
    )
    await run_inbound_turn(
        _job(channel="whatsapp"), agent_service=_agent(outcome), settings=FakeSettings()
    )
    send_fixed.assert_not_awaited()


async def test_whatsapp_escalation_retries_handoff_when_escalation_existed(
    turn_mocks: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """s81: un handoff fallido dejaba la escalación abierta y ningún turno lo reintentaba."""
    send_fixed = _whatsapp_escalation(turn_mocks, monkeypatch, delivered="delivered")
    outcome = _outcome(
        decision="escalate",
        response_text=None,
        resolves_on_delivery=False,
        escalation_id="esc-1",
        escalation_created=False,
        escalation_reason="customer_requested_human",
    )
    await run_inbound_turn(
        _job(channel="whatsapp"), agent_service=_agent(outcome), settings=FakeSettings()
    )
    kwargs = turn_mocks["push_escalation_to_helpdesk_safe"].await_args.kwargs
    assert kwargs["reason"] == "customer_requested_human"
    assert send_fixed.await_args.args[2] == "escalation_ack"


async def test_whatsapp_failed_turn_already_escalated_retries_handoff_and_acks(
    turn_mocks: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#362: un turno que falla con la escalación ya abierta se trata igual que un escalado:
    se reintenta el handoff y el cliente recibe el acuse (antes no recibía nada)."""
    send_fixed = _whatsapp_escalation(turn_mocks, monkeypatch, delivered="delivered")
    outcome = _outcome(
        decision="error",
        response_text=None,
        resolves_on_delivery=False,
        escalation_id="esc-1",
        escalation_created=False,
        escalation_reason="agent_error: respond: RuntimeError: boom",
        error="respond: RuntimeError: boom",
    )
    await run_inbound_turn(
        _job(channel="whatsapp"), agent_service=_agent(outcome), settings=FakeSettings()
    )
    kwargs = turn_mocks["push_escalation_to_helpdesk_safe"].await_args.kwargs
    assert kwargs["reason"] == "agent_error: respond: RuntimeError: boom"
    assert send_fixed.await_args.args[2] == "escalation_ack"


async def test_helpdesk_existing_escalation_is_not_pushed_again(
    turn_mocks: dict[str, Any],
) -> None:
    outcome = _outcome(
        decision="escalate",
        response_text="Lo reviso con el equipo.",
        resolves_on_delivery=False,
        escalation_created=False,
        escalation_reason="Pide reembolso fuera de política",
    )
    await run_inbound_turn(_job(), agent_service=_agent(outcome), settings=FakeSettings())
    turn_mocks["push_escalation_to_helpdesk_safe"].assert_not_awaited()


async def test_helpdesk_escalation_sends_no_fixed_ack(
    turn_mocks: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    send_fixed = AsyncMock()
    monkeypatch.setattr(f"{MODULE}._send_fixed_message", send_fixed)
    outcome = _outcome(
        decision="escalate",
        response_text=None,
        resolves_on_delivery=False,
        escalation_created=True,
        escalation_reason="Pide reembolso fuera de política",
    )
    await run_inbound_turn(_job(), agent_service=_agent(outcome), settings=FakeSettings())
    send_fixed.assert_not_awaited()


async def test_missing_conversation_raises_for_retry(turn_mocks: dict[str, Any]) -> None:
    turn_mocks["get_conversation"].return_value = None
    with pytest.raises(InboundJobError):
        await run_inbound_turn(_job(), agent_service=_agent(), settings=FakeSettings())


# ─── InboundWorker ───────────────────────────────────────────────────────────


def test_retry_backoff_grows_and_caps() -> None:
    assert [retry_delay_seconds(n) for n in (1, 2, 3, 9)] == [30, 120, 300, 300]


@pytest.fixture
def worker_db(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "claim_next_inbound_job": AsyncMock(return_value=None),
        "complete_inbound_job": AsyncMock(),
        "fail_inbound_job": AsyncMock(return_value="pending"),
        "release_inbound_job": AsyncMock(),
        "extend_inbound_job_lease": AsyncMock(),
        "run_inbound_turn": AsyncMock(return_value="respond"),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(f"{MODULE}.{name}", mock)
    monkeypatch.setattr(f"{MODULE}.bootstrap_connection", make_fake_bootstrap_connection())
    return mocks


def _worker(**kw: Any) -> InboundWorker:
    return InboundWorker(agent_service=AsyncMock(), settings=FakeSettings(), **kw)  # type: ignore[arg-type]


async def test_run_once_with_empty_queue(worker_db: dict[str, AsyncMock]) -> None:
    assert await _worker().run_once() is False
    worker_db["run_inbound_turn"].assert_not_awaited()


async def test_run_once_completes_job(worker_db: dict[str, AsyncMock]) -> None:
    worker_db["claim_next_inbound_job"].return_value = _job()
    assert await _worker(lease_seconds=90).run_once() is True
    assert worker_db["claim_next_inbound_job"].await_args.kwargs["lease_seconds"] == 90
    kwargs = worker_db["complete_inbound_job"].await_args.kwargs
    assert kwargs == {"job_id": JOB_ID, "decision": "respond"}
    worker_db["fail_inbound_job"].assert_not_awaited()


async def test_turn_exception_schedules_retry_with_backoff(
    worker_db: dict[str, AsyncMock], caplog: pytest.LogCaptureFixture
) -> None:
    worker_db["claim_next_inbound_job"].return_value = _job(attempts=2)
    worker_db["run_inbound_turn"].side_effect = RuntimeError("anthropic 529")

    await _worker().run_once()

    kwargs = worker_db["fail_inbound_job"].await_args.kwargs
    assert kwargs["job_id"] == JOB_ID
    assert kwargs["retry_in_seconds"] == 120
    assert "anthropic 529" in kwargs["error"]
    worker_db["complete_inbound_job"].assert_not_awaited()
    assert any(r.message == "inbound_job_retry_scheduled" for r in caplog.records)


async def test_exhausted_retries_are_logged_as_error(
    worker_db: dict[str, AsyncMock], caplog: pytest.LogCaptureFixture
) -> None:
    worker_db["claim_next_inbound_job"].return_value = _job(attempts=3)
    worker_db["run_inbound_turn"].side_effect = RuntimeError("boom")
    worker_db["fail_inbound_job"].return_value = "failed"

    await _worker().run_once()

    errors = [r for r in caplog.records if r.message == "inbound_job_failed"]
    assert errors and errors[0].levelname == "ERROR"


async def test_shutdown_releases_running_job(worker_db: dict[str, AsyncMock]) -> None:
    started = asyncio.Event()

    async def _slow_turn(*_: Any, **__: Any) -> str:
        started.set()
        await asyncio.sleep(60)
        return "respond"

    worker_db["claim_next_inbound_job"].side_effect = [_job(), None, None, None]
    worker_db["run_inbound_turn"].side_effect = _slow_turn
    worker = _worker(concurrency=1, poll_interval_seconds=0.01)
    worker.start()
    await asyncio.wait_for(started.wait(), timeout=2)
    await worker.stop()

    worker_db["release_inbound_job"].assert_awaited_once()
    assert worker_db["release_inbound_job"].await_args.kwargs == {"job_id": JOB_ID}
    worker_db["complete_inbound_job"].assert_not_awaited()


async def test_heartbeat_extends_lease_during_long_turn(worker_db: dict[str, AsyncMock]) -> None:
    async def _slow_turn(*_: Any, **__: Any) -> str:
        await asyncio.sleep(2.2)
        return "respond"

    worker_db["claim_next_inbound_job"].return_value = _job()
    worker_db["run_inbound_turn"].side_effect = _slow_turn

    await _worker(lease_seconds=3).run_once()  # heartbeat cada 1 s

    assert worker_db["extend_inbound_job_lease"].await_count >= 2
    worker_db["complete_inbound_job"].assert_awaited_once()


async def test_notify_wakes_idle_worker(worker_db: dict[str, AsyncMock]) -> None:
    done = asyncio.Event()
    calls = {"n": 0}

    async def _claim(*_: Any, **__: Any) -> ClaimedInboundJob | None:
        calls["n"] += 1
        return _job() if calls["n"] == 2 else None

    async def _turn(*_: Any, **__: Any) -> str:
        done.set()
        return "respond"

    worker_db["claim_next_inbound_job"].side_effect = _claim
    worker_db["run_inbound_turn"].side_effect = _turn
    worker = _worker(concurrency=1, poll_interval_seconds=30)
    worker.start()
    await asyncio.sleep(0.05)  # primer claim vacío → a dormir (sondeo de 30 s)
    worker.notify()
    await asyncio.wait_for(done.wait(), timeout=2)
    await worker.stop()


async def test_claim_errors_do_not_kill_the_loop(worker_db: dict[str, AsyncMock]) -> None:
    done = asyncio.Event()

    async def _turn(*_: Any, **__: Any) -> str:
        done.set()
        return "respond"

    worker_db["claim_next_inbound_job"].side_effect = [
        ConnectionError("pooler"),
        _job(),
        None,
        None,
    ]
    worker_db["run_inbound_turn"].side_effect = _turn
    worker = _worker(concurrency=1, poll_interval_seconds=0.01)
    worker.start()
    await asyncio.wait_for(done.wait(), timeout=2)
    await worker.stop()


# ─── WhatsApp: pendientes antes del grafo + entrega con ventana ────────────────


@pytest.fixture
def wa_mocks(turn_mocks: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    conversation = make_conversation(channel="whatsapp", external_id="zconv-1")
    turn_mocks["get_conversation"].return_value = conversation
    order: list[str] = []
    flush = AsyncMock(side_effect=lambda *a, **k: order.append("flush") or 1)
    deliver = AsyncMock(return_value="delivered")
    handoff = AsyncMock(return_value=None)
    media = AsyncMock(return_value=MediaOutcome(texts=["¿dónde está mi pedido?"]))
    monkeypatch.setattr(f"{MODULE}.process_inbound_media", media)
    monkeypatch.setattr(f"{MODULE}.flush_pending_messages", flush)
    monkeypatch.setattr(f"{MODULE}.deliver_to_customer", deliver)
    monkeypatch.setattr(f"{MODULE}.get_active_handoff_for_chat", handoff)
    turn_mocks.update(
        flush=flush,
        deliver=deliver,
        order=order,
        wa_conversation=conversation,
        handoff=handoff,
        media=media,
    )
    return turn_mocks


async def test_whatsapp_flushes_pending_before_the_graph(wa_mocks: dict[str, Any]) -> None:
    agent = _agent()
    agent.process_inbound.side_effect = lambda **_: wa_mocks["order"].append("graph") or _outcome()
    await run_inbound_turn(_job(channel="whatsapp"), agent_service=agent, settings=FakeSettings())
    assert wa_mocks["order"] == ["flush", "graph"]


async def test_whatsapp_reply_goes_through_window_aware_delivery(
    wa_mocks: dict[str, Any],
) -> None:
    msg_id = "aaaaaaaa-0000-0000-0000-000000000001"
    agent = _agent(_outcome(output_message_id=msg_id))
    decision = await run_inbound_turn(
        _job(channel="whatsapp"), agent_service=agent, settings=FakeSettings()
    )
    assert decision == "respond"
    kwargs = wa_mocks["deliver"].await_args.kwargs
    assert kwargs["message_id"] == UUID(msg_id)
    assert kwargs["content"] == "Tu pedido va en camino."
    wa_mocks["send_agent_reply"].assert_not_awaited()
    assert wa_mocks["finalize_agent_resolution"].await_args.kwargs["delivered"] is True


async def test_whatsapp_pending_reply_is_undelivered(wa_mocks: dict[str, Any]) -> None:
    wa_mocks["deliver"].return_value = "pending_window"
    decision = await run_inbound_turn(
        _job(channel="whatsapp"), agent_service=_agent(), settings=FakeSettings()
    )
    assert decision == "respond:undelivered"
    assert wa_mocks["finalize_agent_resolution"].await_args.kwargs["delivered"] is False


async def test_helpdesk_turn_does_not_flush(turn_mocks: dict[str, Any], monkeypatch) -> None:
    flush = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.flush_pending_messages", flush)
    await run_inbound_turn(_job(), agent_service=_agent(), settings=FakeSettings())
    flush.assert_not_awaited()
