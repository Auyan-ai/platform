"""Tests del nodo `load_conversation`."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apps.api.agents.nodes.load_conversation import (
    _format_known_facts,
    make_load_conversation_node,
)

from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    TENANT_ID,
    make_conversation,
    make_end_customer,
    make_fake_tenant_scope,
    make_message,
)

MODULE = "apps.api.agents.nodes.load_conversation"


def _state() -> dict:
    return {
        "tenant_id": str(TENANT_ID),
        "conversation_id": str(CONVERSATION_ID),
        "end_customer_id": str(CUSTOMER_ID),
    }


@pytest.mark.asyncio
async def test_happy_path(fake_deps, monkeypatch) -> None:
    msg1 = make_message(content="primer mensaje")
    msg2 = make_message(content="segundo mensaje")
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation())
    )
    monkeypatch.setattr(
        f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer())
    )
    monkeypatch.setattr(
        f"{MODULE}.get_recent_messages", AsyncMock(return_value=[msg1, msg2])
    )
    node = make_load_conversation_node(fake_deps)

    out = await node(_state())

    assert "error" not in out
    assert len(out["conversation_history"]) == 2
    assert out["conversation_history"][0]["content"] == "primer mensaje"
    assert out["end_customer"]["email"] == "juan@example.com"


@pytest.mark.asyncio
async def test_known_facts_built_from_read_outputs(fake_deps, monkeypatch) -> None:
    """Los outputs de lectura previos se inyectan como bloque known_facts."""
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation())
    )
    monkeypatch.setattr(
        f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer())
    )
    monkeypatch.setattr(f"{MODULE}.get_recent_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        f"{MODULE}.get_recent_read_outputs_for_conversation",
        AsyncMock(return_value=[("shopify.get_order_status", {"order_number": "#1278", "fulfillment_status": None})]),
    )
    monkeypatch.setattr(
        f"{MODULE}.get_approved_actions_for_conversation", AsyncMock(return_value=[])
    )
    node = make_load_conversation_node(fake_deps)

    out = await node(_state())

    assert "shopify.get_order_status" in out["known_facts"]
    assert "#1278" in out["known_facts"]
    assert "NO vuelvas a consultarlos" in out["known_facts"]


@pytest.mark.asyncio
async def test_known_facts_includes_completed_actions(fake_deps, monkeypatch) -> None:
    """Las acciones L3 ya aprobadas se inyectan con la instrucción de no re-disparar."""
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation())
    )
    monkeypatch.setattr(
        f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer())
    )
    monkeypatch.setattr(f"{MODULE}.get_recent_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        f"{MODULE}.get_recent_read_outputs_for_conversation", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        f"{MODULE}.get_approved_actions_for_conversation",
        AsyncMock(return_value=[("shopify.update_shipping_address", {"city": "Madrid"})]),
    )
    node = make_load_conversation_node(fake_deps)

    out = await node(_state())

    assert "shopify.update_shipping_address" in out["known_facts"]
    assert "NO vuelvas a llamar estas skills" in out["known_facts"]


def test_format_known_facts_empty_is_empty_string() -> None:
    assert _format_known_facts([], []) == ""


@pytest.mark.asyncio
async def test_conversation_not_found(fake_deps, monkeypatch) -> None:
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_conversation", AsyncMock(return_value=None))
    monkeypatch.setattr(
        f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer())
    )
    monkeypatch.setattr(f"{MODULE}.get_recent_messages", AsyncMock(return_value=[]))
    node = make_load_conversation_node(fake_deps)

    out = await node(_state())

    assert out["error"] == "conversation_not_found"


@pytest.mark.asyncio
async def test_end_customer_not_found(fake_deps, monkeypatch) -> None:
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation())
    )
    monkeypatch.setattr(f"{MODULE}.get_end_customer", AsyncMock(return_value=None))
    monkeypatch.setattr(f"{MODULE}.get_recent_messages", AsyncMock(return_value=[]))
    node = make_load_conversation_node(fake_deps)

    out = await node(_state())

    assert out["error"] == "end_customer_not_found"


@pytest.mark.asyncio
async def test_uses_history_limit_from_settings(fake_deps, monkeypatch) -> None:
    """history_limit del Settings se pasa a get_recent_messages."""
    fake_deps.settings.history_limit = 7
    get_msgs_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation())
    )
    monkeypatch.setattr(
        f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer())
    )
    monkeypatch.setattr(f"{MODULE}.get_recent_messages", get_msgs_mock)
    node = make_load_conversation_node(fake_deps)

    await node(_state())

    # El call positional/keyword puede variar — chequeamos por kwargs
    call = get_msgs_mock.await_args
    assert call.kwargs.get("limit") == 7 or 7 in call.args


@pytest.mark.asyncio
async def test_history_is_bounded_to_the_inbound_message(fake_deps, monkeypatch) -> None:
    """El turno no ve mensajes del cliente posteriores a su inbound (su propio turno)."""
    from tests.conftest import INBOUND_MSG_ID

    get_msgs_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation())
    )
    monkeypatch.setattr(
        f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer())
    )
    monkeypatch.setattr(f"{MODULE}.get_recent_messages", get_msgs_mock)
    node = make_load_conversation_node(fake_deps)

    await node({**_state(), "inbound_message_id": str(INBOUND_MSG_ID)})

    assert get_msgs_mock.await_args.kwargs["up_to_message_id"] == INBOUND_MSG_ID
