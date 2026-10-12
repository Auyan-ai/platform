"""Coste de un run del simulador con usage reales de Anthropic (#335)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from apps.api.core.config import get_models
from apps.api.db.models import SimulationScenario, UserProfile
from apps.api.simulator import runner

TENANT = uuid4()

_JUDGE_JSON = {
    "reasoning_score": 8,
    "knowledge_score": 8,
    "tools_score": 8,
    "brand_voice_score": 8,
    "overall_score": 8.0,
    "verdict": "pass",
    "judge_goal_achieved": True,
}


def _usage(
    *, input_tokens: int, output_tokens: int, cache_write: int = 0, cache_read: int = 0
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
        cache_creation=None,
    )


def _response(text: str, usage: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(text=text)], usage=usage)


def _anthropic() -> MagicMock:
    sim_turn = _response(
        json.dumps({"message": "gracias", "goal_achieved": True, "give_up": False}),
        _usage(input_tokens=200, output_tokens=40, cache_read=1500),
    )
    judge = _response(
        json.dumps(_JUDGE_JSON),
        _usage(input_tokens=3000, output_tokens=300, cache_write=1200),
    )

    async def create(**kwargs: Any) -> SimpleNamespace:
        return {get_models().simulator_model: sim_turn, get_models().judge_sonnet_model: judge}[kwargs["model"]]

    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=create)
    return client


def _graph() -> MagicMock:
    graph = MagicMock()
    graph.ainvoke = AsyncMock(
        return_value={
            "agent_response": "Tu pedido llega mañana.",
            "system_prompt": "Eres el agente.",
            "decision": "respond",
            "tokens_in": 10_000,
            "tokens_out": 500,
            "cost_usd": 0.012,
        }
    )
    return graph


@pytest.fixture
def finalize(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    profile = UserProfile(
        id=uuid4(), tenant_id=TENANT, name="p", goal="tracking", initial_message="hola"
    )
    scenario = SimulationScenario(
        id=uuid4(),
        tenant_id=TENANT,
        name="CE-01",
        aop_slug="consulta_envio",
        user_profile_id=profile.id,
        expected_outcome="resolved",
        max_turns=3,
    )

    @asynccontextmanager
    async def fake_scope(_tenant_id: Any):
        yield MagicMock()

    finalize_mock = AsyncMock()
    monkeypatch.setattr(runner, "tenant_scope", fake_scope)
    monkeypatch.setattr(runner, "get_simulation_scenario", AsyncMock(return_value=scenario))
    monkeypatch.setattr(runner, "get_user_profile", AsyncMock(return_value=profile))
    monkeypatch.setattr(
        runner, "_setup_run", AsyncMock(return_value=(uuid4(), uuid4(), uuid4()))
    )
    monkeypatch.setattr(runner, "_persist_customer_message", AsyncMock())
    monkeypatch.setattr(runner, "_persist_agent_message", AsyncMock())
    monkeypatch.setattr(runner, "_get_skill_log", AsyncMock(return_value=[]))
    monkeypatch.setattr(runner, "_pending_approval_present", AsyncMock(return_value=False))
    monkeypatch.setattr(runner, "finalize_simulation_run", finalize_mock)
    monkeypatch.setattr(runner, "soft_delete_conversation", AsyncMock())
    monkeypatch.setattr(runner, "soft_delete_conversation_checks", AsyncMock(return_value=0))
    return finalize_mock


async def test_run_cost_sums_agent_cost_and_cached_simulator_and_judge_calls(
    finalize: AsyncMock,
) -> None:
    await runner.run_simulation(
        uuid4(), TENANT, anthropic=_anthropic(), graph=_graph()
    )

    # agente: 0.012 USD de final_state["cost_usd"]                         = 1.2 ¢
    # simulador (Haiku): 200*$1 + 1500 lectura caché*$0.10 + 40*$5 = $0.00055 = 0.055 ¢
    # judge (Sonnet): 3000*$3 + 1200 escritura caché*$3.75 + 300*$15 = $0.018 = 1.8 ¢
    kwargs = finalize.call_args.kwargs
    assert kwargs["cost_cents"] == pytest.approx(3.055)
    assert kwargs["tokens_simulator"] == 200 + 1500 + 40
    assert kwargs["tokens_judge"] == 3000 + 1200 + 300
    assert kwargs["judge_eval"]["input_tokens"] == 4200
