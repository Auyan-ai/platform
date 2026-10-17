"""Eval harness — valida la calidad de un AOP compilado contra fixtures YAML.

Diseño Sprint 7:
- Función pura: sin I/O de red ni DB. compile_aop es determinista.
- Fixtures YAML por slug en apps/api/evals/fixtures/{slug}/*.yaml.
- run_eval(aop, tenant_config) → EvalRunResult con pass_rate y meets_gate.
- El endpoint PATCH /aops/{id}/promote llama a run_eval antes de copiar a producción.
- Gate: pass_rate < PASS_RATE_GATE (0.80) → 422 con detalles.

Tipos de aserciones disponibles:
  compile_ok               — el AOP compila sin excepción
  prompt_contains          — system_prompt contiene todas las frases en 'expected' (lista)
  prompt_not_contains      — system_prompt NO contiene ninguna frase en 'expected' (lista)
  prompt_min_length        — len(system_prompt) >= expected (int)
  skills_include           — allowed_skills tiene todos los slugs en 'expected' (lista)
  skills_not_include       — allowed_skills NO tiene ningún slug en 'expected' (lista)
  max_iterations_gte       — max_iterations >= expected (int)
  confidence_threshold_between — lo <= confidence_threshold <= hi (lista [lo, hi])
  tool_count_matches_skills — len(tool_definitions) == len(allowed_skills)
  frontmatter_has_key      — yaml_frontmatter tiene la clave 'expected' (string)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from apps.api.aops.compiler import CompiledAOP, compile_aop
from apps.api.core.config import get_models
from apps.api.db.models import AopWithContent, TenantConfiguration

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PASS_RATE_GATE = 0.80

# Tipos de aserción deterministas: no llaman al LLM ni a la red. Es la lista explícita
# que decide qué fixtures entran en la capa estática (`python -m apps.api.evals.run
# --static`, bloqueante en CI). Un tipo nuevo que necesite el LLM NO se añade aquí; un
# fixture con un tipo fuera de esta lista hace fallar la corrida estática en alto.
STATIC_ASSERTION_KINDS: frozenset[str] = frozenset(
    {
        "compile_ok",
        "prompt_contains",
        "prompt_not_contains",
        "prompt_min_length",
        "skills_include",
        "skills_not_include",
        "max_iterations_gte",
        "confidence_threshold_between",
        "tool_count_matches_skills",
        "frontmatter_has_key",
    }
)


# ─── Modelos de datos ─────────────────────────────────────────────────────────


@dataclass
class Assertion:
    kind: str
    expected: Any = None


@dataclass
class EvalFixture:
    name: str
    description: str = ""
    assertions: list[Assertion] = field(default_factory=list)


def non_static_kinds(fixture: EvalFixture) -> list[str]:
    """Tipos de aserción del fixture que no están declarados como estáticos."""
    return sorted({a.kind for a in fixture.assertions} - STATIC_ASSERTION_KINDS)


@dataclass
class AssertionResult:
    kind: str
    passed: bool
    message: str


@dataclass
class FixtureResult:
    fixture_name: str
    passed: bool
    assertion_results: list[AssertionResult]


@dataclass
class EvalRunResult:
    aop_slug: str
    aop_version: int
    total_fixtures: int
    passed_fixtures: int
    pass_rate: float
    meets_gate: bool
    fixture_results: list[FixtureResult]


# ─── Carga de fixtures ────────────────────────────────────────────────────────


def load_fixtures(slug: str) -> list[EvalFixture]:
    """Carga todos los fixtures YAML del directorio fixtures/{slug}/."""
    slug_dir = FIXTURES_DIR / slug
    if not slug_dir.exists():
        return []

    fixtures: list[EvalFixture] = []
    for yaml_file in sorted(slug_dir.glob("*.yaml")):
        try:
            raw = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                logger.warning("eval.fixture_invalid_format file=%s", yaml_file.name)
                continue
            assertions = [
                Assertion(kind=a["kind"], expected=a.get("expected"))
                for a in raw.get("assertions", [])
            ]
            fixtures.append(
                EvalFixture(
                    name=raw.get("name", yaml_file.stem),
                    description=raw.get("description", ""),
                    assertions=assertions,
                )
            )
        except Exception as exc:
            logger.warning("eval.fixture_load_error file=%s error=%s", yaml_file.name, exc)

    return fixtures


# ─── Checker de aserciones individuales ──────────────────────────────────────


def _check_assertion(
    kind: str,
    expected: Any,
    aop: AopWithContent,
    compiled: CompiledAOP | None,
    compile_error: str | None,
) -> AssertionResult:
    """Evalúa una sola aserción. Devuelve AssertionResult con passed + mensaje."""

    if kind == "compile_ok":
        if compile_error is None:
            return AssertionResult(kind=kind, passed=True, message="AOP compilado exitosamente")
        return AssertionResult(kind=kind, passed=False, message=f"Error al compilar: {compile_error}")

    # Las demás aserciones requieren que compile_aop haya sido exitoso
    if compiled is None:
        return AssertionResult(
            kind=kind,
            passed=False,
            message=f"No se puede evaluar '{kind}': el AOP no compiló ({compile_error})",
        )

    if kind == "prompt_contains":
        phrases = expected if isinstance(expected, list) else [expected]
        missing = [p for p in phrases if p.lower() not in compiled.system_prompt.lower()]
        if not missing:
            return AssertionResult(kind=kind, passed=True, message="Todas las frases encontradas en el system prompt")
        return AssertionResult(kind=kind, passed=False, message=f"Faltan en el system prompt: {missing}")

    if kind == "prompt_not_contains":
        phrases = expected if isinstance(expected, list) else [expected]
        found = [p for p in phrases if p.lower() in compiled.system_prompt.lower()]
        if not found:
            return AssertionResult(kind=kind, passed=True, message="Ninguna frase prohibida encontrada")
        return AssertionResult(kind=kind, passed=False, message=f"Frases prohibidas encontradas: {found}")

    if kind == "prompt_min_length":
        length = len(compiled.system_prompt)
        if length >= int(expected):
            return AssertionResult(kind=kind, passed=True, message=f"Longitud del prompt: {length} >= {expected}")
        return AssertionResult(kind=kind, passed=False, message=f"Prompt demasiado corto: {length} < {expected}")

    if kind == "skills_include":
        required = expected if isinstance(expected, list) else [expected]
        missing = [s for s in required if s not in compiled.allowed_skills]
        if not missing:
            return AssertionResult(kind=kind, passed=True, message=f"Skills requeridas presentes: {required}")
        return AssertionResult(kind=kind, passed=False, message=f"Skills ausentes en allowed_skills: {missing}")

    if kind == "skills_not_include":
        forbidden = expected if isinstance(expected, list) else [expected]
        found = [s for s in forbidden if s in compiled.allowed_skills]
        if not found:
            return AssertionResult(kind=kind, passed=True, message="Ninguna skill prohibida en el AOP")
        return AssertionResult(kind=kind, passed=False, message=f"Skills prohibidas encontradas: {found}")

    if kind == "max_iterations_gte":
        if compiled.max_iterations >= int(expected):
            return AssertionResult(
                kind=kind,
                passed=True,
                message=f"max_iterations={compiled.max_iterations} >= {expected}",
            )
        return AssertionResult(
            kind=kind,
            passed=False,
            message=f"max_iterations={compiled.max_iterations} < {expected}",
        )

    if kind == "confidence_threshold_between":
        lo, hi = float(expected[0]), float(expected[1])
        ct = compiled.confidence_threshold
        if lo <= ct <= hi:
            return AssertionResult(
                kind=kind, passed=True, message=f"confidence_threshold={ct} en [{lo}, {hi}]"
            )
        return AssertionResult(
            kind=kind, passed=False, message=f"confidence_threshold={ct} fuera de [{lo}, {hi}]"
        )

    if kind == "tool_count_matches_skills":
        n_skills = len(compiled.allowed_skills)
        n_tools = len(compiled.tool_definitions)
        if n_tools == n_skills:
            return AssertionResult(
                kind=kind, passed=True, message=f"tool_definitions ({n_tools}) == allowed_skills ({n_skills})"
            )
        return AssertionResult(
            kind=kind,
            passed=False,
            message=f"tool_definitions ({n_tools}) != allowed_skills ({n_skills})",
        )

    if kind == "frontmatter_has_key":
        key = str(expected)
        if key in aop.yaml_frontmatter:
            return AssertionResult(kind=kind, passed=True, message=f"frontmatter tiene clave '{key}'")
        return AssertionResult(kind=kind, passed=False, message=f"frontmatter no tiene clave '{key}'")

    return AssertionResult(kind=kind, passed=False, message=f"Tipo de aserción desconocido: '{kind}'")


# ─── Runner ───────────────────────────────────────────────────────────────────


def _default_tenant_config(tenant_id: Any = None) -> TenantConfiguration:
    """Configuración mínima para compilar AOPs en el harness sin DB."""
    from uuid import UUID

    tid = tenant_id if isinstance(tenant_id, UUID) else uuid4()
    return TenantConfiguration(
        tenant_id=tid,
        agent_model=get_models().default_agent_model,
        escalation_threshold=0.6,
        branding={},
        extra={},
    )


def run_fixture(
    aop: AopWithContent,
    tenant_config: TenantConfiguration,
    fixture: EvalFixture,
) -> FixtureResult:
    """Ejecuta un fixture contra el AOP. Compila una vez y evalúa todas las aserciones."""
    compiled: CompiledAOP | None = None
    compile_error: str | None = None

    try:
        compiled = compile_aop(aop, tenant_config)
    except Exception as exc:
        compile_error = str(exc)

    results = [
        _check_assertion(a.kind, a.expected, aop, compiled, compile_error)
        for a in fixture.assertions
    ]

    all_passed = all(r.passed for r in results)
    return FixtureResult(
        fixture_name=fixture.name,
        passed=all_passed,
        assertion_results=results,
    )


def run_eval(
    aop: AopWithContent,
    tenant_config: TenantConfiguration | None = None,
) -> EvalRunResult:
    """Evalúa un AOP contra todos los fixtures de su slug.

    Si no hay fixtures para el slug, retorna EvalRunResult con total_fixtures=0
    y meets_gate=False — así el promote endpoint rechaza AOPs sin inventario.
    """
    if tenant_config is None:
        tenant_config = _default_tenant_config(aop.tenant_id)

    fixtures = load_fixtures(aop.slug)
    fixture_results = [run_fixture(aop, tenant_config, f) for f in fixtures]

    total = len(fixture_results)
    passed = sum(1 for r in fixture_results if r.passed)
    pass_rate = passed / total if total > 0 else 0.0
    meets_gate = total > 0 and pass_rate >= PASS_RATE_GATE

    return EvalRunResult(
        aop_slug=aop.slug,
        aop_version=aop.current_version,
        total_fixtures=total,
        passed_fixtures=passed,
        pass_rate=pass_rate,
        meets_gate=meets_gate,
        fixture_results=fixture_results,
    )
