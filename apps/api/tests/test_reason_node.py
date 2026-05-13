"""Tests del nodo `reason` — el núcleo del agente.

Mockeamos `call_claude_with_tool` para no tocar la API real.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.api.agents.nodes.reason import make_reason_node


def _base_state() -> dict:
    """State mínimo válido para que `reason` ejecute sin errores de carga previa."""
    return {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "system_prompt": "Eres el agente de Acme.",
        "retrieved_chunks": [],
        "conversation_history": [{"role": "customer", "content": "¿Cuánto tarda el envío?"}],
        "model_used": "claude-sonnet-4-6",
        "tenant_config": {"escalation_threshold": 0.70},
    }


@pytest.mark.asyncio
async def test_respond_happy_path(fake_deps, make_anthropic_response, monkeypatch) -> None:
    fake_response = make_anthropic_response(
        {
            "decision": "respond",
            "confidence": 0.92,
            "response_text": "Los envíos tardan 3-5 días.",
        }
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tool",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    out = await node(_base_state())

    assert out["decision"] == "respond"
    assert out["agent_response"] == "Los envíos tardan 3-5 días."
    assert out["confidence"] == 0.92
    assert out["tokens_in"] == 100
    assert out["tokens_out"] == 50
    assert out["cost_usd"] > 0
    assert out["model_used"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_threshold_override_low_confidence_respond_to_escalate(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """Si Claude dice 'respond' pero con confianza < threshold, forzamos 'escalate'."""
    fake_response = make_anthropic_response(
        {
            "decision": "respond",
            "confidence": 0.50,  # < threshold 0.70
            "response_text": "respuesta tentativa",
        }
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tool",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    out = await node(_base_state())

    assert out["decision"] == "escalate"
    assert out["agent_response"] is None
    assert "low_confidence" in (out["escalation_reason"] or "")
    assert "0.50" in (out["escalation_reason"] or "")


@pytest.mark.asyncio
async def test_threshold_does_not_override_explicit_escalate(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """Si Claude ya decidió 'escalate', el threshold no toca esa decisión."""
    fake_response = make_anthropic_response(
        {
            "decision": "escalate",
            "confidence": 0.95,
            "escalation_reason": "customer_requested_human",
        }
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tool",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    out = await node(_base_state())

    assert out["decision"] == "escalate"
    assert out["escalation_reason"] == "customer_requested_human"


@pytest.mark.asyncio
async def test_high_confidence_keeps_respond(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """Confianza ≥ threshold mantiene 'respond' intacto."""
    fake_response = make_anthropic_response(
        {
            "decision": "respond",
            "confidence": 0.80,  # > threshold 0.70
            "response_text": "respuesta firme",
        }
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tool",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    out = await node(_base_state())

    assert out["decision"] == "respond"
    assert out["agent_response"] == "respuesta firme"


@pytest.mark.asyncio
async def test_invalid_tool_output_sets_error(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """decision='respond' sin response_text → ValidationError → error en state."""
    fake_response = make_anthropic_response(
        {"decision": "respond", "confidence": 0.9}
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tool",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    out = await node(_base_state())

    assert out.get("error") is not None
    assert "invalid_tool_output" in out["error"] or "reason:" in out["error"]


@pytest.mark.asyncio
async def test_no_tool_use_block_sets_error(fake_deps, monkeypatch) -> None:
    """Si la respuesta de Claude no tiene tool_use block, error explícito."""

    class FakeBlock:
        type = "text"

    class FakeUsage:
        input_tokens = 10
        output_tokens = 5

    class FakeResponse:
        content = [FakeBlock()]
        usage = FakeUsage()

    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tool",
        AsyncMock(return_value=FakeResponse()),
    )
    node = make_reason_node(fake_deps)

    out = await node(_base_state())

    assert out.get("error") is not None
    assert "claude_did_not_use_tool" in out["error"]
