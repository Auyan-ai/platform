"""Tests del nodo `reason` — el núcleo del agente.

Mockeamos `call_claude_with_tools` para no tocar la API real.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from apps.api.agents.nodes.reason import make_reason_node
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry


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
        "allowed_skills": [],
        "tool_results": [],
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
        "apps.api.agents.nodes.reason.call_claude_with_tools",
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
        "apps.api.agents.nodes.reason.call_claude_with_tools",
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
            "response_text": "Te paso con un agente humano.",
            "escalation_reason": "customer_requested_human",
        }
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
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
        "apps.api.agents.nodes.reason.call_claude_with_tools",
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
        "apps.api.agents.nodes.reason.call_claude_with_tools",
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
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=FakeResponse()),
    )
    node = make_reason_node(fake_deps)

    out = await node(_base_state())

    assert out.get("error") is not None
    assert "claude_did_not_use_tool" in out["error"]


# ----------------------------------------------------------------
# Loop ReAct: skill tool path
# ----------------------------------------------------------------


class SearchInput(SkillInput):
    query: str


class SearchOutput(SkillOutput):
    hits: int


class FakeSearchSkill(Skill):
    slug = "test.search"
    description = "Searches stuff."
    tier: SkillTier = "L1"
    input_schema = SearchInput
    output_schema = SearchOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        return SearchOutput(hits=0)


@pytest.fixture
def _register_search() -> Generator[None, None, None]:
    SkillRegistry._reset()
    SkillRegistry.register(FakeSearchSkill)
    yield
    SkillRegistry._reset()


@pytest.mark.asyncio
async def test_skill_tool_emits_pending_tool_call(
    fake_deps, make_anthropic_response, monkeypatch, _register_search
) -> None:
    """Si el LLM elige una skill tool, reason emite pending_tool_call sin decision."""
    fake_response = make_anthropic_response(
        {"query": "hola"},
        tool_name="test_search",
        tool_id="toolu_search_001",
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["allowed_skills"] = ["test.search"]
    out = await node(state)

    assert "pending_tool_call" in out
    assert out["pending_tool_call"]["id"] == "toolu_search_001"
    assert out["pending_tool_call"]["slug"] == "test.search"
    assert out["pending_tool_call"]["input"] == {"query": "hola"}
    assert "decision" not in out
    assert out["tokens_in"] == 100
    assert out["tokens_out"] == 50


@pytest.mark.asyncio
async def test_unknown_tool_name_sets_error(
    fake_deps, make_anthropic_response, monkeypatch, _register_search
) -> None:
    """Si el LLM elige un tool name que no mapea a ningún slug permitido → error."""
    fake_response = make_anthropic_response(
        {"x": 1},
        tool_name="not_a_real_tool",
        tool_id="toolu_x",
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["allowed_skills"] = ["test.search"]
    out = await node(state)

    assert "error" in out
    assert "llm_chose_unknown_tool: not_a_real_tool" in out["error"]


@pytest.mark.asyncio
async def test_tokens_accumulate_across_iterations(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """Si el state ya trae tokens de iteraciones previas, los nuevos se suman."""
    fake_response = make_anthropic_response(
        {"decision": "respond", "confidence": 0.9, "response_text": "hola"},
        input_tokens=80,
        output_tokens=40,
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["tokens_in"] = 200
    state["tokens_out"] = 90
    state["cost_usd"] = 0.0123
    out = await node(state)

    assert out["tokens_in"] == 280
    assert out["tokens_out"] == 130
    assert out["cost_usd"] > 0.0123  # se acumuló costo


@pytest.mark.asyncio
async def test_tool_results_appended_to_messages(
    fake_deps, make_anthropic_response, monkeypatch, _register_search
) -> None:
    """Si hay tool_results previos, reason los appendea como bloques tool_use/tool_result."""
    captured_messages: dict = {}

    async def fake_call(**kwargs: object) -> object:
        captured_messages["messages"] = kwargs["messages"]
        return make_anthropic_response(
            {"decision": "respond", "confidence": 0.9, "response_text": "ok"}
        )

    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(side_effect=fake_call),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["allowed_skills"] = ["test.search"]
    state["tool_results"] = [
        {
            "id": "toolu_prev",
            "slug": "test.search",
            "input": {"query": "hola"},
            "output": {"hits": 0},
            "is_error": False,
            "error": None,
        }
    ]
    await node(state)

    msgs = captured_messages["messages"]
    # Mensaje original del cliente + tool_use + tool_result = 3
    assert len(msgs) == 3
    # El segundo mensaje debe ser un assistant con tool_use
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"][0]["type"] == "tool_use"
    assert msgs[1]["content"][0]["id"] == "toolu_prev"
    assert msgs[1]["content"][0]["name"] == "test_search"
    # El tercero debe ser user con tool_result
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"][0]["type"] == "tool_result"
    assert msgs[2]["content"][0]["tool_use_id"] == "toolu_prev"
    assert msgs[2]["content"][0]["is_error"] is False


@pytest.mark.asyncio
async def test_tool_results_with_error_propagate_to_messages(
    fake_deps, make_anthropic_response, monkeypatch, _register_search
) -> None:
    """Tool results con is_error=True deben llevar is_error en el bloque tool_result."""
    captured: dict = {}

    async def fake_call(**kwargs: object) -> object:
        captured["messages"] = kwargs["messages"]
        return make_anthropic_response(
            {"decision": "escalate", "confidence": 0.9, "escalation_reason": "x"}
        )

    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(side_effect=fake_call),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["allowed_skills"] = ["test.search"]
    state["tool_results"] = [
        {
            "id": "toolu_err",
            "slug": "test.search",
            "input": {"query": "x"},
            "output": None,
            "is_error": True,
            "error": "shopify_not_configured",
        }
    ]
    await node(state)

    msgs = captured["messages"]
    tool_result_block = msgs[2]["content"][0]
    assert tool_result_block["is_error"] is True
    assert tool_result_block["content"] == "shopify_not_configured"


@pytest.mark.asyncio
async def test_tools_list_includes_decide_and_allowed_skills(
    fake_deps, make_anthropic_response, monkeypatch, _register_search
) -> None:
    """La lista de tools que llega al cliente debe incluir el decide tool + skills permitidas."""
    captured: dict = {}

    async def fake_call(**kwargs: object) -> object:
        captured["tools"] = kwargs["tools"]
        captured["tool_choice"] = kwargs["tool_choice"]
        return make_anthropic_response(
            {"decision": "respond", "confidence": 0.9, "response_text": "x"}
        )

    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(side_effect=fake_call),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["allowed_skills"] = ["test.search"]
    await node(state)

    tools = captured["tools"]
    tool_names = [t["name"] for t in tools]
    assert "respond_or_escalate" in tool_names
    assert "test_search" in tool_names
    assert captured["tool_choice"] == {"type": "any"}


@pytest.mark.asyncio
async def test_tools_list_skips_unregistered_skills(
    fake_deps, make_anthropic_response, monkeypatch, _register_search
) -> None:
    """Si allowed_skills incluye un slug no registrado, se omite con warning (no falla)."""
    captured: dict = {}

    async def fake_call(**kwargs: object) -> object:
        captured["tools"] = kwargs["tools"]
        return make_anthropic_response(
            {"decision": "respond", "confidence": 0.9, "response_text": "x"}
        )

    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(side_effect=fake_call),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["allowed_skills"] = ["test.search", "test.ghost"]
    out = await node(state)

    # No error — solo skip silencioso del slug fantasma
    assert "error" not in out
    tool_names = [t["name"] for t in captured["tools"]]
    assert "test_search" in tool_names
    assert "test_ghost" not in tool_names


# ----------------------------------------------------------------
# AOP steps[] — step_entered / step_completed events
# ----------------------------------------------------------------

SAMPLE_STEPS = [
    {"id": "gather_info", "name": "Recopilar información", "decision_point": "¿Email disponible?"},
    {"id": "resolve", "name": "Resolver consulta", "decision_point": "¿Podemos responder?"},
]


@pytest.mark.asyncio
async def test_step_entered_emitted_on_first_iteration(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """Cuando el AOP tiene steps[], emite step_entered para el step de la iteración actual."""
    fake_response = make_anthropic_response(
        {"decision": "respond", "confidence": 0.92, "response_text": "Listo."}
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["aop_steps"] = SAMPLE_STEPS
    await node(state)

    tracker = fake_deps.reasoning_tracker
    entered = [e for e in tracker.events if e["event_type"] == "step_entered"]
    assert len(entered) == 1
    assert entered[0]["label"] == "gather_info"
    assert entered[0]["detail"]["step_name"] == "Recopilar información"
    assert entered[0]["detail"]["iteration"] == 0


@pytest.mark.asyncio
async def test_step_entered_uses_iteration_index(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """Segunda iteración (tool_iterations=1) usa el segundo step."""
    fake_response = make_anthropic_response(
        {"decision": "respond", "confidence": 0.92, "response_text": "Listo."}
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["aop_steps"] = SAMPLE_STEPS
    state["tool_iterations"] = 1  # segunda iteración del loop
    await node(state)

    tracker = fake_deps.reasoning_tracker
    entered = [e for e in tracker.events if e["event_type"] == "step_entered"]
    assert len(entered) == 1
    assert entered[0]["label"] == "resolve"
    assert entered[0]["detail"]["iteration"] == 1


@pytest.mark.asyncio
async def test_no_step_events_when_iteration_exceeds_steps(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """Si tool_iterations >= len(steps), no se emiten step events (degradación elegante)."""
    fake_response = make_anthropic_response(
        {"decision": "respond", "confidence": 0.92, "response_text": "Listo."}
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["aop_steps"] = SAMPLE_STEPS  # 2 steps
    state["tool_iterations"] = 5  # más iteraciones que steps
    await node(state)

    tracker = fake_deps.reasoning_tracker
    step_events = [e for e in tracker.events if e["event_type"] in ("step_entered", "step_completed")]
    assert step_events == []


@pytest.mark.asyncio
async def test_step_completed_emitted_on_decide_tool(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """Cuando el LLM llama el decide tool, se emite step_completed con el outcome."""
    fake_response = make_anthropic_response(
        {"decision": "respond", "confidence": 0.92, "response_text": "Listo."}
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["aop_steps"] = SAMPLE_STEPS
    await node(state)

    tracker = fake_deps.reasoning_tracker
    completed = [e for e in tracker.events if e["event_type"] == "step_completed"]
    assert len(completed) == 1
    assert completed[0]["label"] == "gather_info"
    assert completed[0]["detail"]["outcome"] == "respond"


@pytest.mark.asyncio
async def test_step_completed_emitted_on_skill_call(
    fake_deps, make_anthropic_response, monkeypatch, _register_search
) -> None:
    """Cuando el LLM elige una skill tool, step_completed emite outcome=tool:<slug>."""
    fake_response = make_anthropic_response(
        {"query": "pedido 123"},
        tool_name="test_search",
        tool_id="toolu_search_002",
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["allowed_skills"] = ["test.search"]
    state["aop_steps"] = SAMPLE_STEPS
    await node(state)

    tracker = fake_deps.reasoning_tracker
    completed = [e for e in tracker.events if e["event_type"] == "step_completed"]
    assert len(completed) == 1
    assert completed[0]["label"] == "gather_info"
    assert completed[0]["detail"]["outcome"] == "tool:test.search"


@pytest.mark.asyncio
async def test_no_step_events_without_aop_steps(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """Sin aop_steps en el state, no se emiten step_entered ni step_completed."""
    fake_response = make_anthropic_response(
        {"decision": "respond", "confidence": 0.92, "response_text": "Listo."}
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    # state sin aop_steps
    out = await node(_base_state())
    assert out["decision"] == "respond"

    tracker = fake_deps.reasoning_tracker
    step_events = [e for e in tracker.events if e["event_type"] in ("step_entered", "step_completed")]
    assert step_events == []
