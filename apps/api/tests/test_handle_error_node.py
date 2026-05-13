"""Tests del nodo `handle_error` — el fail-safe del grafo."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.api.agents.nodes.handle_error import make_handle_error_node
from tests.conftest import (
    CONVERSATION_ID,
    ESCALATION_ID,
    INBOUND_MSG_ID,
    TENANT_ID,
    make_escalation,
    make_fake_tenant_scope,
)

MODULE = "apps.api.agents.nodes.handle_error"


def _state(**overrides) -> dict:
    base = {
        "tenant_id": str(TENANT_ID),
        "conversation_id": str(CONVERSATION_ID),
        "inbound_message_id": str(INBOUND_MSG_ID),
        "error": "load_tenant_context: tenant_not_found",
        "langfuse_trace_id": "trace-err",
    }
    return {**base, **overrides}


@pytest.mark.asyncio
async def test_escalates_with_agent_error_prefix(fake_deps, monkeypatch) -> None:
    insert_mock = AsyncMock(return_value=make_escalation())
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    node = make_handle_error_node(fake_deps)

    out = await node(_state())

    assert out["escalation_id"] == str(ESCALATION_ID)
    reason = insert_mock.await_args.kwargs["reason"]
    assert reason.startswith("agent_error:")
    assert "load_tenant_context: tenant_not_found" in reason


@pytest.mark.asyncio
async def test_no_context_just_logs(fake_deps, monkeypatch) -> None:
    """Sin tenant/conversation no podemos persistir — log only."""
    insert_mock = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    node = make_handle_error_node(fake_deps)

    out = await node({"error": "boot_failure"})

    assert out == {}
    insert_mock.assert_not_called()


@pytest.mark.asyncio
async def test_resilient_to_persistence_failure(fake_deps, monkeypatch) -> None:
    """Si la persistencia de la escalación falla, NO propaga — el trace ya quedó."""
    insert_mock = AsyncMock(side_effect=RuntimeError("db is down"))
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    node = make_handle_error_node(fake_deps)

    out = await node(_state())

    assert out == {}


@pytest.mark.asyncio
async def test_falls_back_to_unknown_error(fake_deps, monkeypatch) -> None:
    """Si error está vacío por alguna razón, reason refleja 'unknown_error'."""
    insert_mock = AsyncMock(return_value=make_escalation())
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    node = make_handle_error_node(fake_deps)

    state = _state()
    state["error"] = None
    await node(state)

    assert "unknown_error" in insert_mock.await_args.kwargs["reason"]
