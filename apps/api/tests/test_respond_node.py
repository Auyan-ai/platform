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


@pytest.mark.asyncio
async def test_message_metadata_links_the_inbound_message(fake_deps, monkeypatch) -> None:
    """La respuesta guarda su inbound: el worker no re-responde un turno reintentado."""
    insert_mock = AsyncMock(return_value=make_message(id=OUTBOUND_MSG_ID))
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_message", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    node = make_respond_node(fake_deps)

    await node({**_state(), "inbound_message_id": "inbound-123"})

    assert insert_mock.await_args.kwargs["metadata"]["inbound_message_id"] == "inbound-123"


async def _run_respond(fake_deps, monkeypatch, state: dict) -> tuple[dict, AsyncMock]:
    insert_mock = AsyncMock(return_value=make_message(id=OUTBOUND_MSG_ID))
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.insert_message", insert_mock)
    monkeypatch.setattr(f"{MODULE}.update_conversation_last_message", AsyncMock())
    return await make_respond_node(fake_deps)(state), insert_mock


@pytest.mark.asyncio
async def test_chat_reply_is_normalized_before_persisting_and_returned(
    fake_deps, monkeypatch
) -> None:
    out, insert_mock = await _run_respond(
        fake_deps,
        monkeypatch,
        _state(channel="chat", agent_response="**Hola** 😊 tu pedido #1001 sale hoy"),
    )

    assert insert_mock.await_args.kwargs["content"] == "Hola tu pedido #1001 sale hoy"
    assert out["agent_response"] == "Hola tu pedido #1001 sale hoy"
    assert insert_mock.await_args.kwargs["metadata"]["writing_surface"] == "chat"


@pytest.mark.asyncio
async def test_emojis_survive_when_tenant_opted_in(fake_deps, monkeypatch) -> None:
    out, _ = await _run_respond(
        fake_deps,
        monkeypatch,
        _state(
            channel="chat",
            agent_response="¡Gracias! 😊",
            tenant_config={"extra": {"allow_emojis": True}},
        ),
    )

    assert out["agent_response"] == "¡Gracias! 😊"


@pytest.mark.asyncio
async def test_emojis_stripped_when_allow_emojis_is_not_literally_true(
    fake_deps, monkeypatch
) -> None:
    out, _ = await _run_respond(
        fake_deps,
        monkeypatch,
        _state(
            channel="chat",
            agent_response="Gracias 😊",
            tenant_config={"extra": {"allow_emojis": "yes"}},
        ),
    )

    assert out["agent_response"] == "Gracias"


@pytest.mark.asyncio
async def test_zendesk_email_ticket_gets_system_signature(fake_deps, monkeypatch) -> None:
    out, insert_mock = await _run_respond(
        fake_deps,
        monkeypatch,
        _state(
            channel="zendesk",
            conversation_history=[{"role": "customer", "metadata": {"source_channel": "email"}}],
            tenant_name="Marea SL",
            tenant_facts={"company_name": "Marea Studio"},
            agent_response="Hola Ana,\n\nTu pedido sale hoy.\n\nSaludos,\nLucía",
        ),
    )

    expected = "Hola Ana,\n\nTu pedido sale hoy.\n\nEl equipo de Marea Studio"
    assert insert_mock.await_args.kwargs["content"] == expected
    assert out["agent_response"] == expected
    assert insert_mock.await_args.kwargs["metadata"]["writing_surface"] == "email"


@pytest.mark.asyncio
async def test_zendesk_chat_ticket_is_not_signed(fake_deps, monkeypatch) -> None:
    out, _ = await _run_respond(
        fake_deps,
        monkeypatch,
        _state(
            channel="zendesk",
            conversation_history=[
                {"role": "customer", "metadata": {"source_channel": "native_messaging"}}
            ],
            tenant_name="Marea SL",
            agent_response="Tu pedido sale hoy.",
        ),
    )

    assert out["agent_response"] == "Tu pedido sale hoy."


@pytest.mark.asyncio
async def test_email_uses_client_signature_from_facts(fake_deps, monkeypatch) -> None:
    out, _ = await _run_respond(
        fake_deps,
        monkeypatch,
        _state(
            channel="email",
            tenant_facts={"email_signature": "Ana · Atención al cliente"},
            agent_response="Hola.",
        ),
    )

    assert out["agent_response"] == "Hola.\n\nAna · Atención al cliente"


@pytest.mark.asyncio
async def test_whatsapp_reply_has_no_markup_and_no_signature(fake_deps, monkeypatch) -> None:
    out, _ = await _run_respond(
        fake_deps,
        monkeypatch,
        _state(channel="whatsapp", tenant_name="Marea SL", agent_response="*Hola* Ana, ya salió"),
    )

    assert out["agent_response"] == "Hola Ana, ya salió"


@pytest.mark.asyncio
async def test_reply_that_is_only_emoji_is_treated_as_empty(fake_deps, monkeypatch) -> None:
    out, insert_mock = await _run_respond(
        fake_deps, monkeypatch, _state(channel="chat", agent_response="😊")
    )

    assert out["error"] == "respond_without_text"
    insert_mock.assert_not_called()
