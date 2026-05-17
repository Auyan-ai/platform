"""Tests para skills/registry.py: SkillRegistry register/get/list_for_aop."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry

# ----------------------------------------------------------------
# Skills dummy reutilizables dentro de los tests
# ----------------------------------------------------------------


class PingInput(SkillInput):
    pass


class PingOutput(SkillOutput):
    pong: bool = True


class PingSkill(Skill):
    slug = "test.ping"
    description = "Responds with pong."
    tier: SkillTier = "L1"
    input_schema = PingInput
    output_schema = PingOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        return PingOutput()


class SearchInput(SkillInput):
    query: str


class SearchOutput(SkillOutput):
    results: list[str]


class SearchSkill(Skill):
    slug = "test.search"
    description = "Searches for something."
    tier: SkillTier = "L1"
    input_schema = SearchInput
    output_schema = SearchOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, SearchInput)
        return SearchOutput(results=[])


class BuyInput(SkillInput):
    amount: float


class BuyOutput(SkillOutput):
    success: bool


class BuySkill(Skill):
    slug = "test.buy"
    description = "Buys something."
    tier: SkillTier = "L3"
    input_schema = BuyInput
    output_schema = BuyOutput
    requires_idempotency = True
    default_threshold = 0.95

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        return BuyOutput(success=True)


# ----------------------------------------------------------------
# Fixture: limpiar registry antes y después de cada test
# ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_registry() -> Generator[None, None, None]:
    SkillRegistry._reset()
    yield
    SkillRegistry._reset()


# ----------------------------------------------------------------
# Tests
# ----------------------------------------------------------------


class TestRegister:
    def test_register_adds_skill_to_registry(self) -> None:
        SkillRegistry.register(PingSkill)
        assert SkillRegistry.get("test.ping") is PingSkill

    def test_register_returns_skill_class(self) -> None:
        result = SkillRegistry.register(PingSkill)
        assert result is PingSkill

    def test_register_usable_as_decorator(self) -> None:
        @SkillRegistry.register
        class TempSkill(Skill):
            slug = "test.temp"
            description = "Temp skill."
            tier: SkillTier = "L1"
            input_schema = PingInput
            output_schema = PingOutput
            default_threshold = 0.70

            async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
                return PingOutput()

        assert SkillRegistry.get("test.temp") is TempSkill

    def test_register_multiple_skills(self) -> None:
        SkillRegistry.register(PingSkill)
        SkillRegistry.register(BuySkill)
        assert SkillRegistry.get("test.ping") is PingSkill
        assert SkillRegistry.get("test.buy") is BuySkill

    def test_register_overwrites_same_slug(self) -> None:
        SkillRegistry.register(PingSkill)

        class PingV2(Skill):
            slug = "test.ping"
            description = "Ping v2."
            tier: SkillTier = "L1"
            input_schema = PingInput
            output_schema = PingOutput
            default_threshold = 0.70

            async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
                return PingOutput()

        SkillRegistry.register(PingV2)
        assert SkillRegistry.get("test.ping") is PingV2


class TestGet:
    def test_get_returns_correct_class(self) -> None:
        SkillRegistry.register(PingSkill)
        assert SkillRegistry.get("test.ping") is PingSkill

    def test_get_unknown_slug_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown_skill: no.existe"):
            SkillRegistry.get("no.existe")

    def test_get_after_reset_raises(self) -> None:
        SkillRegistry.register(PingSkill)
        SkillRegistry._reset()
        with pytest.raises(ValueError, match="unknown_skill"):
            SkillRegistry.get("test.ping")


class TestListForAop:
    def test_returns_skills_in_order(self) -> None:
        SkillRegistry.register(PingSkill)
        SkillRegistry.register(BuySkill)
        result = SkillRegistry.list_for_aop(["test.ping", "test.buy"])
        assert result == [PingSkill, BuySkill]

    def test_preserves_requested_order(self) -> None:
        SkillRegistry.register(PingSkill)
        SkillRegistry.register(BuySkill)
        result = SkillRegistry.list_for_aop(["test.buy", "test.ping"])
        assert result == [BuySkill, PingSkill]

    def test_empty_list_returns_empty(self) -> None:
        result = SkillRegistry.list_for_aop([])
        assert result == []

    def test_unknown_slug_in_aop_raises(self) -> None:
        SkillRegistry.register(PingSkill)
        with pytest.raises(ValueError, match="unknown_skill"):
            SkillRegistry.list_for_aop(["test.ping", "test.nonexistent"])

    def test_single_skill(self) -> None:
        SkillRegistry.register(SearchSkill)
        result = SkillRegistry.list_for_aop(["test.search"])
        assert result == [SearchSkill]

    def test_list_for_aop_with_three_skills(self) -> None:
        SkillRegistry.register(PingSkill)
        SkillRegistry.register(SearchSkill)
        SkillRegistry.register(BuySkill)
        result = SkillRegistry.list_for_aop(["test.search", "test.ping", "test.buy"])
        assert result == [SearchSkill, PingSkill, BuySkill]
