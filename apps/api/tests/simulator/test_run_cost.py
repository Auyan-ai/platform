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
    monkeypatch.setattr(runner, "_persist_escalation_ack", AsyncMock())
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


async def test_run_leaves_one_langsmith_trace_with_simulation_metadata_and_children(
    finalize: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.integrations.langsmith_client import LangSmithClient
    from apps.api.integrations.observability import ObservabilityClient

    save_trace_id = AsyncMock()
    monkeypatch.setattr(runner, "set_simulation_run_trace_id", save_trace_id)
    inner = MagicMock()
    observability = ObservabilityClient(primary=LangSmithClient(inner, project_name="auyan-test"))

    await runner.run_simulation(
        uuid4(), TENANT, anthropic=_anthropic(), graph=_graph(), observability=observability
    )

    creates = [c.kwargs for c in inner.create_run.call_args_list]
    root = next(c for c in creates if c["name"] == "simulation_run")
    meta = root["extra"]["metadata"]
    assert meta["simulation"] is True
    assert meta["scenario_name"] == "CE-01"
    assert set(meta) >= {"simulation_run_id", "scenario_id", "capabilities", "tenant_id"}
    assert "simulation" in root["tags"]
    assert root["trace_id"] == root["id"]

    turn = next(c for c in creates if c["name"] == "agent_conversation")
    assert turn["parent_run_id"] == root["id"]
    assert turn["trace_id"] == root["id"]
    assert turn["extra"]["metadata"]["simulation_run_id"] == meta["simulation_run_id"]

    llm_runs = {c["name"]: c for c in creates if c["run_type"] == "llm"}
    assert set(llm_runs) >= {"customer_simulator", "simulation_judge", "agent_model_call"}
    simulator_usage = llm_runs["customer_simulator"]["extra"]["metadata"]["usage_metadata"]
    assert simulator_usage["input_tokens"] == 200 + 1500
    assert simulator_usage["output_tokens"] == 40
    judge_usage = llm_runs["simulation_judge"]["extra"]["metadata"]["usage_metadata"]
    assert judge_usage["input_tokens"] == 3000 + 1200
    assert judge_usage["total_cost"] == pytest.approx(0.018)
    for child in llm_runs.values():
        assert child["trace_id"] == root["id"]

    turn_update = next(
        c.kwargs for c in inner.update_run.call_args_list if c.args[0] == turn["id"]
    )
    assert turn_update["parent_run_id"] == root["id"]

    final = next(c.kwargs for c in inner.update_run.call_args_list if c.args[0] == root["id"])
    assert final["extra"]["metadata"]["cost_usd"] == pytest.approx(0.03055)
    assert final["extra"]["metadata"]["simulation"] is True

    _conn, run_db_id, tenant_id, trace_id = save_trace_id.call_args.args
    assert (str(run_db_id), tenant_id, trace_id) == (meta["simulation_run_id"], TENANT, root["id"])
