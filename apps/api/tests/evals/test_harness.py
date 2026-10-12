"""Tests del eval harness (Sprint 7.6).

Cubre:
- load_fixtures: carga correcta desde YAML, slug sin fixtures, slug inexistente
- _check_assertion: cada tipo de aserción (pass y fail)
- run_fixture: all-pass, any-fail, error de compilación
- run_eval: good AOP pasa, bad AOP falla, sin fixtures → meets_gate=False
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from apps.api.db.models import AopWithContent
from apps.api.evals.harness import (
    PASS_RATE_GATE,
    Assertion,
    EvalFixture,
    _check_assertion,
    load_fixtures,
    run_eval,
    run_fixture,
)
from apps.api.tests.conftest import TENANT_ID, make_tenant_configuration

AOP_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

# ── Fixtures AOP de referencia ────────────────────────────────────────────────

GOOD_CE_FRONTMATTER = {
    "slug": "consulta_envio",
    "name": "Consulta de Envío",
    "allowed_skills": ["shopify.list_my_orders", "shopify.get_order_status"],
    "required_data": ["email del cliente"],
    "guardrails": ["No compartas datos de otros clientes"],
    "max_tool_iterations": 4,
    "confidence_threshold": 0.70,
    "require_supervision": False,
    "escalation_triggers": ["Fraude o disputa de cargo", "Retraso de más de 30 días"],
}
GOOD_CE_BODY = "## Consulta de Envío\n\nPide el email. Busca el pedido. Comunica el estado."

GOOD_DEFAULT_FRONTMATTER = {
    "slug": "default",
    "name": "Procedimiento General",
    "allowed_skills": [],
    "max_tool_iterations": 3,
    "confidence_threshold": 0.50,
    "require_supervision": False,
    "escalation_triggers": [],
}
GOOD_DEFAULT_BODY = "## Procedimiento General\n\nIntenta resolver. Si no puedes, escala."


def _make_aop(frontmatter: dict, body: str = "", slug: str = "test_aop") -> AopWithContent:
    return AopWithContent(
        id=AOP_ID,
        tenant_id=TENANT_ID,
        slug=frontmatter.get("slug", slug),
        workspace="production",
        current_version=1,
        yaml_frontmatter=frontmatter,
        body_markdown=body or "## Body\n\nContenido del AOP.",
        raw_source="",
    )


def _mock_registry(slugs: list[str]) -> MagicMock:
    """Mockea SkillRegistry.get para los slugs dados."""

    def _get(slug: str) -> MagicMock:
        if slug not in slugs:
            raise ValueError(f"Unknown skill: {slug}")
        skill_instance = MagicMock()
        skill_instance.to_anthropic_tool.return_value = {
            "name": slug.replace(".", "_"),
            "description": f"Tool {slug}",
            "input_schema": {"type": "object", "properties": {}},
        }
        return MagicMock(return_value=skill_instance)

    mock = MagicMock()
    mock.side_effect = _get
    return mock


# ── load_fixtures ─────────────────────────────────────────────────────────────


def test_load_fixtures_consulta_envio_returns_8():
    fixtures = load_fixtures("consulta_envio")
    assert len(fixtures) == 8


def test_load_fixtures_default_returns_5():
    fixtures = load_fixtures("default")
    assert len(fixtures) == 5


def test_load_fixtures_unknown_slug_returns_empty():
    fixtures = load_fixtures("slug_que_no_existe_xyz")
    assert fixtures == []


def test_load_fixtures_have_assertions():
    fixtures = load_fixtures("consulta_envio")
    for f in fixtures:
        assert len(f.assertions) >= 1, f"Fixture '{f.name}' no tiene aserciones"


# ── _check_assertion ──────────────────────────────────────────────────────────


@pytest.fixture
def good_aop_ce():
    return _make_aop(GOOD_CE_FRONTMATTER, GOOD_CE_BODY)


@pytest.fixture
def good_compiled_ce(good_aop_ce):
    """CompiledAOP de un buen AOP de consulta_envio."""
    with patch("apps.api.aops.compiler.SkillRegistry.get", side_effect=_mock_registry(
        ["shopify.list_my_orders", "shopify.get_order_status"]
    ).side_effect):
        from apps.api.aops.compiler import compile_aop
        return compile_aop(good_aop_ce, make_tenant_configuration())


class TestCompileOkAssertion:
    def test_passes_when_no_error(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("compile_ok", None, good_aop_ce, good_compiled_ce, None)
        assert result.passed

    def test_fails_when_compile_error(self, good_aop_ce):
        result = _check_assertion("compile_ok", None, good_aop_ce, None, "bad yaml")
        assert not result.passed
        assert "bad yaml" in result.message


class TestPromptContainsAssertion:
    def test_passes_when_all_present(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("prompt_contains", ["email"], good_aop_ce, good_compiled_ce, None)
        assert result.passed

    def test_fails_when_phrase_missing(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("prompt_contains", ["frase_que_no_existe_xyz"], good_aop_ce, good_compiled_ce, None)
        assert not result.passed
        assert "frase_que_no_existe_xyz" in result.message

    def test_fails_without_compiled(self, good_aop_ce):
        result = _check_assertion("prompt_contains", ["algo"], good_aop_ce, None, "error")
        assert not result.passed


class TestPromptNotContainsAssertion:
    def test_passes_when_absent(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("prompt_not_contains", ["frase_inexistente_zzz"], good_aop_ce, good_compiled_ce, None)
        assert result.passed

    def test_fails_when_present(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("prompt_not_contains", ["Consulta de Envío"], good_aop_ce, good_compiled_ce, None)
        assert not result.passed


class TestPromptMinLengthAssertion:
    def test_passes_when_long_enough(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("prompt_min_length", 10, good_aop_ce, good_compiled_ce, None)
        assert result.passed

    def test_fails_when_too_short(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("prompt_min_length", 999999, good_aop_ce, good_compiled_ce, None)
        assert not result.passed


class TestSkillsIncludeAssertion:
    def test_passes_when_all_present(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion(
            "skills_include",
            ["shopify.list_my_orders", "shopify.get_order_status"],
            good_aop_ce, good_compiled_ce, None
        )
        assert result.passed

    def test_fails_when_missing(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion(
            "skills_include", ["skill_inexistente"], good_aop_ce, good_compiled_ce, None
        )
        assert not result.passed
        assert "skill_inexistente" in result.message


class TestSkillsNotIncludeAssertion:
    def test_passes_when_absent(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion(
            "skills_not_include", ["shopify.cancel_order"], good_aop_ce, good_compiled_ce, None
        )
        assert result.passed

    def test_fails_when_present(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion(
            "skills_not_include",
            ["shopify.list_my_orders"],
            good_aop_ce, good_compiled_ce, None
        )
        assert not result.passed


class TestMaxIterationsGteAssertion:
    def test_passes_when_gte(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("max_iterations_gte", 3, good_aop_ce, good_compiled_ce, None)
        assert result.passed

    def test_fails_when_lt(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("max_iterations_gte", 99, good_aop_ce, good_compiled_ce, None)
        assert not result.passed


class TestConfidenceThresholdBetweenAssertion:
    def test_passes_in_range(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("confidence_threshold_between", [0.0, 1.0], good_aop_ce, good_compiled_ce, None)
        assert result.passed

    def test_fails_below_range(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("confidence_threshold_between", [0.9, 1.0], good_aop_ce, good_compiled_ce, None)
        assert not result.passed


class TestToolCountMatchesSkillsAssertion:
    def test_passes_when_equal(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("tool_count_matches_skills", None, good_aop_ce, good_compiled_ce, None)
        assert result.passed

    def test_fails_when_unregistered_skill(self, good_aop_ce):
        aop_with_unknown = _make_aop(
            {**GOOD_CE_FRONTMATTER, "allowed_skills": ["shopify.list_my_orders", "skill.no_registrada"]},
            GOOD_CE_BODY,
        )
        with patch("apps.api.aops.compiler.SkillRegistry.get", side_effect=_mock_registry(
            ["shopify.list_my_orders"]
        ).side_effect):
            from apps.api.aops.compiler import compile_aop
            compiled = compile_aop(aop_with_unknown, make_tenant_configuration())
        result = _check_assertion("tool_count_matches_skills", None, aop_with_unknown, compiled, None)
        assert not result.passed


class TestFrontmatterHasKeyAssertion:
    def test_passes_when_key_exists(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("frontmatter_has_key", "slug", good_aop_ce, good_compiled_ce, None)
        assert result.passed

    def test_fails_when_key_missing(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("frontmatter_has_key", "clave_inexistente", good_aop_ce, good_compiled_ce, None)
        assert not result.passed


class TestUnknownAssertionKind:
    def test_unknown_kind_returns_failed(self, good_aop_ce, good_compiled_ce):
        result = _check_assertion("assertion_inexistente", None, good_aop_ce, good_compiled_ce, None)
        assert not result.passed
        assert "desconocido" in result.message


# ── run_fixture ───────────────────────────────────────────────────────────────


def test_run_fixture_all_pass():
    aop = _make_aop(GOOD_CE_FRONTMATTER, GOOD_CE_BODY)
    fixture = EvalFixture(
        name="test",
        assertions=[Assertion(kind="frontmatter_has_key", expected="slug")],
    )
    with patch("apps.api.aops.compiler.SkillRegistry.get", side_effect=_mock_registry(
        ["shopify.list_my_orders", "shopify.get_order_status"]
    ).side_effect):
        result = run_fixture(aop, make_tenant_configuration(), fixture)
    assert result.passed
    assert result.fixture_name == "test"


def test_run_fixture_one_fail():
    aop = _make_aop(GOOD_CE_FRONTMATTER, GOOD_CE_BODY)
    fixture = EvalFixture(
        name="test_fail",
        assertions=[
            Assertion(kind="frontmatter_has_key", expected="slug"),
            Assertion(kind="frontmatter_has_key", expected="clave_que_no_existe"),
        ],
    )
    with patch("apps.api.aops.compiler.SkillRegistry.get", side_effect=_mock_registry(
        ["shopify.list_my_orders", "shopify.get_order_status"]
    ).side_effect):
        result = run_fixture(aop, make_tenant_configuration(), fixture)
    assert not result.passed
    assert result.assertion_results[0].passed
    assert not result.assertion_results[1].passed


# ── run_eval ──────────────────────────────────────────────────────────────────


def test_run_eval_no_fixtures_returns_not_meets_gate():
    aop = _make_aop({"slug": "aop_sin_fixtures_xyz"}, "body")
    result = run_eval(aop)
    assert result.total_fixtures == 0
    assert result.pass_rate == 0.0
    assert not result.meets_gate


def test_run_eval_good_aop_passes_gate():
    aop = _make_aop(GOOD_CE_FRONTMATTER, GOOD_CE_BODY)
    with patch("apps.api.aops.compiler.SkillRegistry.get", side_effect=_mock_registry(
        ["shopify.list_my_orders", "shopify.get_order_status"]
    ).side_effect):
        result = run_eval(aop, make_tenant_configuration())
    assert result.total_fixtures == 8
    assert result.meets_gate
    assert result.pass_rate >= PASS_RATE_GATE


def test_run_eval_bad_aop_fails_gate():
    """AOP sin skills, sin name, sin escalation_triggers → falla varios fixtures."""
    bad_frontmatter = {
        "slug": "consulta_envio",
        "allowed_skills": [],  # falta list_my_orders, get_order_status
        "max_tool_iterations": 1,  # < 3
        "confidence_threshold": 0.70,
    }
    aop = _make_aop(bad_frontmatter, "body")
    with patch("apps.api.aops.compiler.SkillRegistry.get", side_effect=_mock_registry([]).side_effect):
        result = run_eval(aop, make_tenant_configuration())
    assert result.total_fixtures == 8
    assert not result.meets_gate
    assert result.passed_fixtures < result.total_fixtures


def test_run_eval_default_good_aop_passes():
    aop = _make_aop(GOOD_DEFAULT_FRONTMATTER, GOOD_DEFAULT_BODY)
    with patch("apps.api.aops.compiler.SkillRegistry.get", side_effect=_mock_registry([]).side_effect):
        result = run_eval(aop, make_tenant_configuration())
    assert result.total_fixtures == 5
    assert result.meets_gate


def test_run_eval_uses_default_tenant_config_when_none():
    aop = _make_aop(GOOD_DEFAULT_FRONTMATTER, GOOD_DEFAULT_BODY)
    with patch("apps.api.aops.compiler.SkillRegistry.get", side_effect=_mock_registry([]).side_effect):
        result = run_eval(aop)  # sin tenant_config
    assert result.total_fixtures == 5
