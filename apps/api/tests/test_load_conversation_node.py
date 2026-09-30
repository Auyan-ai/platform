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
    monkeypatch.setattr(f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation()))
    monkeypatch.setattr(f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer()))
    monkeypatch.setattr(f"{MODULE}.get_recent_messages", AsyncMock(return_value=[msg1, msg2]))
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
    monkeypatch.setattr(f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation()))
    monkeypatch.setattr(f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer()))
    monkeypatch.setattr(f"{MODULE}.get_recent_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        f"{MODULE}.get_recent_read_outputs_for_conversation",
        AsyncMock(
            return_value=[
                ("shopify.get_order_status", {"order_number": "#1278", "fulfillment_status": None})
            ]
        ),
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
    monkeypatch.setattr(f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation()))
    monkeypatch.setattr(f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer()))
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
    monkeypatch.setattr(f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer()))
    monkeypatch.setattr(f"{MODULE}.get_recent_messages", AsyncMock(return_value=[]))
    node = make_load_conversation_node(fake_deps)

    out = await node(_state())

    assert out["error"] == "conversation_not_found"


@pytest.mark.asyncio
async def test_end_customer_not_found(fake_deps, monkeypatch) -> None:
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation()))
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
    monkeypatch.setattr(f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation()))
    monkeypatch.setattr(f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer()))
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
    monkeypatch.setattr(f"{MODULE}.get_conversation", AsyncMock(return_value=make_conversation()))
    monkeypatch.setattr(f"{MODULE}.get_end_customer", AsyncMock(return_value=make_end_customer()))
    monkeypatch.setattr(f"{MODULE}.get_recent_messages", get_msgs_mock)
    node = make_load_conversation_node(fake_deps)

    await node({**_state(), "inbound_message_id": str(INBOUND_MSG_ID)})

    assert get_msgs_mock.await_args.kwargs["up_to_message_id"] == INBOUND_MSG_ID


class TestPendingCustomerMessagesLast:
    """Con la cola, la respuesta de un turno previo puede quedar tras los mensajes
    pendientes; el historial debe terminar en el cliente (lo exige el builder)."""

    @staticmethod
    def _msgs() -> list:
        from uuid import uuid4

        hola = make_message(id=uuid4(), role="customer", content="Hola")
        m2 = make_message(id=uuid4(), role="customer", content="duda envíos")
        m3 = make_message(id=uuid4(), role="customer", content="¿cuánto tarda?")
        reply = make_message(
            id=uuid4(),
            role="agent_ai",
            direction="outbound",
            content="¡Hola! ¿En qué te ayudo?",
            metadata={"inbound_message_id": str(hola.id)},
        )
        return [hola, m2, m3, reply]

    def test_reply_moves_before_pending_messages(self) -> None:
        from apps.api.agents.nodes.load_conversation import _pending_customer_messages_last

        hola, m2, m3, reply = self._msgs()
        out = _pending_customer_messages_last([hola, m2, m3, reply])
        assert [m.content for m in out] == [hola.content, reply.content, m2.content, m3.content]

    def test_already_ordered_history_is_untouched(self) -> None:
        from apps.api.agents.nodes.load_conversation import _pending_customer_messages_last

        hola, m2, m3, reply = self._msgs()
        ordered = [hola, reply, m2, m3]
        assert _pending_customer_messages_last(ordered) == ordered

    def test_legacy_history_without_links_is_untouched(self) -> None:
        from apps.api.agents.nodes.load_conversation import _pending_customer_messages_last

        hola, m2, _, _ = self._msgs()
        legacy = make_message(role="agent_ai", direction="outbound", content="x", metadata={})
        history = [hola, legacy, m2]
        assert _pending_customer_messages_last(history) == history
