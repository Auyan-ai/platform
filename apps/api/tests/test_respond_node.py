"""Tests del nodo `respond`."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apps.api.agents.nodes.respond import make_respond_node

from tests.conftest import (
    CONVERSATION_ID,
    OUTBOUND_MSG_ID,
    TENANT_ID,
    make_fake_tenant_scope,
    make_message,
)

MODULE = "apps.api.agents.nodes.respond"


def _state(**overrides) -> dict:
    base = {
        "tenant_id": str(TENANT_ID),
        "conversation_id": str(CONVERSATION_ID),
        "agent_response": "Los envíos tardan 3-5 días hábiles.",
        "model_used": "claude-sonnet-4-6",
        "tokens_in": 120,
        "tokens_out": 35,
        "cost_usd": 0.00086,
        "confidence": 0.92,
        "langfuse_trace_id": "trace-abc",
    }
    return {**base, **overrides}


@pytest.mark.asyncio
async def test_happy_path_persists_message(fake_deps, monkeypatch) -> None:
    out_msg = make_message(
        id=OUTBOUND_MSG_ID, role="agent_ai", direction="outbound", content="x"
    )
    insert_mock = AsyncMock(return_value=out_msg)
    update_mock = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_message", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", update_mock)
    node = make_respond_node(fake_deps)

    out = await node(_state())

    assert out["output_message_id"] == str(OUTBOUND_MSG_ID)
    assert "error" not in out
    insert_mock.assert_awaited_once()
    update_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolves_on_delivery_when_not_awaiting(fake_deps, monkeypatch) -> None:
    """Respuesta terminal (no pide más datos) → resuelve, pero solo al entregarse:
    el nodo NO marca `resolved` ni registra billing (auditoría s71 #3)."""
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.insert_message", AsyncMock(return_value=make_message(id=OUTBOUND_MSG_ID))
    )
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_respond_node(fake_deps)

    out = await node(_state(awaiting_customer_reply=False))

    assert out["resolves_on_delivery"] is True
    assert "conversation_resolved" not in out


@pytest.mark.asyncio
async def test_does_not_resolve_when_awaiting_customer(fake_deps, monkeypatch) -> None:
    """Pregunta de clarificación (awaiting_customer_reply) → no resuelve."""
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.insert_message", AsyncMock(return_value=make_message(id=OUTBOUND_MSG_ID))
    )
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_respond_node(fake_deps)

    out = await node(_state(awaiting_customer_reply=True))

    assert out["resolves_on_delivery"] is False


def test_respond_node_does_not_touch_resolution_state() -> None:
    """Guard de regresión: el nodo no importa las queries de resolución/billing."""
    import apps.api.agents.nodes.respond as respond_module

    assert not hasattr(respond_module, "mark_conversation_resolved")
    assert not hasattr(respond_module, "insert_resolution_event")


@pytest.mark.asyncio
async def test_message_metadata_includes_telemetry(fake_deps, monkeypatch) -> None:
    """metadata del mensaje debe traer trace_id, model, tokens, cost, confidence."""
    insert_mock = AsyncMock(return_value=make_message(id=OUTBOUND_MSG_ID))
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_message", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_respond_node(fake_deps)

    await node(_state())

    metadata = insert_mock.await_args.kwargs["metadata"]
    assert metadata["langfuse_trace_id"] == "trace-abc"
    assert metadata["model"] == "claude-sonnet-4-6"
    assert metadata["prompt_tokens"] == 120
    assert metadata["completion_tokens"] == 35
    assert metadata["cost_usd"] == 0.00086
    assert metadata["confidence"] == 0.92


@pytest.mark.asyncio
async def test_empty_response_sets_error(fake_deps, monkeypatch) -> None:
    """reason debió validar esto; defense-in-depth en respond."""
    insert_mock = AsyncMock()
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_message", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_respond_node(fake_deps)

    out = await node(_state(agent_response="   "))

    assert out["error"] == "respond_without_text"
    insert_mock.assert_not_called()


@pytest.mark.asyncio
async def test_inserts_with_correct_role_and_direction(fake_deps, monkeypatch) -> None:
    """El mensaje siempre se persiste como (agent_ai, outbound)."""
    insert_mock = AsyncMock(return_value=make_message(id=OUTBOUND_MSG_ID))
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_message", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_respond_node(fake_deps)

    await node(_state())

    kwargs = insert_mock.await_args.kwargs
    assert kwargs["role"] == "agent_ai"
    assert kwargs["direction"] == "outbound"
