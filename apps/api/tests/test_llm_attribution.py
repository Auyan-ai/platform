"""Cada llamada al LLM queda atribuida a su rol, con su coste, en el turno y en el tenant
(#378, #379). Los tests llaman al cliente HTTP falso de Anthropic: el código de
`integrations/anthropic_client.py` corre entero."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.agents.graph import build_graph
from apps.api.agents.service import AgentService
from apps.api.services.approval_reply import generate_customer_reply
from apps.api.services.usage import UsageRecorder

from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    INBOUND_MSG_ID,
    TENANT_ID,
    FakeAnthropicResponse,
    make_fake_bootstrap_connection,
)
from tests.test_graph_e2e import _patch_all_db_and_llm
from tests.test_select_aop_node import DEFAULT_AOP

# Haiku 4.5: $1 entrada, $5 salida por millón.
CLASSIFIER_COST = (2000 * 1.0 + 150 * 5.0) / 1_000_000
SIMPLE_TURN_COST = (100 * 1.0 + 50 * 5.0) / 1_000_000


def _classifier_response() -> FakeAnthropicResponse:
    return FakeAnthropicResponse(
        {
            "primary": {"slug": "default", "confidence": 0.9},
            "reasoning": "consulta general",
            "ambiguity_detected": False,
        },
        tool_name="select_aop",
        input_tokens=2000,
        output_tokens=150,
    )


def _reply_response() -> FakeAnthropicResponse:
    return FakeAnthropicResponse(
        {"decision": "respond", "confidence": 0.92, "response_text": "Los envíos tardan 3-5 días."}
    )


def _with_aops(monkeypatch: pytest.MonkeyPatch, insert_run: AsyncMock) -> None:
    monkeypatch.setattr(
        "apps.api.agents.nodes.select_aop.load_active_aops", AsyncMock(return_value=[DEFAULT_AOP])
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.select_aop.get_last_intent_for_conversation",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.select_aop.load_aop", AsyncMock(return_value=DEFAULT_AOP)
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.select_aop.insert_intent_classifier_run", insert_run
    )


async def _run_turn(fake_deps: Any, *responses: FakeAnthropicResponse) -> Any:
    fake_deps.anthropic.messages.create = AsyncMock(side_effect=list(responses))
    service = AgentService(
        graph=build_graph(fake_deps),
        observability=MagicMock(),
        handle_error=AsyncMock(side_effect=AssertionError("el grafo no debe lanzar")),
    )
    return await service.process_inbound(
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        inbound_message_id=INBOUND_MSG_ID,
        inbound_message_content="¿envíos a Argentina?",
        channel="chat",
        end_customer_id=CUSTOMER_ID,
    )


@pytest.mark.asyncio
async def test_turn_cost_includes_the_aop_classifier(
    fake_deps: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_all_db_and_llm(monkeypatch)
    _with_aops(monkeypatch, AsyncMock())

    with caplog.at_level(logging.INFO, logger="apps.api.integrations.anthropic_client"):
        outcome = await _run_turn(fake_deps, _classifier_response(), _reply_response())

    assert outcome.decision == "respond"
    assert outcome.cost_usd == pytest.approx(CLASSIFIER_COST + SIMPLE_TURN_COST)
    assert outcome.tokens_in == 2100
    assert outcome.tokens_out == 200
    assert any("llm_call label=select_aop" in r.getMessage() for r in caplog.records)


async def _drain_usage_tasks() -> None:
    await asyncio.gather(*UsageRecorder._pending_tasks)


@pytest.mark.asyncio
async def test_approval_reply_records_its_usage_for_the_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upsert = AsyncMock()
    monkeypatch.setattr("apps.api.services.usage.upsert_tenant_usage_daily", upsert)
    monkeypatch.setattr("apps.api.services.usage.insert_llm_calls", AsyncMock())
    monkeypatch.setattr(
        "apps.api.services.usage.bootstrap_connection", make_fake_bootstrap_connection()
    )
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Listo, ya está cancelado.")],
            usage=SimpleNamespace(input_tokens=300, output_tokens=40),
            stop_reason="end_turn",
        )
    )

    await generate_customer_reply(
        client,
        "shopify.cancel_order",
        success=False,
        reject_comment="no procede",
        language="es",
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
    )
    await _drain_usage_tasks()

    upsert.assert_awaited_once()
    kwargs = upsert.await_args.kwargs
    assert kwargs["tenant_id"] == TENANT_ID
    assert kwargs["tokens_in"] == 300
    assert kwargs["tokens_out"] == 40
    assert kwargs["cost_usd"] == pytest.approx((300 * 1.0 + 40 * 5.0) / 1_000_000)
