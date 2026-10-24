"""La petición HTTP que cada nodo manda a Anthropic, por modelo (#345).

Cliente real del SDK con transporte falso (`tests/anthropic_http.py`). Con los modelos de
hoy (Haiku 4.5, Sonnet 4.6, Opus 4.7) la petición es la misma que antes de #345: los JSON
de `golden_requests/` se capturaron con el código anterior. Con los 5.5, la petición no
fuerza tool ni apaga el thinking, y la respuesta se lee igual con thinking, sin tool o con
`stop_reason: refusal`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes.reason import make_reason_node
from apps.api.agents.nodes.select_aop import make_select_aop_node
from apps.api.agents.nodes.supervise import make_supervise_node
from apps.api.core.config import ModelRegistry, get_models
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify.cancel_order import CancelOrder
from apps.api.skills.shopify.get_shop_policies import GetShopPolicies
from apps.api.tests.anthropic_http import (
    RecordingAnthropic,
    message,
    refusal,
    text,
    thinking,
    tool_use,
)
from apps.api.tests.test_select_aop_node import (
    BASE_STATE as SELECT_AOP_STATE,
)
from apps.api.tests.test_select_aop_node import (
    CONSULTA_ENVIO,
    DEFAULT_AOP,
    _make_fake_tenant_scope,
)

GOLDEN = Path(__file__).parent / "golden_requests"
FROZEN_NOW = "2026-10-17 10:00 (Europe/Madrid)"
POLICIES = "shopify.get_shop_policies"
CANCEL = "shopify.cancel_order"

RESPOND = {"decision": "respond", "confidence": 0.9, "response_text": "Tardan 3 días."}
CLASSIFIED = {
    "primary": {"slug": "consulta_envio", "confidence": 0.92},
    "reasoning": "pregunta por su pedido",
    "ambiguity_detected": False,
}
APPROVE = {"verdict": "approve", "reject_kind": "n/a", "reason": "correcto"}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    monkeypatch.setattr("apps.api.agents.nodes.reason._tenant_now_str", lambda _facts: FROZEN_NOW)
    for name in ModelRegistry.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    get_models.cache_clear()
    # Otros tests vacían el registro global de skills (`SkillRegistry._reset()`).
    saved = dict(SkillRegistry._by_slug)
    SkillRegistry._by_slug.update({POLICIES: GetShopPolicies, CANCEL: CancelOrder})
    yield monkeypatch
    SkillRegistry._by_slug.clear()
    SkillRegistry._by_slug.update(saved)
    get_models.cache_clear()


def _deps(api: RecordingAnthropic, fake_deps: AgentDependencies) -> AgentDependencies:
    return AgentDependencies(
        anthropic=api.client,
        openai=fake_deps.openai,
        settings=fake_deps.settings,
        reasoning_tracker=fake_deps.reasoning_tracker,
        audit_logger=fake_deps.audit_logger,
    )


def _reason_state(model: str, **extra: Any) -> dict[str, Any]:
    return {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "system_prompt": "Eres el agente de Acme.",
        "retrieved_chunks": [],
        "conversation_history": [{"role": "customer", "content": "¿Cuánto tarda el envío?"}],
        "model_used": model,
        "tenant_config": {"escalation_threshold": 0.70},
        "allowed_skills": [],
        "tool_results": [],
        **extra,
    }


def _with_policies(state: dict[str, Any], *, hops: int) -> dict[str, Any]:
    state["allowed_skills"] = [POLICIES]
    state["tool_permissions"] = {POLICIES: {"is_enabled": True}}
    state["tool_iterations"] = hops
    state["max_tool_iterations"] = 3
    state["tool_results"] = [
        {
            "id": f"toolu_hop{i}",
            "slug": POLICIES,
            "input": {},
            "output": {"shipping": "3 días"},
            "is_error": False,
            "error": None,
        }
        for i in range(hops)
    ]
    return state


def _supervise_state(**extra: Any) -> dict[str, Any]:
    return {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "conversation_id": "22222222-2222-2222-2222-222222222222",
        "system_prompt": "eres un agente de soporte\n## Reglas NO negociables\n- no inventes",
        "tenant_config": {"extra": {}, "escalation_threshold": 0.70},
        "conversation_history": [{"role": "customer", "content": "quiero cancelar"}],
        "decision": "respond",
        "agent_response": "ok, te ayudo",
        "tool_results": [],
        "cost_usd": 0.01,
        "aop_slug": "cancelacion",
        **extra,
    }


async def run_reason(
    fake_deps: AgentDependencies, state: dict[str, Any], *responses: dict[str, Any]
) -> tuple[RecordingAnthropic, dict[str, Any]]:
    api = RecordingAnthropic(*responses)
    out = await make_reason_node(_deps(api, fake_deps))(state)  # type: ignore[arg-type]
    return api, out


async def run_select_aop(
    fake_deps: AgentDependencies, *responses: dict[str, Any]
) -> tuple[RecordingAnthropic, dict[str, Any]]:
    api = RecordingAnthropic(*responses)
    node = make_select_aop_node(_deps(api, fake_deps))
    module = "apps.api.agents.nodes.select_aop"
    with (
        patch(f"{module}.tenant_scope", _make_fake_tenant_scope(AsyncMock())),
        patch(f"{module}.get_last_intent_for_conversation", AsyncMock(return_value=None)),
        patch(f"{module}.load_active_aops", AsyncMock(return_value=[CONSULTA_ENVIO, DEFAULT_AOP])),
        patch(
            f"{module}.load_aop",
            AsyncMock(
                side_effect=lambda _c, _t, slug: {"consulta_envio": CONSULTA_ENVIO}.get(
                    slug, DEFAULT_AOP
                )
            ),
        ),
        patch(f"{module}.insert_intent_classifier_run", AsyncMock()),
    ):
        out = await node(SELECT_AOP_STATE)  # type: ignore[arg-type]
    return api, out


async def run_supervise(
    fake_deps: AgentDependencies, state: dict[str, Any], *responses: dict[str, Any]
) -> tuple[RecordingAnthropic, dict[str, Any]]:
    api = RecordingAnthropic(*responses)
    out = await make_supervise_node(_deps(api, fake_deps))(state)  # type: ignore[arg-type]
    return api, out


async def current_model_scenarios(
    fake_deps: AgentDependencies,
) -> dict[str, RecordingAnthropic]:
    """Un escenario por forma de petición de hoy. Genera y comprueba los golden."""
    simple, _ = await run_reason(
        fake_deps,
        _reason_state("claude-sonnet-4-6"),
        message(tool_use("respond_or_escalate", RESPOND), model="claude-haiku-4-5-20251001"),
    )
    loop, _ = await run_reason(
        fake_deps,
        _with_policies(_reason_state("claude-sonnet-4-6"), hops=1),
        message(tool_use("respond_or_escalate", RESPOND)),
    )
    exhausted, _ = await run_reason(
        fake_deps,
        _with_policies(_reason_state("claude-sonnet-4-6"), hops=3),
        message(tool_use("respond_or_escalate", RESPOND)),
    )
    classifier, _ = await run_select_aop(
        fake_deps, message(tool_use("select_aop", CLASSIFIED), model="claude-haiku-4-5-20251001")
    )
    supervisor_l1_l2, _ = await run_supervise(
        fake_deps,
        _supervise_state(),
        message(tool_use("supervisor_verdict", APPROVE)),
    )
    supervisor_l3, _ = await run_supervise(
        fake_deps,
        _supervise_state(
            decision=None,
            agent_response=None,
            pending_tool_call={"id": "toolu_c", "slug": CANCEL, "input": {"order_id": 1}},
        ),
        message(tool_use("supervisor_verdict", APPROVE), model="claude-opus-4-7"),
    )
    first_hop, _ = await run_reason(
        fake_deps,
        _with_policies(_reason_state("claude-sonnet-4-6"), hops=0),
        message(tool_use("shopify_get_shop_policies", {}, id="toolu_hop0")),
    )
    failed_state = _with_policies(_reason_state("claude-sonnet-4-6"), hops=1)
    failed_state["tool_results"][0].update(
        output=None, is_error=True, error="shopify_unavailable: 503"
    )
    tool_error, _ = await run_reason(
        fake_deps, failed_state, message(tool_use("respond_or_escalate", RESPOND))
    )
    return {
        "reason_simple_haiku": simple,
        "reason_loop_sonnet_4_6": loop,
        "reason_exhausted_sonnet_4_6": exhausted,
        "reason_first_hop_skills_sonnet_4_6": first_hop,
        "reason_tool_error_sonnet_4_6": tool_error,
        "select_aop_haiku": classifier,
        "supervise_l1_l2_sonnet_4_6": supervisor_l1_l2,
        "supervise_l3_opus_4_7": supervisor_l3,
        **await text_role_scenarios(),
    }


SIM_JUDGE_REPLY = json.dumps(
    {
        "reasoning_score": 8,
        "knowledge_score": 8,
        "tools_score": 8,
        "brand_voice_score": 8,
        "overall_score": 8.0,
        "verdict": "pass",
        "judge_goal_achieved": True,
    }
)


def _sim_transcript() -> Any:
    from apps.api.db.models import SimulationScenario
    from apps.api.simulator.transcript import SimulatorTranscript, TranscriptTurn

    scenario = SimulationScenario(
        id=UUID(int=1),
        tenant_id=UUID(int=2),
        name="CE-01",
        aop_slug="consulta_envio",
        user_profile_id=UUID(int=3),
        expected_outcome="El agente da el plazo de envío.",
        mock_fixtures={"goal": "saber el plazo"},
        assertions={},
        max_turns=8,
    )
    transcript = SimulatorTranscript(
        scenario=scenario, profile_name="cooperativo", termination_reason="goal_achieved"
    )
    transcript.turns.append(
        TranscriptTurn(role="customer", content="¿Cuánto tarda?", turn_number=0)
    )
    transcript.turns.append(TranscriptTurn(role="agent", content="Tardan 3 días.", turn_number=1))
    return transcript


async def text_role_scenarios() -> dict[str, RecordingAnthropic]:
    """Jueces, slow agent, mensaje tras aprobar una L3 y simulador, con sus modelos de hoy."""
    from apps.api.services.approval_reply import generate_customer_reply
    from apps.api.simulator.judge import judge_simulation
    from apps.api.simulator.user_simulator import UserSimulator
    from apps.api.slow_agent.judge import _call_judge
    from apps.api.slow_agent.transcript import build_transcript
    from apps.api.tests.simulator.test_user_simulator import _make_profile
    from apps.api.tests.slow_agent.test_judge import _conv

    end_turn = {"stop_reason": "end_turn"}
    sim_judges = {}
    for alias, model in (("sonnet", "claude-sonnet-4-6"), ("opus", "claude-opus-4-7")):
        api = RecordingAnthropic(message(text(SIM_JUDGE_REPLY), model=model, **end_turn))
        await judge_simulation(
            api.client, _sim_transcript(), _sim_transcript().scenario, judge_model=alias
        )
        sim_judges[f"sim_judge_{alias}"] = api

    slow_agent = RecordingAnthropic(
        message(text('{"should_propose": false, "confidence": 0.9}'), **end_turn)
    )
    conversation = _conv().model_copy(update={"id": UUID(int=4), "end_customer_id": UUID(int=5)})
    await _call_judge(
        slow_agent.client,
        build_transcript(conversation, [], [], None, None, "salt"),
        "slow_agent_model",
    )

    approval = RecordingAnthropic(
        message(
            text("Listo, tu pedido está cancelado."), model="claude-haiku-4-5-20251001", **end_turn
        )
    )
    await generate_customer_reply(approval.client, CANCEL, success=True, language="es")

    simulator = RecordingAnthropic(
        message(
            text('{"message": "vale", "goal_achieved": false, "give_up": false}'),
            model="claude-haiku-4-5-20251001",
            **end_turn,
        )
    )
    await UserSimulator(profile=_make_profile(), anthropic=simulator.client).next_turn(
        conversation_history=[{"role": "agent", "content": "¿En qué ayudo?"}], turn_number=1
    )
    return {
        "sim_judge_sonnet_4_6": sim_judges["sim_judge_sonnet"],
        "sim_judge_opus_4_7": sim_judges["sim_judge_opus"],
        "slow_agent_judge_sonnet_4_6": slow_agent,
        "approval_reply_haiku": approval,
        "user_simulator_haiku": simulator,
    }


@pytest.mark.asyncio
async def test_current_models_send_the_same_request_as_before(
    fake_deps: AgentDependencies,
) -> None:
    """`UPDATE_GOLDEN_REQUESTS=1` reescribe los JSON: solo con un cambio de petición buscado."""
    scenarios = await current_model_scenarios(fake_deps)
    for name, api in scenarios.items():
        recorded = {"body": api.requests, "beta": api.beta_headers}
        path = GOLDEN / f"{name}.json"
        if os.environ.get("UPDATE_GOLDEN_REQUESTS") == "1":
            path.write_text(json.dumps(recorded, ensure_ascii=False, indent=2) + "\n")
        assert recorded == json.loads(path.read_text()), name


class TestTruncatedDecision:
    """Un `tool_use` cortado por `max_tokens` trae un `input` a medias: nunca se lee."""

    @pytest.mark.asyncio
    async def test_truncated_reply_is_an_explicit_error_not_a_reply(
        self, fake_deps: AgentDependencies
    ) -> None:
        cut = {"decision": "respond", "confidence": 0.9, "response_text": "Tu pedido sal"}
        _, out = await run_reason(
            fake_deps,
            _reason_state("claude-sonnet-4-6"),
            message(
                tool_use("respond_or_escalate", cut),
                stop_reason="max_tokens",
                model="claude-haiku-4-5-20251001",
            ),
        )

        assert out["error"] == "llm_no_decision: max_tokens"
        assert "agent_response" not in out
        # 100 in @ $1 + 50 out @ $5 (Haiku): la llamada se cobra igual.
        assert out["cost_usd"] == pytest.approx(0.00035)

    @pytest.mark.asyncio
    async def test_truncated_skill_call_is_not_executed(self, fake_deps: AgentDependencies) -> None:
        _, out = await run_reason(
            fake_deps,
            _with_policies(_reason_state("claude-sonnet-4-6"), hops=0),
            message(tool_use("shopify_get_shop_policies", {}), stop_reason="max_tokens"),
        )

        assert out["error"] == "llm_no_decision: max_tokens"
        assert "pending_tool_call" not in out


@pytest.mark.asyncio
async def test_a_failed_nudge_retry_keeps_the_cost_of_the_first_call(
    fake_deps: AgentDependencies, _env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sonnet 4.6 con thinking por rol: sin tool forzada, la primera llamada contesta solo
    texto y el reintento con la instrucción falla. La primera llamada ya se cobró."""
    from apps.api.tests.anthropic_http import api_error

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    _env.setenv("THINKING_BY_ROLE", '{"default_agent_model": "adaptive"}')
    get_models.cache_clear()
    state = _with_policies(_reason_state("claude-sonnet-4-6"), hops=0)

    _, out = await run_reason(
        fake_deps,
        state,
        message(thinking(), text("Te cuento..."), stop_reason="end_turn"),
        *[api_error(500)] * 3,
    )

    assert out["error"] == "llm_no_decision: call_failed (InternalServerError)"
    # 100 in @ $3 + 50 out @ $15 (Sonnet 4.6), solo la primera llamada.
    assert out["cost_usd"] == pytest.approx(0.00105)
    assert out["tokens_out"] == 50


PRESERVED_BETA = "thinking-binding-controls-2026-08-01"
ADAPTIVE = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}


def _assert_valid_5_5_request(body: dict[str, Any], *, decision_tool: str) -> None:
    """Lo que un 5.5 exige: sin tool_choice forzado, sin thinking apagado, esfuerzo
    explícito y la tool de decisión estricta."""
    assert body["tool_choice"] == {"type": "auto"}
    assert body["thinking"] == ADAPTIVE
    assert body["output_config"] == {"effort": "medium"}
    assert body["max_tokens"] >= 16000
    strict = [t for t in body["tools"] if t.get("strict")]
    assert [t["name"] for t in strict] == [decision_tool]
    schema = strict[0]["input_schema"]
    assert schema["additionalProperties"] is False
    assert _keys(schema) & {"minimum", "maximum", "minLength", "maxLength"} == set()


def _keys(schema: Any) -> set[str]:
    if isinstance(schema, dict):
        return set(schema) | {k for v in schema.values() for k in _keys(v)}
    if isinstance(schema, list):
        return {k for v in schema for k in _keys(v)}
    return set()


@pytest.mark.asyncio
async def test_the_turn_clock_is_read_once_so_the_system_does_not_change_between_hops(
    fake_deps: AgentDependencies, _env: pytest.MonkeyPatch
) -> None:
    """Con thinking preservado, un system distinto entre vueltas invalida los thinking blocks
    replayados. La hora del turno se fija en la primera vuelta."""
    minutes = iter(["10:00", "10:01"])
    _env.setattr(
        "apps.api.agents.nodes.reason._tenant_now_str",
        lambda _facts: f"2026-10-17 {next(minutes)} (Europe/Madrid)",
    )
    first_hop, first = await run_reason(
        fake_deps,
        _with_policies(_reason_state("claude-opus-5-5"), hops=0),
        message(thinking(), tool_use("shopify_get_shop_policies", {}, id="toolu_hop0")),
    )
    next_state = {**_with_policies(_reason_state("claude-opus-5-5"), hops=1), **first}
    next_state.pop("pending_tool_call")
    second_hop, _ = await run_reason(
        fake_deps, next_state, message(tool_use("respond_or_escalate", RESPOND))
    )

    assert first["turn_now"] == "2026-10-17 10:00 (Europe/Madrid)"
    assert second_hop.requests[0]["system"] == first_hop.requests[0]["system"]


class TestReasonOn55:
    @pytest.mark.asyncio
    async def test_request_is_valid_and_thinking_then_decision_is_read(
        self, fake_deps: AgentDependencies
    ) -> None:
        state = _with_policies(_reason_state("claude-opus-5-5"), hops=0)
        api, out = await run_reason(
            fake_deps,
            state,
            message(thinking(), tool_use("respond_or_escalate", RESPOND), model="claude-opus-5-5"),
        )

        body = api.requests[0]
        _assert_valid_5_5_request(body, decision_tool="respond_or_escalate")
        assert api.beta_headers == [PRESERVED_BETA]
        assert "respond_or_escalate" in body["system"][-1]["text"]
        assert out["decision"] == "respond"
        assert out["agent_response"] == "Tardan 3 días."
        assert out["model_used"] == "claude-opus-5-5"
        # 100 in @ $4 + 50 out @ $20
        assert out["cost_usd"] == pytest.approx(0.0014)

    @pytest.mark.asyncio
    async def test_skill_call_replays_its_thinking_on_the_next_hop(
        self, fake_deps: AgentDependencies
    ) -> None:
        state = _with_policies(_reason_state("claude-sonnet-5-5"), hops=0)
        _, first = await run_reason(
            fake_deps,
            state,
            message(
                thinking("sig_hop0"),
                tool_use("shopify_get_shop_policies", {}, id="toolu_hop0"),
                model="claude-sonnet-5-5",
            ),
        )
        assert first["pending_tool_call"]["slug"] == POLICIES

        next_state = _with_policies(_reason_state("claude-sonnet-5-5"), hops=1)
        next_state["tool_use_thinking"] = first["tool_use_thinking"]
        api, _ = await run_reason(
            fake_deps,
            next_state,
            message(tool_use("respond_or_escalate", RESPOND), model="claude-sonnet-5-5"),
        )

        assistant = api.requests[0]["messages"][-2]
        assert assistant == {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig_hop0"},
                {
                    "type": "tool_use",
                    "id": "toolu_hop0",
                    "name": "shopify_get_shop_policies",
                    "input": {},
                },
            ],
        }

    @pytest.mark.asyncio
    async def test_exhausted_iterations_steer_to_the_decide_tool(
        self, fake_deps: AgentDependencies
    ) -> None:
        state = _with_policies(_reason_state("claude-opus-5-5"), hops=3)
        api, out = await run_reason(
            fake_deps,
            state,
            message(tool_use("respond_or_escalate", RESPOND), model="claude-opus-5-5"),
        )
        body = api.requests[0]
        assert body["tool_choice"] == {"type": "auto"}
        assert "`respond_or_escalate`" in body["system"][-1]["text"]
        assert out["decision"] == "respond"

    @pytest.mark.asyncio
    async def test_refusal_escalates_with_its_category_and_charges_the_call(
        self, fake_deps: AgentDependencies, caplog: pytest.LogCaptureFixture
    ) -> None:
        state = _with_policies(_reason_state("claude-opus-5-5"), hops=0)
        with caplog.at_level("ERROR"):
            api, out = await run_reason(fake_deps, state, refusal("cyber"))

        assert len(api.requests) == 1
        assert out["error"] == "llm_refusal: cyber"
        assert out["cost_usd"] == pytest.approx(0.0014)
        assert any("llm_refusal" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_text_without_tool_retries_once_with_a_nudge(
        self, fake_deps: AgentDependencies
    ) -> None:
        state = _with_policies(_reason_state("claude-opus-5-5"), hops=0)
        api, out = await run_reason(
            fake_deps,
            state,
            message(
                thinking(), text("Te cuento..."), stop_reason="end_turn", model="claude-opus-5-5"
            ),
            message(tool_use("respond_or_escalate", RESPOND), model="claude-opus-5-5"),
        )

        assert len(api.requests) == 2
        first, retry = api.requests
        assert retry["messages"][: len(first["messages"])] == first["messages"]
        assert retry["messages"][-2] == {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig_1"},
                {"type": "text", "text": "Te cuento..."},
            ],
        }
        assert retry["messages"][-1]["role"] == "user"
        assert out["decision"] == "respond"
        # Dos llamadas cobradas: 2 x (100 in @ $4 + 50 out @ $20)
        assert out["cost_usd"] == pytest.approx(0.0028)

    @pytest.mark.asyncio
    async def test_no_tool_after_the_retry_is_an_explicit_error(
        self, fake_deps: AgentDependencies
    ) -> None:
        state = _with_policies(_reason_state("claude-opus-5-5"), hops=0)
        no_tool = message(text("..."), stop_reason="end_turn", model="claude-opus-5-5")
        api, out = await run_reason(fake_deps, state, no_tool, no_tool)

        assert len(api.requests) == 2
        assert out["error"] == "llm_no_decision: tool_not_called (end_turn)"


class TestTenantModelIncompatibleWithRoleSettings:
    """El thinking/esfuerzo por rol se valida al cargar contra el modelo del rol, no contra
    el `agent_model` que fije un tenant. Un tenant incompatible no escala cada turno: la
    petición degrada al ajuste por defecto de su modelo y queda un error."""

    @pytest.mark.asyncio
    async def test_opus_5_5_with_thinking_off_by_role_degrades_to_its_default(
        self,
        fake_deps: AgentDependencies,
        _env: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _env.setenv("THINKING_BY_ROLE", '{"default_agent_model": "off"}')
        get_models.cache_clear()
        state = _with_policies(_reason_state("claude-opus-5-5"), hops=0)

        with caplog.at_level("ERROR"):
            api, out = await run_reason(
                fake_deps,
                state,
                message(tool_use("respond_or_escalate", RESPOND), model="claude-opus-5-5"),
            )

        _assert_valid_5_5_request(api.requests[0], decision_tool="respond_or_escalate")
        assert out["decision"] == "respond"
        assert any(
            "model_setting_degraded" in r.getMessage() and "claude-opus-5-5" in r.getMessage()
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_haiku_with_effort_by_role_drops_the_effort(
        self, fake_deps: AgentDependencies, _env: pytest.MonkeyPatch
    ) -> None:
        _env.setenv("EFFORT_BY_ROLE", '{"default_agent_model": "low"}')
        get_models.cache_clear()
        state = _with_policies(_reason_state("claude-haiku-4-5-20251001"), hops=0)

        api, out = await run_reason(
            fake_deps,
            state,
            message(tool_use("respond_or_escalate", RESPOND), model="claude-haiku-4-5-20251001"),
        )

        assert "output_config" not in api.requests[0]
        assert out["decision"] == "respond"


@pytest.mark.asyncio
async def test_between_tools_loop_has_room_for_progress_notes(
    fake_deps: AgentDependencies, _env: pytest.MonkeyPatch
) -> None:
    """Con `between_tools` el modelo escribe notas de progreso (thinking blocks) antes de la
    tool: con 1024 tokens la decisión se cortaba en `NoDecision("max_tokens")`."""
    _env.setenv("THINKING_BY_ROLE", '{"default_agent_model": "off"}')
    get_models.cache_clear()
    state = _with_policies(_reason_state("claude-sonnet-5-5"), hops=0)

    api, _ = await run_reason(
        fake_deps,
        state,
        message(tool_use("respond_or_escalate", RESPOND), model="claude-sonnet-5-5"),
    )

    body = api.requests[0]
    assert body["thinking"] == {"type": "between_tools"}
    assert body["max_tokens"] >= 16000


class TestSelectAopOn55:
    @pytest.mark.asyncio
    async def test_classifier_with_thinking_off_and_low_effort(
        self, fake_deps: AgentDependencies, _env: pytest.MonkeyPatch
    ) -> None:
        _env.setenv("INTENT_CLASSIFIER_MODEL", "claude-sonnet-5-5")
        _env.setenv("THINKING_BY_ROLE", '{"intent_classifier_model": "off"}')
        _env.setenv("EFFORT_BY_ROLE", '{"intent_classifier_model": "low"}')
        get_models.cache_clear()

        api, out = await run_select_aop(
            fake_deps, message(tool_use("select_aop", CLASSIFIED), model="claude-sonnet-5-5")
        )

        body = api.requests[0]
        assert body["model"] == "claude-sonnet-5-5"
        assert body["tool_choice"] == {"type": "auto"}
        assert body["thinking"] == {"type": "between_tools"}
        assert body["output_config"] == {"effort": "low"}
        assert body["tools"][0]["strict"] is True
        assert "`select_aop`" in body["system"]
        assert api.beta_headers == [None]
        assert out["aop_slug"] == "consulta_envio"

    @pytest.mark.asyncio
    async def test_refusal_falls_back_to_the_default_aop(
        self, fake_deps: AgentDependencies, _env: pytest.MonkeyPatch
    ) -> None:
        _env.setenv("INTENT_CLASSIFIER_MODEL", "claude-opus-5-5")
        get_models.cache_clear()

        api, out = await run_select_aop(fake_deps, refusal("general_harms"))

        _assert_valid_5_5_request(api.requests[0], decision_tool="select_aop")
        assert out["aop_slug"] == "default"


class TestSuperviseOn55:
    @pytest.mark.asyncio
    async def test_l3_request_is_valid_and_verdict_is_read(
        self, fake_deps: AgentDependencies, _env: pytest.MonkeyPatch
    ) -> None:
        _env.setenv("SUPERVISOR_MODEL_L3", "claude-opus-5-5")
        get_models.cache_clear()
        state = _supervise_state(
            decision=None,
            agent_response=None,
            pending_tool_call={"id": "toolu_c", "slug": CANCEL, "input": {"order_id": 1}},
        )

        api, out = await run_supervise(
            fake_deps,
            state,
            message(thinking(), tool_use("supervisor_verdict", APPROVE), model="claude-opus-5-5"),
        )

        _assert_valid_5_5_request(api.requests[0], decision_tool="supervisor_verdict")
        assert out["supervisor_verdict"] == "approve"
        assert out["supervisor_model_used"] == "claude-opus-5-5"

    @pytest.mark.asyncio
    async def test_refusal_rejects_and_drops_the_unreviewed_draft(
        self, fake_deps: AgentDependencies, _env: pytest.MonkeyPatch
    ) -> None:
        _env.setenv("SUPERVISOR_MODEL_L1_L2", "claude-sonnet-5-5")
        get_models.cache_clear()

        _, out = await run_supervise(
            fake_deps, _supervise_state(), refusal("cyber", "claude-sonnet-5-5")
        )

        assert out["supervisor_verdict"] == "reject"
        assert out["escalation_reason"] == "supervisor_rejected (structural): llm_refusal: cyber"
        assert out["agent_response"] is None
        # 100 in @ $2 + 50 out @ $10, sobre el 0,01 que ya traía el turno
        assert out["cost_usd"] == pytest.approx(0.0107)


class TestTextRolesOn55:
    """Jueces, simulador y mensajes al cliente: el texto se lee aunque venga tras un
    thinking block, y la petición no lleva lo que un 5.5 rechaza."""

    @pytest.mark.asyncio
    async def test_text_call_on_sonnet_5_5(self, _env: pytest.MonkeyPatch) -> None:
        from apps.api.integrations.anthropic_client import call_claude_text

        _env.setenv("JUDGE_SONNET_MODEL", "claude-sonnet-5-5")
        get_models.cache_clear()
        api = RecordingAnthropic(
            message(
                thinking(), text('{"ok": true}'), stop_reason="end_turn", model="claude-sonnet-5-5"
            )
        )

        reply = await call_claude_text(
            client=api.client,
            role="judge_sonnet_model",
            system="juzga",
            messages=[{"role": "user", "content": "transcript"}],
            max_tokens=1024,
            timeout_seconds=90,
            temperature=0.7,
        )

        body = api.requests[0]
        assert body["thinking"] == ADAPTIVE
        assert body["output_config"] == {"effort": "medium"}
        assert body["max_tokens"] == 16000
        assert "temperature" not in body
        assert api.beta_headers == [PRESERVED_BETA]
        assert reply.text == '{"ok": true}'
        assert reply.usage.output_tokens == 50

    @pytest.mark.asyncio
    async def test_refusal_returns_no_text_and_its_category(
        self, _env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from apps.api.integrations.anthropic_client import call_claude_text

        _env.setenv("REPLY_MODEL", "claude-opus-5-5")
        get_models.cache_clear()
        api = RecordingAnthropic(refusal("bio"))

        with caplog.at_level("ERROR"):
            reply = await call_claude_text(
                client=api.client,
                role="reply_model",
                system="s",
                messages=[{"role": "user", "content": "m"}],
                max_tokens=200,
                timeout_seconds=15,
            )

        assert (reply.text, reply.refusal_category) == ("", "bio")
        assert any("llm_refusal: bio" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_user_simulator_on_sonnet_5_5(self, _env: pytest.MonkeyPatch) -> None:
        from apps.api.simulator.user_simulator import UserSimulator
        from apps.api.tests.simulator.test_user_simulator import _make_profile

        _env.setenv("SIMULATOR_MODEL", "claude-sonnet-5-5")
        get_models.cache_clear()
        reply = '{"message": "vale", "goal_achieved": false, "give_up": false, "internal_reasoning": "ok"}'
        api = RecordingAnthropic(
            message(thinking(), text(reply), stop_reason="end_turn", model="claude-sonnet-5-5")
        )

        turn = await UserSimulator(profile=_make_profile(), anthropic=api.client).next_turn(
            conversation_history=[{"role": "agent", "content": "¿En qué ayudo?"}], turn_number=1
        )

        assert turn.message == "vale"
        assert "temperature" not in api.requests[0]
        assert api.requests[0]["model"] == "claude-sonnet-5-5"

    @pytest.mark.asyncio
    async def test_slow_agent_judge_on_sonnet_5_5(self, _env: pytest.MonkeyPatch) -> None:
        from apps.api.slow_agent.judge import _call_judge
        from apps.api.tests.slow_agent.test_judge import _transcript

        _env.setenv("SLOW_AGENT_MODEL", "claude-sonnet-5-5")
        get_models.cache_clear()
        payload = {"should_propose": False, "confidence": 0.9, "rationale": "bien"}
        api = RecordingAnthropic(
            message(
                thinking(),
                text(json.dumps(payload)),
                stop_reason="end_turn",
                model="claude-sonnet-5-5",
            )
        )

        verdict = await _call_judge(api.client, _transcript(), "slow_agent_model")

        assert verdict.confidence == 0.9
        assert verdict.model_used == "claude-sonnet-5-5"
        assert api.requests[0]["thinking"] == ADAPTIVE

    @pytest.mark.asyncio
    async def test_approval_reply_on_opus_5_5(self, _env: pytest.MonkeyPatch) -> None:
        from apps.api.services.approval_reply import generate_customer_reply

        _env.setenv("REPLY_MODEL", "claude-opus-5-5")
        get_models.cache_clear()
        api = RecordingAnthropic(
            message(
                thinking(),
                text("Listo, pedido cancelado."),
                stop_reason="end_turn",
                model="claude-opus-5-5",
            )
        )

        msg = await generate_customer_reply(api.client, "shopify.cancel_order", success=True)

        assert msg == "Listo, pedido cancelado."
        assert api.requests[0]["output_config"] == {"effort": "medium"}
