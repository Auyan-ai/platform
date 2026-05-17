"""Tests del nodo select_aop (Sprint 7.3/7.4)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from apps.api.agents.nodes.select_aop import (
    _format_history,
    _should_reclassify,
    _turn_number,
    make_select_aop_node,
)
from apps.api.db.models import AopWithContent
from apps.api.tests.conftest import (
    CONVERSATION_ID,
    TENANT_ID,
    make_tenant_configuration,
)

AOP_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

CONSULTA_ENVIO = AopWithContent(
    id=AOP_ID,
    tenant_id=TENANT_ID,
    slug="consulta_envio",
    workspace="production",
    current_version=1,
    yaml_frontmatter={
        "name": "Consulta de envío",
        "slug": "consulta_envio",
        "workspace": "production",
        "allowed_skills": ["shopify.get_order_by_email"],
        "triggers": {"description": "El cliente pregunta por su pedido"},
        "max_tool_iterations": 3,
        "confidence_threshold": 0.70,
        "require_supervision": False,
        "escalation_triggers": [],
    },
    body_markdown="Busca el pedido del cliente.",
    raw_source="",
)

DEFAULT_AOP = AopWithContent(
    id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    tenant_id=TENANT_ID,
    slug="default",
    workspace="production",
    current_version=1,
    yaml_frontmatter={
        "name": "Procedimiento por defecto",
        "slug": "default",
        "workspace": "production",
        "allowed_skills": [],
        "triggers": {"description": "Cualquier consulta no cubierta por otros procedimientos"},
        "max_tool_iterations": 3,
        "confidence_threshold": 0.70,
        "require_supervision": False,
        "escalation_triggers": [],
    },
    body_markdown="Responde con la información disponible.",
    raw_source="",
)

TENANT_CONFIG_DICT = make_tenant_configuration().model_dump(mode="json")

BASE_STATE: dict = {
    "tenant_id": str(TENANT_ID),
    "conversation_id": str(CONVERSATION_ID),
    "inbound_message_content": "¿Dónde está mi pedido?",
    "conversation_history": [],
    "tenant_config": TENANT_CONFIG_DICT,
    "langfuse_trace_id": "trace-fake-001",
}


def _make_classifier_response(
    slug: str = "consulta_envio",
    confidence: float = 0.92,
    alt_slug: str | None = None,
    alt_confidence: float | None = None,
    ambiguity: bool = False,
) -> MagicMock:
    """Simula la respuesta de Haiku con tool_use."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = {
        "primary": {"slug": slug, "confidence": confidence},
        "reasoning": "El cliente pregunta por su pedido.",
        "ambiguity_detected": ambiguity,
    }
    if alt_slug and alt_confidence is not None:
        tool_block.input["alternative"] = {"slug": alt_slug, "confidence": alt_confidence}
    response = MagicMock()
    response.content = [tool_block]
    return response


def _make_fake_tenant_scope(conn: Any = None) -> Any:
    if conn is None:
        conn = AsyncMock()

    @asynccontextmanager
    async def _scope(tid: UUID) -> Any:
        yield conn

    return _scope


# ─── _should_reclassify ──────────────────────────────────────────────────────


def test_should_reclassify_first_turn_no_aop_slug() -> None:
    assert _should_reclassify({}) is True


def test_should_reclassify_first_turn_empty_slug() -> None:
    assert _should_reclassify({"aop_slug": ""}) is True


def test_should_reclassify_false_when_aop_already_set() -> None:
    assert _should_reclassify({"aop_slug": "consulta_envio"}) is False


def test_should_reclassify_true_when_completed_signal() -> None:
    assert _should_reclassify({"aop_slug": "consulta_envio", "aop_completed_signal": True}) is True


def test_should_reclassify_false_when_locked() -> None:
    history = [{"role": "customer", "content": "msg"}]
    state = {
        "aop_slug": "cancelacion",
        "aop_locked_until_turn": 3,
        "conversation_history": history,
    }
    assert _should_reclassify(state) is False


def test_should_reclassify_true_when_lock_expired() -> None:
    history = [{"role": "customer"}, {"role": "customer"}, {"role": "customer"}]
    state = {
        "aop_slug": "cancelacion",
        "aop_locked_until_turn": 2,
        "conversation_history": history,
    }
    assert _should_reclassify(state) is True


# ─── _format_history ─────────────────────────────────────────────────────────


def test_format_history_empty() -> None:
    result = _format_history([])
    assert "sin historial" in result.lower()


def test_format_history_shows_roles() -> None:
    history = [
        {"role": "customer", "content": "Hola"},
        {"role": "agent_ai", "content": "Buenas"},
    ]
    result = _format_history(history)
    assert "Cliente" in result
    assert "Agente" in result


def test_format_history_max_3_messages() -> None:
    history = [{"role": "customer", "content": str(i)} for i in range(10)]
    result = _format_history(history)
    assert "7" in result
    assert "8" in result
    assert "9" in result
    assert "0" not in result.split(":")[-1]


def test_format_history_truncates_long_content() -> None:
    long_msg = "x" * 300
    result = _format_history([{"role": "customer", "content": long_msg}])
    assert len(result) < 300


# ─── _turn_number ────────────────────────────────────────────────────────────


def test_turn_number_empty_history() -> None:
    assert _turn_number({}) == 0


def test_turn_number_counts_customer_messages() -> None:
    state = {
        "conversation_history": [
            {"role": "customer"},
            {"role": "agent_ai"},
            {"role": "customer"},
        ]
    }
    assert _turn_number(state) == 2


# ─── make_select_aop_node ────────────────────────────────────────────────────


@pytest.fixture
def fake_deps(fake_anthropic: AsyncMock, fake_openai: AsyncMock, fake_settings: Any) -> Any:
    from apps.api.agents.dependencies import AgentDependencies

    return AgentDependencies(
        anthropic=fake_anthropic,
        openai=fake_openai,
        settings=fake_settings,
    )


@pytest.mark.asyncio
async def test_select_aop_no_reclassify_when_locked(fake_deps: Any) -> None:
    """Si el AOP está locked, el nodo devuelve {} sin tocar la DB ni llamar a LLM."""
    node = make_select_aop_node(fake_deps)
    state = {
        **BASE_STATE,
        "aop_slug": "cancelacion",
        "aop_locked_until_turn": 5,
        "conversation_history": [{"role": "customer", "content": "x"}],
    }
    result = await node(state)
    assert result == {}
    fake_deps.anthropic.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_select_aop_returns_empty_when_no_aops(fake_deps: Any) -> None:
    """Sin AOPs configurados, el nodo es un no-op (degradación elegante)."""
    node = make_select_aop_node(fake_deps)
    fake_conn = AsyncMock()

    with patch("apps.api.agents.nodes.select_aop.tenant_scope", _make_fake_tenant_scope(fake_conn)), \
         patch("apps.api.agents.nodes.select_aop.load_active_aops", return_value=[]):
        result = await node(BASE_STATE)

    assert result == {}


@pytest.mark.asyncio
async def test_select_aop_happy_path(fake_deps: Any) -> None:
    """Clasificación exitosa: devuelve aop_slug, system_prompt y allowed_skills."""
    node = make_select_aop_node(fake_deps)
    fake_conn = AsyncMock()
    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_classifier_response("consulta_envio", 0.92)
    )

    with patch("apps.api.agents.nodes.select_aop.tenant_scope", _make_fake_tenant_scope(fake_conn)), \
         patch("apps.api.agents.nodes.select_aop.load_active_aops", return_value=[CONSULTA_ENVIO, DEFAULT_AOP]), \
         patch("apps.api.agents.nodes.select_aop.load_aop", return_value=CONSULTA_ENVIO), \
         patch("apps.api.agents.nodes.select_aop.insert_intent_classifier_run", return_value=AsyncMock()):
        result = await node(BASE_STATE)

    assert result["aop_slug"] == "consulta_envio"
    assert result["aop_version"] == 1
    assert result["intent_confidence"] == 0.92
    assert "system_prompt" in result
    assert result["allowed_skills"] == ["shopify.get_order_by_email"]
    assert result["max_tool_iterations"] == 3


@pytest.mark.asyncio
async def test_select_aop_falls_back_to_default_on_low_confidence(fake_deps: Any) -> None:
    """Confidence < intent_min_confidence → selecciona el AOP 'default'."""
    node = make_select_aop_node(fake_deps)
    fake_conn = AsyncMock()
    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_classifier_response("consulta_envio", 0.30)
    )

    with patch("apps.api.agents.nodes.select_aop.tenant_scope", _make_fake_tenant_scope(fake_conn)), \
         patch("apps.api.agents.nodes.select_aop.load_active_aops", return_value=[CONSULTA_ENVIO, DEFAULT_AOP]), \
         patch("apps.api.agents.nodes.select_aop.load_aop", return_value=DEFAULT_AOP) as mock_load, \
         patch("apps.api.agents.nodes.select_aop.insert_intent_classifier_run", return_value=AsyncMock()):
        result = await node(BASE_STATE)

    mock_load.assert_called_once()
    load_args = mock_load.call_args
    assert load_args[0][2] == "default" or load_args[1].get("slug") == "default" or "default" in str(load_args)
    assert result["aop_slug"] == "default"


@pytest.mark.asyncio
async def test_select_aop_falls_back_when_slug_not_in_catalog(fake_deps: Any) -> None:
    """El clasificador devuelve un slug que no está en el catálogo → fallback a default."""
    node = make_select_aop_node(fake_deps)
    fake_conn = AsyncMock()
    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_classifier_response("slug_inventado", 0.95)
    )

    with patch("apps.api.agents.nodes.select_aop.tenant_scope", _make_fake_tenant_scope(fake_conn)), \
         patch("apps.api.agents.nodes.select_aop.load_active_aops", return_value=[CONSULTA_ENVIO, DEFAULT_AOP]), \
         patch("apps.api.agents.nodes.select_aop.load_aop", return_value=DEFAULT_AOP), \
         patch("apps.api.agents.nodes.select_aop.insert_intent_classifier_run", return_value=AsyncMock()):
        result = await node(BASE_STATE)

    assert result["aop_slug"] == "default"


@pytest.mark.asyncio
async def test_select_aop_returns_empty_when_default_aop_missing(fake_deps: Any) -> None:
    """Si el AOP default tampoco existe, no-op."""
    node = make_select_aop_node(fake_deps)
    fake_conn = AsyncMock()
    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_classifier_response("consulta_envio", 0.20)
    )

    with patch("apps.api.agents.nodes.select_aop.tenant_scope", _make_fake_tenant_scope(fake_conn)), \
         patch("apps.api.agents.nodes.select_aop.load_active_aops", return_value=[CONSULTA_ENVIO]), \
         patch("apps.api.agents.nodes.select_aop.load_aop", return_value=None), \
         patch("apps.api.agents.nodes.select_aop.insert_intent_classifier_run", return_value=AsyncMock()):
        result = await node(BASE_STATE)

    assert result == {}


@pytest.mark.asyncio
async def test_select_aop_persists_classifier_run(fake_deps: Any) -> None:
    """Se persiste el classifier run en DB."""
    node = make_select_aop_node(fake_deps)
    fake_conn = AsyncMock()
    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_classifier_response("consulta_envio", 0.88)
    )

    with patch("apps.api.agents.nodes.select_aop.tenant_scope", _make_fake_tenant_scope(fake_conn)), \
         patch("apps.api.agents.nodes.select_aop.load_active_aops", return_value=[CONSULTA_ENVIO, DEFAULT_AOP]), \
         patch("apps.api.agents.nodes.select_aop.load_aop", return_value=CONSULTA_ENVIO), \
         patch("apps.api.agents.nodes.select_aop.insert_intent_classifier_run") as mock_persist:
        mock_persist.return_value = AsyncMock()
        await node(BASE_STATE)

    mock_persist.assert_called_once()
    kwargs = mock_persist.call_args[1]
    assert kwargs["primary_slug"] == "consulta_envio"
    assert kwargs["primary_confidence"] == 0.88
    assert kwargs["was_reclassification"] is False


@pytest.mark.asyncio
async def test_select_aop_marks_reclassification_on_second_turn(fake_deps: Any) -> None:
    """En el segundo turno, was_reclassification=True."""
    node = make_select_aop_node(fake_deps)
    fake_conn = AsyncMock()
    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_classifier_response("consulta_envio", 0.88)
    )
    state = {
        **BASE_STATE,
        "aop_slug": "default",
        "aop_completed_signal": True,
    }

    with patch("apps.api.agents.nodes.select_aop.tenant_scope", _make_fake_tenant_scope(fake_conn)), \
         patch("apps.api.agents.nodes.select_aop.load_active_aops", return_value=[CONSULTA_ENVIO, DEFAULT_AOP]), \
         patch("apps.api.agents.nodes.select_aop.load_aop", return_value=CONSULTA_ENVIO), \
         patch("apps.api.agents.nodes.select_aop.insert_intent_classifier_run") as mock_persist:
        mock_persist.return_value = AsyncMock()
        await node(state)

    kwargs = mock_persist.call_args[1]
    assert kwargs["was_reclassification"] is True


@pytest.mark.asyncio
async def test_select_aop_detects_ambiguity(fake_deps: Any) -> None:
    """Cuando hay ambigüedad, se persiste pending_intent."""
    node = make_select_aop_node(fake_deps)
    fake_conn = AsyncMock()
    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_classifier_response(
            "consulta_envio", 0.80,
            alt_slug="cancelacion", alt_confidence=0.65,
            ambiguity=True,
        )
    )

    with patch("apps.api.agents.nodes.select_aop.tenant_scope", _make_fake_tenant_scope(fake_conn)), \
         patch("apps.api.agents.nodes.select_aop.load_active_aops", return_value=[CONSULTA_ENVIO, DEFAULT_AOP]), \
         patch("apps.api.agents.nodes.select_aop.load_aop", return_value=CONSULTA_ENVIO), \
         patch("apps.api.agents.nodes.select_aop.insert_intent_classifier_run", return_value=AsyncMock()):
        result = await node(BASE_STATE)

    assert result.get("pending_intent") == "cancelacion"


@pytest.mark.asyncio
async def test_select_aop_no_pending_intent_when_alt_low_confidence(fake_deps: Any) -> None:
    """No se persiste pending_intent si la confianza del alternativo es baja."""
    node = make_select_aop_node(fake_deps)
    fake_conn = AsyncMock()
    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_classifier_response(
            "consulta_envio", 0.80,
            alt_slug="cancelacion", alt_confidence=0.40,
            ambiguity=True,
        )
    )

    with patch("apps.api.agents.nodes.select_aop.tenant_scope", _make_fake_tenant_scope(fake_conn)), \
         patch("apps.api.agents.nodes.select_aop.load_active_aops", return_value=[CONSULTA_ENVIO, DEFAULT_AOP]), \
         patch("apps.api.agents.nodes.select_aop.load_aop", return_value=CONSULTA_ENVIO), \
         patch("apps.api.agents.nodes.select_aop.insert_intent_classifier_run", return_value=AsyncMock()):
        result = await node(BASE_STATE)

    assert "pending_intent" not in result


@pytest.mark.asyncio
async def test_select_aop_passthrough_on_prior_error(fake_deps: Any) -> None:
    """@guarded: si hay error previo, el nodo no hace nada."""
    node = make_select_aop_node(fake_deps)
    state = {**BASE_STATE, "error": "load_conversation: some_error"}
    result = await node(state)
    assert result == {}
    fake_deps.anthropic.messages.create.assert_not_called()
