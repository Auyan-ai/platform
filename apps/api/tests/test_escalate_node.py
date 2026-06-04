"""Tests del nodo `escalate`."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apps.api.agents.nodes.escalate import make_escalate_node

from tests.conftest import (
    CONVERSATION_ID,
    ESCALATION_ID,
    INBOUND_MSG_ID,
    OUTBOUND_MSG_ID,
    TENANT_ID,
    make_escalation,
    make_fake_tenant_scope,
    make_message,
)

MODULE = "apps.api.agents.nodes.escalate"


def _state(**overrides) -> dict:
    base = {
        "tenant_id": str(TENANT_ID),
        "conversation_id": str(CONVERSATION_ID),
        "inbound_message_id": str(INBOUND_MSG_ID),
        "escalation_reason": "customer_requested_human",
        "agent_response": "Te paso con un agente ahora mismo.",
        "confidence": 0.55,
        "model_used": "claude-sonnet-4-6",
        "langfuse_trace_id": "trace-xyz",
    }
    return {**base, **overrides}


def _mock_no_existing(monkeypatch) -> None:
    monkeypatch.setattr(
        f"{MODULE}.get_open_escalation_for_conversation", AsyncMock(return_value=None)
    )


@pytest.mark.asyncio
async def test_creates_escalation_with_reason(fake_deps, monkeypatch) -> None:
    esc = make_escalation(reason="customer_requested_human")
    insert_mock = AsyncMock(return_value=esc)
    out_msg = make_message(id=OUTBOUND_MSG_ID, role="agent_ai", direction="outbound")
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    _mock_no_existing(monkeypatch)
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    monkeypatch.setattr(f"{MODULE}.insert_message", AsyncMock(return_value=out_msg))
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_escalate_node(fake_deps)

    out = await node(_state())

    assert out["escalation_id"] == str(ESCALATION_ID)
    insert_mock.assert_awaited_once()
    kwargs = insert_mock.await_args.kwargs
    assert kwargs["reason"] == "customer_requested_human"
    assert kwargs["triggered_by_message_id"] is not None


@pytest.mark.asyncio
async def test_sets_conversation_status_to_escalated(fake_deps, monkeypatch) -> None:
    update_mock = AsyncMock()
    out_msg = make_message(id=OUTBOUND_MSG_ID, role="agent_ai", direction="outbound")
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    _mock_no_existing(monkeypatch)
    monkeypatch.setattr(f"{MODULE}.insert_escalation", AsyncMock(return_value=make_escalation()))
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", update_mock)
    monkeypatch.setattr(f"{MODULE}.insert_message", AsyncMock(return_value=out_msg))
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_escalate_node(fake_deps)

    await node(_state())

    args = update_mock.await_args.args
    assert "escalated" in args


@pytest.mark.asyncio
async def test_metadata_includes_confidence_and_trace(fake_deps, monkeypatch) -> None:
    insert_mock = AsyncMock(return_value=make_escalation())
    out_msg = make_message(id=OUTBOUND_MSG_ID, role="agent_ai", direction="outbound")
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    _mock_no_existing(monkeypatch)
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    monkeypatch.setattr(f"{MODULE}.insert_message", AsyncMock(return_value=out_msg))
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_escalate_node(fake_deps)

    await node(_state())

    metadata = insert_mock.await_args.kwargs["metadata"]
    assert metadata["confidence"] == 0.55
    assert metadata["langfuse_trace_id"] == "trace-xyz"
    assert metadata["model_used"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_falls_back_to_unspecified_reason(fake_deps, monkeypatch) -> None:
    """Si por algún motivo no hay escalation_reason, no rompe — usa fallback."""
    insert_mock = AsyncMock(return_value=make_escalation())
    out_msg = make_message(id=OUTBOUND_MSG_ID, role="agent_ai", direction="outbound")
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    _mock_no_existing(monkeypatch)
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    monkeypatch.setattr(f"{MODULE}.insert_message", AsyncMock(return_value=out_msg))
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_escalate_node(fake_deps)

    state = _state()
    del state["escalation_reason"]
    await node(state)

    assert insert_mock.await_args.kwargs["reason"] == "unspecified_escalation"


@pytest.mark.asyncio
async def test_persists_agent_response_as_outbound_message(fake_deps, monkeypatch) -> None:
    """El mensaje de handoff del agente debe guardarse en la DB."""
    out_msg = make_message(id=OUTBOUND_MSG_ID, role="agent_ai", direction="outbound")
    insert_msg_mock = AsyncMock(return_value=out_msg)
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    _mock_no_existing(monkeypatch)
    monkeypatch.setattr(f"{MODULE}.insert_escalation", AsyncMock(return_value=make_escalation()))
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    monkeypatch.setattr(f"{MODULE}.insert_message", insert_msg_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_escalate_node(fake_deps)

    out = await node(_state())

    insert_msg_mock.assert_awaited_once()
    kwargs = insert_msg_mock.await_args.kwargs
    assert kwargs["role"] == "agent_ai"
    assert kwargs["direction"] == "outbound"
    assert kwargs["content"] == "Te paso con un agente ahora mismo."
    assert out["output_message_id"] == str(OUTBOUND_MSG_ID)


@pytest.mark.asyncio
async def test_pending_approval_uses_contextual_gate_message(fake_deps, monkeypatch) -> None:
    """Gate L3 sin agent_response propio: mensaje cálido y contextual por skill,
    no la plantilla robótica ('requiere revisión por parte de nuestro equipo')."""
    out_msg = make_message(id=OUTBOUND_MSG_ID, role="agent_ai", direction="outbound")
    insert_msg_mock = AsyncMock(return_value=out_msg)
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    _mock_no_existing(monkeypatch)
    monkeypatch.setattr(f"{MODULE}.insert_escalation", AsyncMock(return_value=make_escalation()))
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    monkeypatch.setattr(f"{MODULE}.insert_message", insert_msg_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_escalate_node(fake_deps)

    out = await node(
        _state(
            agent_response="",
            pending_approval_id="ap-123",
            pending_approval_skill_slug="shopify.update_shipping_address",
        )
    )

    content = insert_msg_mock.await_args.kwargs["content"]
    assert "dirección de tu pedido" in content
    assert "requiere revisión por parte de nuestro equipo" not in content
    # El mensaje del gate se expone para que el webhook lo entregue al cliente.
    assert out["agent_response"] == content


@pytest.mark.asyncio
async def test_repeat_pending_approval_uses_waiting_message(fake_deps, monkeypatch) -> None:
    """Gate L3 repetido (el cliente vuelve a escribir esperando): mensaje de espera
    ('sigue en revisión'), no el gate de cero ('lo paso a mi equipo')."""
    out_msg = make_message(id=OUTBOUND_MSG_ID, role="agent_ai", direction="outbound")
    insert_msg_mock = AsyncMock(return_value=out_msg)
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    _mock_no_existing(monkeypatch)
    monkeypatch.setattr(f"{MODULE}.insert_escalation", AsyncMock(return_value=make_escalation()))
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    monkeypatch.setattr(f"{MODULE}.insert_message", insert_msg_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_escalate_node(fake_deps)

    await node(
        _state(
            agent_response="",
            pending_approval_id="ap-123",
            pending_approval_skill_slug="shopify.update_shipping_address",
            pending_approval_is_repeat=True,
        )
    )

    content = insert_msg_mock.await_args.kwargs["content"]
    assert "sigue en revisión" in content
    assert "Lo paso a mi equipo" not in content


@pytest.mark.asyncio
async def test_no_message_inserted_when_response_empty(fake_deps, monkeypatch) -> None:
    """Si no hay agent_response, no se inserta mensaje — no rompe."""
    insert_msg_mock = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    _mock_no_existing(monkeypatch)
    monkeypatch.setattr(f"{MODULE}.insert_escalation", AsyncMock(return_value=make_escalation()))
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    monkeypatch.setattr(f"{MODULE}.insert_message", insert_msg_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_escalate_node(fake_deps)

    out = await node(_state(agent_response=""))

    insert_msg_mock.assert_not_awaited()
    assert "output_message_id" not in out


@pytest.mark.asyncio
async def test_reuses_existing_open_escalation(fake_deps, monkeypatch) -> None:
    """Si ya hay una escalación activa, no crea una nueva."""
    existing_esc = make_escalation(reason="customer_requested_human", status="pending")
    insert_mock = AsyncMock()
    update_status_mock = AsyncMock()
    out_msg = make_message(id=OUTBOUND_MSG_ID, role="agent_ai", direction="outbound")
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_open_escalation_for_conversation",
        AsyncMock(return_value=existing_esc),
    )
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", update_status_mock)
    monkeypatch.setattr(f"{MODULE}.insert_message", AsyncMock(return_value=out_msg))
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_escalate_node(fake_deps)

    out = await node(_state())

    insert_mock.assert_not_awaited()
    update_status_mock.assert_not_awaited()
    assert out["escalation_id"] == str(ESCALATION_ID)


@pytest.mark.asyncio
async def test_claimed_escalation_also_reused(fake_deps, monkeypatch) -> None:
    """Una escalación ya tomada por un agente (claimed) tampoco genera duplicado."""
    existing_esc = make_escalation(reason="customer_requested_human", status="claimed")
    insert_mock = AsyncMock()
    out_msg = make_message(id=OUTBOUND_MSG_ID, role="agent_ai", direction="outbound")
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_open_escalation_for_conversation",
        AsyncMock(return_value=existing_esc),
    )
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    monkeypatch.setattr(f"{MODULE}.insert_message", AsyncMock(return_value=out_msg))
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_escalate_node(fake_deps)

    await node(_state())

    insert_mock.assert_not_awaited()
