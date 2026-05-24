"""Tests del AOP compiler (Sprint 7.2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from apps.api.aops.compiler import (
    _AOP_CACHE,
    AopStep,
    CompiledAOP,
    _parse_steps,
    _render_aop_procedure,
    _render_global_rules,
    _render_guardrails,
    _render_kb_chunks,
    _render_required_data,
    _render_steps,
    _render_tenant_identity,
    compile_aop,
    load_aop,
)
from apps.api.db.models import AopWithContent
from apps.api.skills.registry import SkillRegistry
from apps.api.tests.conftest import (
    TENANT_ID,
    make_knowledge_chunk,
    make_tenant_configuration,
)

AOP_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

SAMPLE_FRONTMATTER = {
    "name": "Consulta de envío",
    "slug": "consulta_envio",
    "workspace": "production",
    "allowed_skills": ["shopify.get_order_by_email", "shopify.get_order_status"],
    "required_data": ["customer_email"],
    "guardrails": [
        "NUNCA inventes un número de tracking.",
        "Pide el email antes de usar tools.",
    ],
    "max_tool_iterations": 3,
    "confidence_threshold": 0.70,
    "require_supervision": False,
    "escalation_triggers": [
        "El pedido no aparece en Shopify",
        "El cliente está enojado",
    ],
}
SAMPLE_BODY = "## Cómo te comportas\n\n1. Busca el pedido.\n2. Comparte el tracking."


def _make_aop(**overrides: object) -> AopWithContent:
    base = {
        "id": AOP_ID,
        "tenant_id": TENANT_ID,
        "slug": "consulta_envio",
        "workspace": "production",
        "current_version": 1,
        "yaml_frontmatter": SAMPLE_FRONTMATTER,
        "body_markdown": SAMPLE_BODY,
        "raw_source": "",
    }
    base.update(overrides)
    return AopWithContent(**base)  # type: ignore[arg-type]


def _mock_skill(slug: str) -> MagicMock:
    """Skill mock con to_anthropic_tool() funcional."""
    skill_instance = MagicMock()
    skill_instance.to_anthropic_tool.return_value = {
        "name": slug.replace(".", "_"),
        "description": f"Tool para {slug}",
        "input_schema": {"type": "object", "properties": {}},
    }
    skill_class = MagicMock(return_value=skill_instance)
    return skill_class


# ─── _render_tenant_identity ─────────────────────────────────────────────────


def test_render_identity_uses_agent_voice_from_extra() -> None:
    config = make_tenant_configuration(extra={"agent_voice": "Eres Lunaria, tutea al cliente."})
    result = _render_tenant_identity(config)
    assert "Lunaria" in result
    assert "## Identidad" in result


def test_render_identity_uses_agent_voice_from_branding() -> None:
    config = make_tenant_configuration(branding={"agent_voice": "Eres Nova, sé formal."})
    result = _render_tenant_identity(config)
    assert "Nova" in result


def test_render_identity_extra_takes_priority_over_branding() -> None:
    config = make_tenant_configuration(
        extra={"agent_voice": "Desde extra"},
        branding={"agent_voice": "Desde branding"},
    )
    result = _render_tenant_identity(config)
    assert "Desde extra" in result
    assert "Desde branding" not in result


def test_render_identity_fallback_when_no_agent_voice() -> None:
    config = make_tenant_configuration()
    result = _render_tenant_identity(config)
    assert "## Identidad" in result
    assert len(result) > 10


# ─── _render_aop_procedure ───────────────────────────────────────────────────


def test_render_procedure_includes_name_and_body() -> None:
    result = _render_aop_procedure("Paso 1: busca el pedido.", {"name": "Consulta de envío"})
    assert "Consulta de envío" in result
    assert "Paso 1: busca el pedido." in result


def test_render_procedure_fallback_name() -> None:
    result = _render_aop_procedure("cuerpo", {})
    assert "Procedimiento" in result


def test_render_procedure_strips_body_whitespace() -> None:
    result = _render_aop_procedure("  cuerpo con espacios  ", {"name": "Test"})
    assert result.endswith("cuerpo con espacios")


# ─── _render_guardrails ───────────────────────────────────────────────────────


def test_render_guardrails_empty_returns_empty() -> None:
    assert _render_guardrails([]) == ""


def test_render_guardrails_formats_each_rule() -> None:
    result = _render_guardrails(["Regla A", "Regla B"])
    assert "- Regla A" in result
    assert "- Regla B" in result
    assert "NO negociables" in result


def test_render_guardrails_single_rule() -> None:
    result = _render_guardrails(["Solo una regla"])
    assert "Solo una regla" in result


# ─── _render_required_data ───────────────────────────────────────────────────


def test_render_required_data_empty_returns_empty() -> None:
    assert _render_required_data([]) == ""


def test_render_required_data_lists_items() -> None:
    result = _render_required_data(["customer_email", "order_number"])
    assert "customer_email" in result
    assert "order_number" in result
    assert "Datos requeridos" in result


# ─── _render_kb_chunks ───────────────────────────────────────────────────────


def test_render_kb_chunks_empty_returns_empty() -> None:
    assert _render_kb_chunks([]) == ""


def test_render_kb_chunks_includes_content_and_title() -> None:
    chunk = make_knowledge_chunk(document_title="FAQ envíos", content="Los pedidos tardan 3 días.")
    result = _render_kb_chunks([chunk])
    assert "FAQ envíos" in result
    assert "Los pedidos tardan 3 días." in result


def test_render_kb_chunks_shows_similarity() -> None:
    chunk = make_knowledge_chunk(similarity=0.92)
    result = _render_kb_chunks([chunk])
    assert "0.92" in result


def test_render_kb_chunks_multiple_numbered() -> None:
    chunks = [make_knowledge_chunk(), make_knowledge_chunk()]
    result = _render_kb_chunks(chunks)
    assert "Fragmento 1" in result
    assert "Fragmento 2" in result


def test_render_kb_chunks_includes_no_invent_warning() -> None:
    result = _render_kb_chunks([make_knowledge_chunk()])
    assert "NO inventes" in result


# ─── _render_global_rules ────────────────────────────────────────────────────


def test_render_global_rules_always_has_base_rules() -> None:
    result = _render_global_rules([])
    assert "idioma del cliente" in result
    assert "escala" in result.lower()
    assert "No inventes" in result or "nunca inventes" in result.lower()


def test_render_global_rules_includes_escalation_triggers() -> None:
    result = _render_global_rules(["El pedido no aparece", "Cliente enojado"])
    assert "El pedido no aparece" in result
    assert "Cliente enojado" in result


def test_render_global_rules_no_triggers_section_when_empty() -> None:
    result = _render_global_rules([])
    assert "Escala inmediatamente" not in result


# ─── compile_aop ─────────────────────────────────────────────────────────────


def test_compile_aop_returns_compiled_aop() -> None:
    aop = _make_aop()
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert isinstance(result, CompiledAOP)


def test_compile_aop_system_prompt_has_all_blocks() -> None:
    aop = _make_aop()
    config = make_tenant_configuration(extra={"agent_voice": "Eres Lunaria."})
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert "Lunaria" in result.system_prompt
    assert "Consulta de envío" in result.system_prompt
    assert "NUNCA inventes" in result.system_prompt
    assert "customer_email" in result.system_prompt
    assert "idioma del cliente" in result.system_prompt
    assert "El pedido no aparece en Shopify" in result.system_prompt


def test_compile_aop_includes_kb_chunks_when_provided() -> None:
    aop = _make_aop()
    config = make_tenant_configuration()
    chunk = make_knowledge_chunk(document_title="FAQ", content="Política de devoluciones.")
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config, kb_chunks=[chunk])
    assert "FAQ" in result.system_prompt
    assert "Política de devoluciones." in result.system_prompt


def test_compile_aop_no_kb_block_when_no_chunks() -> None:
    aop = _make_aop()
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config, kb_chunks=[])
    assert "base de conocimiento" not in result.system_prompt


def test_compile_aop_reads_max_iterations_from_frontmatter() -> None:
    aop = _make_aop(yaml_frontmatter={**SAMPLE_FRONTMATTER, "max_tool_iterations": 7})
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert result.max_iterations == 7


def test_compile_aop_defaults_max_iterations_to_5() -> None:
    fm = {k: v for k, v in SAMPLE_FRONTMATTER.items() if k != "max_tool_iterations"}
    aop = _make_aop(yaml_frontmatter=fm)
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert result.max_iterations == 5


def test_compile_aop_reads_confidence_threshold() -> None:
    aop = _make_aop(yaml_frontmatter={**SAMPLE_FRONTMATTER, "confidence_threshold": 0.85})
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert result.confidence_threshold == 0.85


def test_compile_aop_require_supervision_true() -> None:
    aop = _make_aop(yaml_frontmatter={**SAMPLE_FRONTMATTER, "require_supervision": True})
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert result.require_supervision is True


def test_compile_aop_resolves_skill_tools() -> None:
    aop = _make_aop()
    config = make_tenant_configuration()
    mock_skill_class = _mock_skill("shopify.get_order_by_email")
    with patch.object(SkillRegistry, "get", return_value=mock_skill_class):
        result = compile_aop(aop, config)
    assert len(result.tool_definitions) == len(SAMPLE_FRONTMATTER["allowed_skills"])


def test_compile_aop_skips_unknown_skills_gracefully() -> None:
    aop = _make_aop()
    config = make_tenant_configuration()

    def _get(slug: str) -> object:
        if slug == "shopify.get_order_by_email":
            return _mock_skill(slug)
        raise ValueError(f"unknown_skill: {slug}")

    with patch.object(SkillRegistry, "get", side_effect=_get):
        result = compile_aop(aop, config)

    assert len(result.tool_definitions) == 1
    assert result.tool_definitions[0]["name"] == "shopify_get_order_by_email"


def test_compile_aop_no_skills_in_frontmatter() -> None:
    fm = {**SAMPLE_FRONTMATTER, "allowed_skills": []}
    aop = _make_aop(yaml_frontmatter=fm)
    config = make_tenant_configuration()
    result = compile_aop(aop, config)
    assert result.tool_definitions == []
    assert result.allowed_skills == []


def test_compile_aop_escalation_triggers_in_result() -> None:
    aop = _make_aop()
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert "El pedido no aparece en Shopify" in result.escalation_triggers
    assert "El cliente está enojado" in result.escalation_triggers


def test_compile_aop_blocks_separated_by_divider() -> None:
    aop = _make_aop()
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert "---" in result.system_prompt


# ─── _parse_steps ─────────────────────────────────────────────────────────────


def test_parse_steps_empty_list() -> None:
    assert _parse_steps([]) == []


def test_parse_steps_parses_full_step() -> None:
    raw = [{"id": "gather_info", "name": "Recopilar datos", "decision_point": "¿Tenemos email?"}]
    steps = _parse_steps(raw)
    assert len(steps) == 1
    assert steps[0].id == "gather_info"
    assert steps[0].name == "Recopilar datos"
    assert steps[0].decision_point == "¿Tenemos email?"


def test_parse_steps_decision_point_optional() -> None:
    raw = [{"id": "resolve", "name": "Resolver"}]
    steps = _parse_steps(raw)
    assert steps[0].decision_point == ""


def test_parse_steps_skips_items_without_id_or_name() -> None:
    raw = [
        {"id": "ok", "name": "Válido"},
        {"name": "sin id"},
        {"id": "sin_nombre"},
        "no es dict",
    ]
    steps = _parse_steps(raw)
    assert len(steps) == 1
    assert steps[0].id == "ok"


def test_parse_steps_multiple_steps_in_order() -> None:
    raw = [
        {"id": "step_1", "name": "Primero"},
        {"id": "step_2", "name": "Segundo"},
        {"id": "step_3", "name": "Tercero"},
    ]
    steps = _parse_steps(raw)
    assert [s.id for s in steps] == ["step_1", "step_2", "step_3"]


# ─── _render_steps ────────────────────────────────────────────────────────────


def test_render_steps_empty_returns_empty() -> None:
    assert _render_steps([]) == ""


def test_render_steps_includes_step_names() -> None:
    steps = [AopStep(id="s1", name="Verificar pedido"), AopStep(id="s2", name="Responder")]
    result = _render_steps(steps)
    assert "Verificar pedido" in result
    assert "Responder" in result
    assert "Pasos del procedimiento" in result


def test_render_steps_includes_decision_point_when_present() -> None:
    steps = [AopStep(id="s1", name="Verificar", decision_point="¿Tenemos el pedido?")]
    result = _render_steps(steps)
    assert "¿Tenemos el pedido?" in result


def test_render_steps_no_decision_point_dash_not_shown() -> None:
    steps = [AopStep(id="s1", name="Solo nombre")]
    result = _render_steps(steps)
    assert "—" not in result


def test_render_steps_numbered() -> None:
    steps = [AopStep(id="a", name="Uno"), AopStep(id="b", name="Dos")]
    result = _render_steps(steps)
    assert "1." in result
    assert "2." in result


# ─── compile_aop con steps ────────────────────────────────────────────────────


def test_compile_aop_steps_empty_when_not_in_frontmatter() -> None:
    aop = _make_aop()
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert result.steps == []


def test_compile_aop_steps_parsed_from_frontmatter() -> None:
    fm = {
        **SAMPLE_FRONTMATTER,
        "steps": [
            {"id": "gather", "name": "Recopilar info", "decision_point": "¿Email disponible?"},
            {"id": "respond", "name": "Responder"},
        ],
    }
    aop = _make_aop(yaml_frontmatter=fm)
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert len(result.steps) == 2
    assert result.steps[0].id == "gather"
    assert result.steps[1].id == "respond"


def test_compile_aop_steps_included_in_system_prompt() -> None:
    fm = {
        **SAMPLE_FRONTMATTER,
        "steps": [{"id": "s1", "name": "Verificar pedido", "decision_point": "¿Número disponible?"}],
    }
    aop = _make_aop(yaml_frontmatter=fm)
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert "Verificar pedido" in result.system_prompt
    assert "¿Número disponible?" in result.system_prompt


def test_compile_aop_legacy_aop_without_steps_unchanged() -> None:
    """AOP sin steps[] compila igual que antes y no incluye sección de pasos."""
    aop = _make_aop()
    config = make_tenant_configuration()
    with patch.object(SkillRegistry, "get", side_effect=ValueError("unknown_skill")):
        result = compile_aop(aop, config)
    assert result.steps == []
    assert "Pasos del procedimiento" not in result.system_prompt


# ─── load_aop (cache) ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_aop_cache() -> None:
    _AOP_CACHE.clear()
    yield  # type: ignore[misc]
    _AOP_CACHE.clear()


@pytest.mark.asyncio
async def test_load_aop_returns_none_when_not_found() -> None:
    conn = AsyncMock()
    with patch("apps.api.aops.compiler.get_aop_by_slug", return_value=None) as mock_get:
        result = await load_aop(conn, TENANT_ID, "nonexistent")
    assert result is None
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_load_aop_caches_result() -> None:
    aop = _make_aop()
    conn = AsyncMock()
    with patch("apps.api.aops.compiler.get_aop_by_slug", return_value=aop) as mock_get:
        result1 = await load_aop(conn, TENANT_ID, "consulta_envio")
        result2 = await load_aop(conn, TENANT_ID, "consulta_envio")

    assert result1 == result2
    mock_get.assert_called_once()  # segunda llamada usó el cache


@pytest.mark.asyncio
async def test_load_aop_bypass_cache_hits_db() -> None:
    aop = _make_aop()
    conn = AsyncMock()
    with patch("apps.api.aops.compiler.get_aop_by_slug", return_value=aop) as mock_get:
        await load_aop(conn, TENANT_ID, "consulta_envio")
        await load_aop(conn, TENANT_ID, "consulta_envio", bypass_cache=True)

    assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_load_aop_different_workspaces_cached_independently() -> None:
    aop_prod = _make_aop(workspace="production")
    aop_staging = _make_aop(workspace="staging")
    conn = AsyncMock()

    with patch(
        "apps.api.aops.compiler.get_aop_by_slug",
        side_effect=[aop_prod, aop_staging],
    ) as mock_get:
        result_prod = await load_aop(conn, TENANT_ID, "consulta_envio", "production")
        result_staging = await load_aop(conn, TENANT_ID, "consulta_envio", "staging")

    assert result_prod.workspace == "production"
    assert result_staging.workspace == "staging"
    assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_load_aop_none_not_cached() -> None:
    conn = AsyncMock()
    with patch("apps.api.aops.compiler.get_aop_by_slug", return_value=None) as mock_get:
        await load_aop(conn, TENANT_ID, "nonexistent")
        await load_aop(conn, TENANT_ID, "nonexistent")

    assert mock_get.call_count == 2  # None no se guarda en cache
