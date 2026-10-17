"""Tests del nodo `reason` — el núcleo del agente.

Mockeamos `call_claude_with_tools` para no tocar la API real.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from anthropic.types import Usage
from apps.api.agents.nodes.reason import make_reason_node
from apps.api.services.fixed_texts import fixed_text
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


def _allow(state: dict, *slugs: str) -> None:
    """El AOP permite estas skills y el tenant las tiene encendidas."""
    state["allowed_skills"] = list(slugs)
    state["tool_permissions"] = {slug: {"is_enabled": True} for slug in slugs}


def test_tenant_now_str_uses_tenant_timezone() -> None:
    import re

    from apps.api.agents.nodes.reason import _tenant_now_str

    out = _tenant_now_str({"timezone": "Europe/Madrid"})
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} \(Europe/Madrid\)$", out)


def test_tenant_now_str_respects_other_valid_tz() -> None:
    from apps.api.agents.nodes.reason import _tenant_now_str

    assert "(America/Caracas)" in _tenant_now_str({"timezone": "America/Caracas"})


def test_tenant_now_str_defaults_when_missing() -> None:
    from apps.api.agents.nodes.reason import _tenant_now_str

    assert "(Europe/Madrid)" in _tenant_now_str(None)
    assert "(Europe/Madrid)" in _tenant_now_str({})


def test_tenant_now_str_invalid_tz_falls_back_to_default() -> None:
    from apps.api.agents.nodes.reason import _tenant_now_str

    assert "(Europe/Madrid)" in _tenant_now_str({"timezone": "Mars/Phobos"})


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
    # _base_state es un turno conversacional puro (sin skills ni tool_results) →
    # el router usa el modelo rápido. Ver TestSelectReasonModel.
    assert out["model_used"] == "claude-haiku-4-5-20251001"


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


# ──────────────────────────────────────────────────────────
# _select_reason_model — router por complejidad (palanca de latencia c)
# ──────────────────────────────────────────────────────────


class TestSelectReasonModel:
    """Haiku SOLO en turnos sin riesgo: AOP sin skills, sin tool_results previos
    y sin pending_tool_call → el único desenlace posible es respond/escalate puro.
    Apenas el turno pueda tocar una herramienta, se usa el modelo del tenant."""

    def _fn(self, state: dict) -> str:
        from apps.api.agents.nodes.reason import _select_reason_model

        return _select_reason_model(state)  # type: ignore[arg-type]

    def test_simple_turn_uses_fast_model(self) -> None:
        model = self._fn(
            {
                "model_used": "claude-sonnet-4-6",
                "allowed_skills": [],
                "tool_results": [],
            }
        )
        assert model == "claude-haiku-4-5-20251001"

    def test_aop_with_skills_uses_tenant_model(self, _register_search: None) -> None:
        model = self._fn(
            {
                "model_used": "claude-sonnet-4-6",
                "allowed_skills": ["test.search"],
                "tool_permissions": {"test.search": {"is_enabled": True}},
                "tool_results": [],
            }
        )
        assert model == "claude-sonnet-4-6"

    def test_aop_with_only_switched_off_skills_is_a_simple_turn(
        self, _register_search: None
    ) -> None:
        model = self._fn(
            {
                "model_used": "claude-sonnet-4-6",
                "allowed_skills": ["test.search"],
                "tool_permissions": {"test.search": {"is_enabled": False}},
                "tool_results": [],
            }
        )
        assert model == "claude-haiku-4-5-20251001"

    def test_prior_tool_results_force_tenant_model(self) -> None:
        # Venimos de un hop del loop ReAct: aunque el AOP no tenga skills ahora,
        # el turno ya tocó una herramienta → no degradar.
        model = self._fn(
            {
                "model_used": "claude-sonnet-4-6",
                "allowed_skills": [],
                "tool_results": [{"slug": "x", "is_error": False}],
            }
        )
        assert model == "claude-sonnet-4-6"

    def test_pending_tool_call_forces_tenant_model(self) -> None:
        model = self._fn(
            {
                "model_used": "claude-sonnet-4-6",
                "allowed_skills": [],
                "tool_results": [],
                "pending_tool_call": {"slug": "x", "input": {}},
            }
        )
        assert model == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_simple_turn_calls_claude_with_fast_model(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """Integración: un turno conversacional puro llama a Claude con el modelo rápido
    y reporta ese modelo en model_used (para que el costo se compute correcto)."""
    fake_response = make_anthropic_response(
        {"decision": "respond", "confidence": 0.95, "response_text": "¡De nada!"}
    )
    mock_call = AsyncMock(return_value=fake_response)
    monkeypatch.setattr("apps.api.agents.nodes.reason.call_claude_with_tools", mock_call)
    node = make_reason_node(fake_deps)

    out = await node(_base_state())  # allowed_skills=[], tool_results=[]

    assert mock_call.await_args.kwargs["model"] == "claude-haiku-4-5-20251001"
    assert out["model_used"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_per_aop_confidence_threshold_overrides_tenant(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """El umbral por-AOP (más estricto) manda sobre el escalation_threshold global."""
    fake_response = make_anthropic_response(
        {
            "decision": "respond",
            "confidence": 0.75,  # ≥ tenant 0.70 (respondería) pero < AOP 0.78 (escala)
            "response_text": "respuesta tentativa",
        }
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["aop_confidence_threshold"] = 0.78
    out = await node(state)

    assert out["decision"] == "escalate"
    assert out["agent_response"] is None
    assert "0.78" in (out["escalation_reason"] or "")


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
    fake_response = make_anthropic_response({"decision": "respond", "confidence": 0.9})
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
    _allow(state, "test.search")
    out = await node(state)

    assert "pending_tool_call" in out
    assert out["pending_tool_call"]["id"] == "toolu_search_001"
    assert out["pending_tool_call"]["slug"] == "test.search"
    assert out["pending_tool_call"]["input"] == {"query": "hola"}
    # "Sin decisión" se expresa como None explícito (anula residuos de pasadas
    # anteriores en el merge de LangGraph), no como key ausente.
    assert out["decision"] is None
    assert out["tokens_in"] == 100
    assert out["tokens_out"] == 50


@pytest.mark.asyncio
async def test_decide_tool_clears_stale_pending_tool_call(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """Retry post-rechazo del supervisor: la pasada anterior dejó una tool
    pendiente y en el retry el LLM usa el decide tool. El parche debe anular
    pending_tool_call — LangGraph solo pisa las keys presentes, así que sin el
    None explícito route_after_reason prioriza la tool residual y ejecuta la
    acción que el supervisor rechazó (sin re-supervisión, porque
    supervisor_retried=True desactiva needs_supervision)."""
    fake_response = make_anthropic_response(
        {
            "decision": "respond",
            "confidence": 0.92,
            "response_text": "¿Me confirmas la dirección de envío?",
        }
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["pending_tool_call"] = {
        "id": "toolu_rejected",
        "slug": "test.search",
        "input": {"query": "stale"},
    }
    state["supervisor_retried"] = True
    out = await node(state)

    assert out["decision"] == "respond"
    assert out["pending_tool_call"] is None


@pytest.mark.asyncio
async def test_skill_tool_clears_stale_decision_fields(
    fake_deps, make_anthropic_response, monkeypatch, _register_search
) -> None:
    """Espejo del caso anterior: la pasada rechazada fue una decisión
    (respond/escalate) y en el retry el LLM pide una skill. El parche debe
    anular decision/agent_response/escalation_reason — si el turno muere por
    max_tool_iterations, escalate reenviaría al cliente el agent_response que
    el supervisor rechazó."""
    fake_response = make_anthropic_response(
        {"query": "pedido 1234"},
        tool_name="test_search",
        tool_id="toolu_search_002",
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    _allow(state, "test.search")
    state["decision"] = "respond"
    state["agent_response"] = "respuesta que el supervisor rechazó"
    state["escalation_reason"] = "low_confidence previa"
    state["supervisor_retried"] = True
    out = await node(state)

    assert out["pending_tool_call"]["slug"] == "test.search"
    assert out["decision"] is None
    assert out["agent_response"] is None
    assert out["escalation_reason"] is None


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
    _allow(state, "test.search")
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
async def test_cached_prompt_counts_in_tokens_and_cost(
    fake_deps, make_anthropic_response, monkeypatch
) -> None:
    """El prefijo leído de caché suma a tokens_in y se cobra a la tarifa de lectura (#331)."""
    fake_response = make_anthropic_response(
        {"decision": "respond", "confidence": 0.9, "response_text": "hola"}
    )
    fake_response.usage = Usage.model_validate(
        {
            "input_tokens": 1684,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 3426,
            "output_tokens": 166,
        }
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=fake_response),
    )
    node = make_reason_node(fake_deps)

    state = _base_state()
    state["tokens_in"] = 1000
    state["tokens_cache_read"] = 400
    out = await node(state)

    assert out["model_used"] == "claude-haiku-4-5-20251001"
    assert out["tokens_in"] == 1000 + 1684 + 3426
    assert out["tokens_cache_read"] == 400 + 3426
    assert out["tokens_cache_write"] == 0
    # Haiku 4.5: 1684 @ $1 + 3426 @ $0.10 + 166 @ $5 = $0.0028566
    assert out["cost_usd"] == pytest.approx(0.0028566)


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
    _allow(state, "test.search")
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
    _allow(state, "test.search")
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
    _allow(state, "test.search")
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
    _allow(state, "test.search", "test.ghost")
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
    step_events = [
        e for e in tracker.events if e["event_type"] in ("step_entered", "step_completed")
    ]
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
    _allow(state, "test.search")
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
    step_events = [
        e for e in tracker.events if e["event_type"] in ("step_entered", "step_completed")
    ]
    assert step_events == []


class TestIterationsExhausted:
    """Agotado `max_tool_iterations`, `reason` tiene un último turno forzado a decidir."""

    @staticmethod
    def _exhausted_state() -> dict:
        return {
            **_base_state(),
            "allowed_skills": ["shopify.get_order_status"],
            "tool_iterations": 4,
            "max_tool_iterations": 4,
        }

    @pytest.mark.asyncio
    async def test_forces_decide_tool_and_uses_its_answer(
        self, fake_deps, make_anthropic_response, monkeypatch
    ) -> None:
        call = AsyncMock(
            return_value=make_anthropic_response(
                {
                    "decision": "escalate",
                    "confidence": 0.9,
                    "response_text": "Siento mucho lo del bolso. Lo paso al equipo ya.",
                    "escalation_reason": "Producto dañado, segunda incidencia",
                }
            )
        )
        monkeypatch.setattr("apps.api.agents.nodes.reason.call_claude_with_tools", call)

        out = await make_reason_node(fake_deps)(self._exhausted_state())

        from apps.api.agents.nodes.reason import DECIDE_TOOL_NAME

        assert call.await_args.kwargs["tool_choice"] == {
            "type": "tool",
            "name": DECIDE_TOOL_NAME,
        }
        assert out["decision"] == "escalate"
        assert "max_tool_iterations" not in (out.get("escalation_reason") or "")

    @pytest.mark.asyncio
    async def test_normal_turn_keeps_tool_choice_any(
        self, fake_deps, make_anthropic_response, monkeypatch
    ) -> None:
        call = AsyncMock(
            return_value=make_anthropic_response(
                {"decision": "respond", "confidence": 0.9, "response_text": "ok"}
            )
        )
        monkeypatch.setattr("apps.api.agents.nodes.reason.call_claude_with_tools", call)
        await make_reason_node(fake_deps)({**self._exhausted_state(), "tool_iterations": 1})
        assert call.await_args.kwargs["tool_choice"] == {"type": "any"}

    @pytest.mark.asyncio
    async def test_skill_call_despite_forcing_escalates_with_courtesy(
        self, fake_deps, monkeypatch
    ) -> None:

        from tests.conftest import FakeAnthropicResponse

        monkeypatch.setattr(
            "apps.api.agents.nodes.reason.call_claude_with_tools",
            AsyncMock(
                return_value=FakeAnthropicResponse(
                    {"order_identifier": "#1"},
                    tool_name="shopify_get_order_status",
                    tool_id="toolu_x",
                )
            ),
        )

        out = await make_reason_node(fake_deps)(self._exhausted_state())

        assert out["decision"] == "escalate"
        assert out["escalation_reason"] == "max_tool_iterations_exceeded (4/4)"
        assert out["agent_response"] == fixed_text("iterations_exhausted", "es")
        assert out["pending_tool_call"] is None


    @pytest.mark.asyncio
    async def test_courtesy_message_speaks_the_conversation_language(
        self, fake_deps, monkeypatch
    ) -> None:
        from tests.conftest import FakeAnthropicResponse

        monkeypatch.setattr(
            "apps.api.agents.nodes.reason.call_claude_with_tools",
            AsyncMock(
                return_value=FakeAnthropicResponse(
                    {"order_identifier": "#1"},
                    tool_name="shopify_get_order_status",
                    tool_id="toolu_x",
                )
            ),
        )

        out = await make_reason_node(fake_deps)(
            {**self._exhausted_state(), "response_language": "en"}
        )

        assert out["agent_response"] == fixed_text("iterations_exhausted", "en")
        assert out["agent_response"].startswith("Thanks for writing to us")
