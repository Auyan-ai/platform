"""Tests del nodo `escalate`."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.api.agents.nodes.escalate import make_escalate_node
from tests.conftest import (
    CONVERSATION_ID,
    ESCALATION_ID,
    INBOUND_MSG_ID,
    TENANT_ID,
    make_escalation,
    make_fake_tenant_scope,
)

MODULE = "apps.api.agents.nodes.escalate"


def _state(**overrides) -> dict:
    base = {
        "tenant_id": str(TENANT_ID),
        "conversation_id": str(CONVERSATION_ID),
        "inbound_message_id": str(INBOUND_MSG_ID),
        "escalation_reason": "customer_requested_human",
        "confidence": 0.55,
        "model_used": "claude-sonnet-4-6",
        "langfuse_trace_id": "trace-xyz",
    }
    return {**base, **overrides}


@pytest.mark.asyncio
async def test_creates_escalation_with_reason(fake_deps, monkeypatch) -> None:
    esc = make_escalation(reason="customer_requested_human")
    insert_mock = AsyncMock(return_value=esc)
    update_mock = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", update_mock)
    node = make_escalate_node(fake_deps)

    out = await node(_state())

    assert out["escalation_id"] == str(ESCALATION_ID)
    insert_mock.assert_awaited_once()
    kwargs = insert_mock.await_args.kwargs
    assert kwargs["reason"] == "customer_requested_human"
    assert kwargs["triggered_by_message_id"] is not None


@pytest.mark.asyncio
async def test_sets_conversation_status_to_escalated(fake_deps, monkeypatch) -> None:
    insert_mock = AsyncMock(return_value=make_escalation())
    update_mock = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", update_mock)
    node = make_escalate_node(fake_deps)

    await node(_state())

    args = update_mock.await_args.args
    assert "escalated" in args


@pytest.mark.asyncio
async def test_metadata_includes_confidence_and_trace(fake_deps, monkeypatch) -> None:
    insert_mock = AsyncMock(return_value=make_escalation())
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
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
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    node = make_escalate_node(fake_deps)

    state = _state()
    del state["escalation_reason"]
    await node(state)

    assert insert_mock.await_args.kwargs["reason"] == "unspecified_escalation"
