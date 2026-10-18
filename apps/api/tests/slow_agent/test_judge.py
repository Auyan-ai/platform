"""Tests del judge — mockean la API de Anthropic."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.core.config import get_models
from apps.api.db.models import Conversation
from apps.api.slow_agent.judge import (
    _call_judge,
    judge_conversation,
)
from apps.api.slow_agent.transcript import build_transcript

TENANT = uuid.uuid4()
NOW = datetime(2026, 5, 19, 12, 0, 0)


def _conv() -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        end_customer_id=uuid.uuid4(),
        channel="chat",
        status="escalated",
        created_at=NOW,
    )


def _transcript():
    return build_transcript(_conv(), [], [], None, None, "salt")


def _mock_anthropic(response_json: dict) -> MagicMock:
    content_block = MagicMock(type="text")
    content_block.text = json.dumps(response_json)
    usage = MagicMock()
    usage.input_tokens = 500
    usage.output_tokens = 200
    message = MagicMock()
    message.content = [content_block]
    message.usage = usage
    anthropic = MagicMock()
    anthropic.messages.create = AsyncMock(return_value=message)
    return anthropic


# ─── _call_judge ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_judge_propose_true():
    payload = {
        "should_propose": True,
        "proposal_type": "aop_edit",
        "aop_slug": "consulta_envio",
        "diff_markdown": "## Añadir instrucción\n- Si el cliente pide rastreo, ofrecer código.",
        "rationale": "El agente escaló sin verificar el tracking.",
        "confidence": 0.85,
        "flag_for_opus": False,
    }
    anthropic = _mock_anthropic(payload)
    verdict = await _call_judge(anthropic, _transcript(), "slow_agent_model")

    assert verdict.should_propose is True
    assert verdict.proposal_type == "aop_edit"
    assert verdict.aop_slug == "consulta_envio"
    assert verdict.confidence == 0.85
    assert verdict.flag_for_opus is False
    assert verdict.model_used == get_models().slow_agent_model
    assert verdict.input_tokens == 500
    assert verdict.output_tokens == 200


@pytest.mark.asyncio
async def test_call_judge_no_propose():
    payload = {"should_propose": False, "confidence": 0.9}
    anthropic = _mock_anthropic(payload)
    verdict = await _call_judge(anthropic, _transcript(), "slow_agent_model")

    assert verdict.should_propose is False
    assert verdict.proposal_type is None
    assert verdict.confidence == 0.9


@pytest.mark.asyncio
async def test_call_judge_handles_json_embedded_in_text():
    content_block = MagicMock(type="text")
    content_block.text = (
        'Aquí está mi análisis:\n\n'
        '{"should_propose": false, "confidence": 0.8}\n\nEspero que ayude.'
    )
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    message = MagicMock()
    message.content = [content_block]
    message.usage = usage
    anthropic = MagicMock()
    anthropic.messages.create = AsyncMock(return_value=message)

    verdict = await _call_judge(anthropic, _transcript(), "slow_agent_model")
    assert verdict.should_propose is False


@pytest.mark.asyncio
async def test_call_judge_handles_invalid_json():
    content_block = MagicMock(type="text")
    content_block.text = "No puedo analizar esto."
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 20
    message = MagicMock()
    message.content = [content_block]
    message.usage = usage
    anthropic = MagicMock()
    anthropic.messages.create = AsyncMock(return_value=message)

    verdict = await _call_judge(anthropic, _transcript(), "slow_agent_model")
    assert verdict.should_propose is False
    assert verdict.confidence == 0.0


# ─── judge_conversation (two-step) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_judge_conversation_uses_sonnet_when_confident():
    payload = {
        "should_propose": True,
        "proposal_type": "aop_edit",
        "aop_slug": "default",
        "diff_markdown": "## Cambio",
        "rationale": "Razón clara.",
        "confidence": 0.82,
        "flag_for_opus": False,
    }
    anthropic = _mock_anthropic(payload)
    verdict = await judge_conversation(anthropic, _transcript())

    assert verdict.model_used == get_models().slow_agent_model
    # Solo una llamada — no escaló a Opus
    assert anthropic.messages.create.call_count == 1


@pytest.mark.asyncio
async def test_judge_conversation_escalates_to_opus_on_low_confidence():
    low_conf_payload = {
        "should_propose": True,
        "proposal_type": "aop_edit",
        "aop_slug": "default",
        "diff_markdown": "...",
        "rationale": "...",
        "confidence": 0.55,  # < 0.7 → escala
        "flag_for_opus": False,
    }
    opus_payload = {
        "should_propose": True,
        "proposal_type": "aop_edit",
        "aop_slug": "default",
        "diff_markdown": "## Opus analysis",
        "rationale": "Análisis más profundo.",
        "confidence": 0.88,
        "flag_for_opus": False,
    }

    call_count = 0

    async def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            content_block = MagicMock(type="text")
            content_block.text = json.dumps(low_conf_payload)
        else:
            content_block = MagicMock(type="text")
            content_block.text = json.dumps(opus_payload)
        usage = MagicMock()
        usage.input_tokens = 500
        usage.output_tokens = 200
        message = MagicMock()
        message.content = [content_block]
        message.usage = usage
        return message

    anthropic = MagicMock()
    anthropic.messages.create = AsyncMock(side_effect=side_effect)

    verdict = await judge_conversation(anthropic, _transcript())

    assert anthropic.messages.create.call_count == 2
    assert verdict.model_used == get_models().judge_opus_model
    assert verdict.confidence == 0.88


@pytest.mark.asyncio
async def test_judge_conversation_escalates_to_opus_on_flag():
    flagged_payload = {
        "should_propose": True,
        "proposal_type": "skill_request",
        "aop_slug": None,
        "diff_markdown": "...",
        "rationale": "...",
        "confidence": 0.75,
        "flag_for_opus": True,  # explícitamente escalado
    }
    opus_payload = {
        "should_propose": False,
        "confidence": 0.91,
        "flag_for_opus": False,
    }

    call_count = 0

    async def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        payload = flagged_payload if call_count == 1 else opus_payload
        content_block = MagicMock(type="text")
        content_block.text = json.dumps(payload)
        usage = MagicMock()
        usage.input_tokens = 500
        usage.output_tokens = 100
        message = MagicMock()
        message.content = [content_block]
        message.usage = usage
        return message

    anthropic = MagicMock()
    anthropic.messages.create = AsyncMock(side_effect=side_effect)

    verdict = await judge_conversation(anthropic, _transcript())

    assert anthropic.messages.create.call_count == 2
    assert verdict.model_used == get_models().judge_opus_model
    assert verdict.should_propose is False
