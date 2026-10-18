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
    monkeypatch.setattr(
        f"{MODULE}.get_open_escalation_for_conversation", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    node = make_handle_error_node(fake_deps)

    out = await node(_state())

    assert out["escalation_id"] == str(ESCALATION_ID)
    reason = insert_mock.await_args.kwargs["reason"]
    assert reason.startswith("agent_error:")
    assert "load_tenant_context: tenant_not_found" in reason


@pytest.mark.asyncio
async def test_new_escalation_sets_escalation_created(fake_deps, monkeypatch) -> None:
    """Al crear una escalación nueva, el parche debe traer escalation_created=True.
    Sin esa señal, el caller post-grafo nunca empuja la nota interna + asignación
    al helpdesk del cliente: los errores de sistema quedaban invisibles para el
    equipo CX (solo aparecían en el dashboard de Auyan)."""
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_open_escalation_for_conversation", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(f"{MODULE}.insert_escalation", AsyncMock(return_value=make_escalation()))
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    node = make_handle_error_node(fake_deps)

    out = await node(_state())

    assert out["escalation_created"] is True
    # La nota interna del helpdesk se redacta desde escalation_reason.
    assert out["escalation_reason"] == "agent_error: load_tenant_context: tenant_not_found"


@pytest.mark.asyncio
async def test_reuses_open_escalation(fake_deps, monkeypatch) -> None:
    """Si la conversación ya tiene una escalación activa (pending/claimed), un
    nuevo error NO crea otra: reusa la existente y escalation_created=False
    (el helpdesk ya recibió su nota; no duplicar). Mismo patrón que escalate."""
    existing = make_escalation(reason="previous")
    insert_mock = AsyncMock()
    status_mock = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_open_escalation_for_conversation",
        AsyncMock(return_value=existing),
    )
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", status_mock)
    node = make_handle_error_node(fake_deps)

    out = await node(_state())

    assert out["escalation_id"] == str(existing.id)
    assert out["escalation_created"] is False
    insert_mock.assert_not_called()
    status_mock.assert_not_called()


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
async def test_persistence_failure_propagates(fake_deps, monkeypatch) -> None:
    """Si no se puede escalar, el fallo se propaga: AgentService lo re-lanza para que
    el turno se reintente en vez de cerrarse sin escalación."""
    insert_mock = AsyncMock(side_effect=RuntimeError("db is down"))
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_open_escalation_for_conversation", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    node = make_handle_error_node(fake_deps)

    with pytest.raises(RuntimeError, match="db is down"):
        await node(_state())


@pytest.mark.asyncio
async def test_falls_back_to_unknown_error(fake_deps, monkeypatch) -> None:
    """Si error está vacío por alguna razón, reason refleja 'unknown_error'."""
    insert_mock = AsyncMock(return_value=make_escalation())
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_open_escalation_for_conversation", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(f"{MODULE}.insert_escalation", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_status", AsyncMock())
    node = make_handle_error_node(fake_deps)

    state = _state()
    state["error"] = None
    await node(state)

    assert "unknown_error" in insert_mock.await_args.kwargs["reason"]
