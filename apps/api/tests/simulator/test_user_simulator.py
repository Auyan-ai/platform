"""Tests del user_simulator.py — sin llamadas reales al LLM."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from apps.api.integrations.pricing import LLMUsage
from apps.api.simulator.user_simulator import (
    UserSimulator,
    _build_messages,
    _parse_turn,
)


def _make_profile(
    *,
    initial_message: str = "Hola",
    goal: str = "Saber el tracking",
    language: str = "es",
    persona: dict | None = None,
):
    from datetime import datetime

    from apps.api.db.models import UserProfile

    return UserProfile(
        id=uuid4(),
        tenant_id=uuid4(),
        name="cooperativo",
        persona=persona or {"tone": "amable", "behavior": "paciente", "give_up_after": 10},
        goal=goal,
        initial_message=initial_message,
        language=language,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


class TestFirstMessage:
    def test_returns_initial_message_without_llm(self):
        profile = _make_profile(initial_message="Quiero saber mi pedido #1234")
        sim = UserSimulator(profile=profile, anthropic=MagicMock())
        turn = sim.first_message()
        assert turn.message == "Quiero saber mi pedido #1234"
        assert not turn.goal_achieved
        assert not turn.give_up
        assert turn.input_tokens == 0
        assert turn.output_tokens == 0


class TestBuildMessages:
    def test_agent_maps_to_user(self):
        # Desde la perspectiva del simulador (que ES el cliente), el agente es la
        # "otra parte" → user.
        history = [{"role": "agent", "content": "¿En qué puedo ayudarte?"}]
        result = _build_messages(history)
        assert result == [{"role": "user", "content": "¿En qué puedo ayudarte?"}]

    def test_leading_customer_message_dropped(self):
        # El mensaje inicial del cliente mapea a assistant; como Anthropic exige
        # empezar con user, se descarta hasta el primer mensaje del agente.
        history = [
            {"role": "customer", "content": "Hola, quiero devolver"},
            {"role": "agent", "content": "Claro, ¿qué pedido?"},
        ]
        result = _build_messages(history)
        assert result == [{"role": "user", "content": "Claro, ¿qué pedido?"}]

    def test_alternating_roles_start_with_user(self):
        history = [
            {"role": "customer", "content": "msg1"},
            {"role": "agent", "content": "msg2"},
            {"role": "customer", "content": "msg3"},
            {"role": "agent", "content": "msg4"},
        ]
        msgs = _build_messages(history)
        # customer-msg1 (assistant) descartado al inicio; queda user/assistant/user
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "msg2"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "msg3"
        assert msgs[2]["role"] == "user"

    def test_unknown_roles_skipped(self):
        history = [
            {"role": "agent", "content": "hola"},
            {"role": "system", "content": "ignore me"},
        ]
        result = _build_messages(history)
        assert result == [{"role": "user", "content": "hola"}]

    def test_empty_content_skipped(self):
        history = [
            {"role": "agent", "content": "hola"},
            {"role": "customer", "content": "   "},
        ]
        result = _build_messages(history)
        assert result == [{"role": "user", "content": "hola"}]


class TestParseTurn:
    def test_valid_json(self):
        raw = '{"message": "Hola", "goal_achieved": false, "give_up": false, "internal_reasoning": "ok"}'
        turn = _parse_turn(raw, LLMUsage(input_tokens=100, output_tokens=50))
        assert turn.message == "Hola"
        assert not turn.goal_achieved
        assert not turn.give_up
        assert turn.input_tokens == 100
        assert turn.output_tokens == 50

    def test_goal_achieved(self):
        raw = '{"message": "ok gracias", "goal_achieved": true, "give_up": false, "internal_reasoning": "done"}'
        turn = _parse_turn(raw, LLMUsage())
        assert turn.goal_achieved

    def test_json_embedded_in_text(self):
        raw = 'Sure: {"message": "hola", "goal_achieved": false, "give_up": false, "internal_reasoning": "x"}'
        turn = _parse_turn(raw, LLMUsage())
        assert turn.message == "hola"

    def test_fallback_on_invalid_json(self):
        raw = "esto no es json"
        turn = _parse_turn(raw, LLMUsage(input_tokens=10, output_tokens=5))
        assert turn.message == "esto no es json"
        assert turn.internal_reasoning == "parse_error"
        assert not turn.goal_achieved
        assert not turn.give_up


class TestNextTurn:
    @pytest.mark.asyncio
    async def test_calls_anthropic_and_returns_turn(self):
        profile = _make_profile()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"message": "vale", "goal_achieved": false, "give_up": false, "internal_reasoning": "ok"}')]
        mock_response.usage.input_tokens = 200
        mock_response.usage.output_tokens = 30

        anthropic = MagicMock()
        anthropic.messages.create = AsyncMock(return_value=mock_response)

        sim = UserSimulator(profile=profile, anthropic=anthropic)
        history = [{"role": "customer", "content": "Hola"}, {"role": "agent", "content": "¿En qué ayudo?"}]
        turn = await sim.next_turn(conversation_history=history, turn_number=1)

        assert turn.message == "vale"
        assert turn.input_tokens == 200
        assert turn.output_tokens == 30
        anthropic.messages.create.assert_called_once()


class TestNextTurnRequest:
    """La petición que sale por HTTP, con el SDK real."""

    @pytest.mark.asyncio
    async def test_haiku_request_keeps_temperature(self, monkeypatch):
        from apps.api.tests.anthropic_http import RecordingAnthropic, message, text

        monkeypatch.delenv("SIMULATOR_MODEL", raising=False)
        reply = '{"message": "vale", "goal_achieved": false, "give_up": false, "internal_reasoning": "ok"}'
        api = RecordingAnthropic(message(text(reply), stop_reason="end_turn"))

        sim = UserSimulator(profile=_make_profile(), anthropic=api.client)
        turn = await sim.next_turn(
            conversation_history=[{"role": "agent", "content": "¿En qué ayudo?"}], turn_number=1
        )

        assert turn.message == "vale"
        body = api.requests[0]
        assert body["model"] == "claude-haiku-4-5-20251001"
        assert body["temperature"] == 0.7
        assert body["max_tokens"] == 512
