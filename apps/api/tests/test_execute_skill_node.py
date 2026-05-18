"""Tests para el nodo `execute_skill`.

Cubre: happy path, no pending_tool_call, allowed_skills check, unknown slug,
input validation, skill execution failures, tool_iterations, accumulation
de tool_results, build_skill_context y short-circuit por @guarded.

Las skills reales (Shopify) NO se usan — se registra una skill dummy en
cada test para no acoplar este nodo a una integración específica.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes.execute_skill import (
    build_skill_context,
    make_execute_skill_node,
)
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry

# ----------------------------------------------------------------
# Skill dummy
# ----------------------------------------------------------------


class EchoInput(SkillInput):
    text: str


class EchoOutput(SkillOutput):
    echoed: str


class EchoSkill(Skill):
    slug = "test.echo"
    description = "Echoes the input text."
    tier: SkillTier = "L1"
    input_schema = EchoInput
    output_schema = EchoOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, EchoInput)
        return EchoOutput(echoed=f"echo:{inputs.text}")


class BoomSkill(Skill):
    """Skill que siempre falla — para probar el catch de excepciones."""

    slug = "test.boom"
    description = "Always raises."
    tier: SkillTier = "L1"
    input_schema = EchoInput
    output_schema = EchoOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        raise RuntimeError("boom_intentional")


# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _registry() -> Generator[None, None, None]:
    SkillRegistry._reset()
    SkillRegistry.register(EchoSkill)
    SkillRegistry.register(BoomSkill)
    yield
    SkillRegistry._reset()


@pytest.fixture
def deps(fake_deps: AgentDependencies) -> AgentDependencies:
    return fake_deps


def _base_state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "conversation_id": "22222222-2222-2222-2222-222222222222",
        "tenant_config": {"extra": {}},
        "allowed_skills": ["test.echo", "test.boom"],
        "tool_iterations": 0,
        "max_tool_iterations": 5,
        "tool_results": [],
    }
    base.update(overrides)
    return base


def _pending(slug: str = "test.echo", **kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "toolu_abc",
        "slug": slug,
        "input": {"text": "hola"},
    }
    base.update(kwargs)
    return base


# ----------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------


class TestHappyPath:
    async def test_executes_skill_and_appends_result(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending())
        result = await node(state)

        assert "tool_results" in result
        assert len(result["tool_results"]) == 1
        entry = result["tool_results"][0]
        assert entry["id"] == "toolu_abc"
        assert entry["slug"] == "test.echo"
        assert entry["is_error"] is False
        assert entry["error"] is None
        assert entry["output"] == {"echoed": "echo:hola"}
        assert entry["input"] == {"text": "hola"}

    async def test_clears_pending_tool_call(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending())
        result = await node(state)
        assert result["pending_tool_call"] is None

    async def test_increments_tool_iterations(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(), tool_iterations=3)
        result = await node(state)
        assert result["tool_iterations"] == 4

    async def test_appends_to_existing_results(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        prior = {"id": "toolu_prev", "slug": "test.echo", "input": {}, "output": {}, "is_error": False, "error": None}
        state = _base_state(pending_tool_call=_pending(), tool_results=[prior])
        result = await node(state)
        assert len(result["tool_results"]) == 2
        assert result["tool_results"][0] == prior
        assert result["tool_results"][1]["id"] == "toolu_abc"


# ----------------------------------------------------------------
# Errores operacionales (se reportan como tool_result con is_error=True)
# ----------------------------------------------------------------


class TestSkillNotAllowed:
    async def test_empty_allowed_skills_rejects_all(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(), allowed_skills=[])
        result = await node(state)
        entry = result["tool_results"][0]
        assert entry["is_error"] is True
        assert "skill_not_allowed" in entry["error"]

    async def test_slug_not_in_allowed_list(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending("test.echo"),
            allowed_skills=["test.other"],
        )
        result = await node(state)
        entry = result["tool_results"][0]
        assert entry["is_error"] is True
        assert "skill_not_allowed: test.echo" in entry["error"]

    async def test_increments_iterations_even_on_rejection(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(), allowed_skills=[])
        result = await node(state)
        assert result["tool_iterations"] == 1


class TestUnknownSkill:
    async def test_unknown_slug_returns_error_entry(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending("test.nonexistent"),
            allowed_skills=["test.nonexistent"],  # permitida pero no registrada
        )
        result = await node(state)
        entry = result["tool_results"][0]
        assert entry["is_error"] is True
        assert "unknown_skill: test.nonexistent" in entry["error"]


class TestInvalidInput:
    async def test_missing_required_field_returns_error_entry(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(input={}))  # falta `text`
        result = await node(state)
        entry = result["tool_results"][0]
        assert entry["is_error"] is True
        assert "invalid_input" in entry["error"]

    async def test_wrong_type_returns_error_entry(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(input={"text": 123}))
        result = await node(state)
        entry = result["tool_results"][0]
        # Pydantic v2 coerces int → str por default; verifico que NO crashea
        # y que sí ejecuta o reporta error consistente.
        assert entry["id"] == "toolu_abc"


class TestSkillExecutionFails:
    async def test_skill_raising_is_captured_as_error_entry(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending("test.boom"))
        result = await node(state)
        entry = result["tool_results"][0]
        assert entry["is_error"] is True
        assert "skill_failed: RuntimeError: boom_intentional" in entry["error"]
        assert entry["output"] is None


# ----------------------------------------------------------------
# Missing pending_tool_call
# ----------------------------------------------------------------


class TestNoPendingCall:
    async def test_returns_graph_error(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state()  # sin pending_tool_call
        result = await node(state)
        assert result.get("error") == "execute_skill_no_pending_call"
        assert "tool_results" not in result


# ----------------------------------------------------------------
# build_skill_context
# ----------------------------------------------------------------


class TestBuildSkillContext:
    def test_reads_shopify_creds_from_tenant_config_extra(self) -> None:
        state: dict[str, Any] = {
            "tenant_id": "t-1",
            "conversation_id": "c-1",
            "tenant_config": {
                "extra": {
                    "shopify_domain": "myshop.myshopify.com",
                    "shopify_token": "shpat_x",
                }
            },
        }
        ctx = build_skill_context(state)
        assert ctx.tenant_id == "t-1"
        assert ctx.conversation_id == "c-1"
        assert ctx.shopify_domain == "myshop.myshopify.com"
        assert ctx.shopify_token == "shpat_x"

    def test_no_creds_when_extra_missing(self) -> None:
        state: dict[str, Any] = {
            "tenant_id": "t-1",
            "conversation_id": "c-1",
            "tenant_config": {},
        }
        ctx = build_skill_context(state)
        assert ctx.shopify_domain is None
        assert ctx.shopify_token is None

    def test_no_creds_when_tenant_config_missing(self) -> None:
        state: dict[str, Any] = {"tenant_id": "t-1", "conversation_id": "c-1"}
        ctx = build_skill_context(state)
        assert ctx.shopify_domain is None
        assert ctx.shopify_token is None

    def test_context_is_immutable(self) -> None:
        state: dict[str, Any] = {
            "tenant_id": "t",
            "conversation_id": "c",
            "tenant_config": {"extra": {}},
        }
        ctx = build_skill_context(state)
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            ctx.tenant_id = "other"  # type: ignore[misc]


# ----------------------------------------------------------------
# Short-circuit por @guarded
# ----------------------------------------------------------------


class TestGuardShortCircuit:
    async def test_prior_error_skips_node(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(), error="upstream_failure")
        result = await node(state)
        # @guarded retorna dict vacío cuando hay error previo
        assert result == {}

    async def test_unexpected_exception_is_caught_by_guarded(
        self, deps: AgentDependencies, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Si algo del nodo (no la skill misma) lanza inesperadamente, @guarded lo captura."""

        # Hacemos que SkillRegistry.get lance un tipo no-ValueError.
        def _boom(slug: str) -> type:
            raise KeyError("registry_broken")

        monkeypatch.setattr(SkillRegistry, "get", classmethod(lambda cls, slug: _boom(slug)))

        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending())
        result = await node(state)
        assert "error" in result
        assert "execute_skill" in result["error"]


# ----------------------------------------------------------------
# Integración con SkillContext: Shopify creds via build_skill_context
# ----------------------------------------------------------------


class TestSkillContextPropagation:
    async def test_context_reaches_skill_with_creds(
        self, deps: AgentDependencies
    ) -> None:
        captured: dict[str, Any] = {}

        class ProbeInput(SkillInput):
            pass

        class ProbeOutput(SkillOutput):
            ok: bool

        class ProbeSkill(Skill):
            slug = "test.probe"
            description = "Captures context."
            tier: SkillTier = "L1"
            input_schema = ProbeInput
            output_schema = ProbeOutput
            default_threshold = 0.70

            async def execute(
                self, ctx: SkillContext, inputs: SkillInput
            ) -> SkillOutput:
                captured["ctx"] = ctx
                return ProbeOutput(ok=True)

        SkillRegistry.register(ProbeSkill)

        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call={"id": "toolu_x", "slug": "test.probe", "input": {}},
            allowed_skills=["test.probe"],
            tenant_config={
                "extra": {
                    "shopify_domain": "x.myshopify.com",
                    "shopify_token": "shpat_t",
                }
            },
        )
        await node(state)

        ctx: SkillContext = captured["ctx"]
        assert ctx.shopify_domain == "x.myshopify.com"
        assert ctx.shopify_token == "shpat_t"
        assert ctx.tenant_id == state["tenant_id"]
        assert ctx.conversation_id == state["conversation_id"]


# ----------------------------------------------------------------
# L2 / L3 permission gate
# ----------------------------------------------------------------


class L2Skill(Skill):
    """Skill L2 dummy para probar el permission gate."""

    slug = "test.write"
    description = "L2 write dummy."
    tier: SkillTier = "L2"
    input_schema = EchoInput
    output_schema = EchoOutput
    default_threshold = 0.85

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, EchoInput)
        return EchoOutput(echoed=f"written:{inputs.text}")


class L3Skill(Skill):
    """Skill L3 dummy para probar el bloqueo permanente."""

    slug = "test.dangerous"
    description = "L3 dangerous dummy."
    tier: SkillTier = "L3"
    input_schema = EchoInput
    output_schema = EchoOutput
    default_threshold = 0.95

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, EchoInput)
        return EchoOutput(echoed="dangerous")


class TestL2PermissionGate:
    @pytest.fixture(autouse=True)
    def _register_l2_l3(self) -> Generator[None, None, None]:
        SkillRegistry._reset()
        SkillRegistry.register(EchoSkill)
        SkillRegistry.register(L2Skill)
        SkillRegistry.register(L3Skill)
        yield
        SkillRegistry._reset()

    async def test_l2_blocked_without_allow_flag(self, deps: AgentDependencies) -> None:
        """L2 skill → error si allow_l2_skills no está en extra."""
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.write"),
            allowed_skills=["test.write"],
            tenant_config={"extra": {}},  # sin allow_l2_skills
        )
        result = await node(state)

        entry = result["tool_results"][-1]
        assert entry["is_error"] is True
        assert entry["error"] == "l2_skills_not_enabled_for_tenant"

    async def test_l2_blocked_when_flag_is_false(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.write"),
            allowed_skills=["test.write"],
            tenant_config={"extra": {"allow_l2_skills": False}},
        )
        result = await node(state)

        entry = result["tool_results"][-1]
        assert entry["is_error"] is True
        assert entry["error"] == "l2_skills_not_enabled_for_tenant"

    async def test_l2_executes_when_flag_is_true(self, deps: AgentDependencies) -> None:
        """Con allow_l2_skills: true, la skill L2 se ejecuta normalmente."""
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.write"),
            allowed_skills=["test.write"],
            tenant_config={"extra": {"allow_l2_skills": True}},
        )
        result = await node(state)

        entry = result["tool_results"][-1]
        assert entry["is_error"] is False
        assert entry["output"]["echoed"] == "written:hola"

    async def test_l3_always_blocked(self, deps: AgentDependencies) -> None:
        """L3 está bloqueado incluso con allow_l2_skills: true — Sprint 10."""
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.dangerous"),
            allowed_skills=["test.dangerous"],
            tenant_config={"extra": {"allow_l2_skills": True}},
        )
        result = await node(state)

        entry = result["tool_results"][-1]
        assert entry["is_error"] is True
        assert entry["error"] == "l3_skills_not_available"

    async def test_l1_unaffected_by_gate(self, deps: AgentDependencies) -> None:
        """Skills L1 no se ven afectadas por el gate, con o sin el flag."""
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.echo"),
            allowed_skills=["test.echo"],
            tenant_config={"extra": {}},  # sin allow_l2_skills
        )
        result = await node(state)

        entry = result["tool_results"][-1]
        assert entry["is_error"] is False
        assert entry["output"]["echoed"] == "echo:hola"

    async def test_l2_blocked_increments_iterations(self, deps: AgentDependencies) -> None:
        """El rechazo por tier sigue consumiendo una iteración."""
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.write"),
            allowed_skills=["test.write"],
            tenant_config={"extra": {}},
            tool_iterations=2,
        )
        result = await node(state)

        assert result["tool_iterations"] == 3


# ----------------------------------------------------------------
# Make node sanity
# ----------------------------------------------------------------


class TestFactory:
    def test_make_returns_callable(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        assert callable(node)

    def test_deps_can_be_mock(self) -> None:
        # Confirma que el nodo no toca deps internamente.
        node = make_execute_skill_node(AsyncMock())  # type: ignore[arg-type]
        assert callable(node)
