"""Tests para skills/base.py: Skill ABC, SkillInput, SkillOutput, SkillContext, to_anthropic_tool."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from pydantic import ValidationError

# ----------------------------------------------------------------
# Skill concreta mínima para probar el framework
# ----------------------------------------------------------------


class GreetInput(SkillInput):
    name: str


class GreetOutput(SkillOutput):
    message: str


class GreetSkill(Skill):
    slug = "test.greet"
    description = "Says hello to someone."
    tier: SkillTier = "L1"
    input_schema = GreetInput
    output_schema = GreetOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, GreetInput)
        return GreetOutput(message=f"Hello, {inputs.name}!")


# ----------------------------------------------------------------
# Skill L3 para verificar que requires_idempotency se hereda/overridea
# ----------------------------------------------------------------


class RefundInput(SkillInput):
    order_id: str
    amount: float


class RefundOutput(SkillOutput):
    success: bool
    refund_id: str


class RefundSkill(Skill):
    slug = "test.refund"
    description = "Issues a refund."
    tier: SkillTier = "L3"
    input_schema = RefundInput
    output_schema = RefundOutput
    requires_idempotency = True
    default_threshold = 0.95

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, RefundInput)
        return RefundOutput(success=True, refund_id="ref-001")


# ----------------------------------------------------------------
# Tests
# ----------------------------------------------------------------


class TestSkillInstantiation:
    def test_concrete_skill_instantiates(self) -> None:
        skill = GreetSkill()
        assert skill.slug == "test.greet"
        assert skill.description == "Says hello to someone."
        assert skill.tier == "L1"
        assert skill.default_threshold == 0.70

    def test_requires_idempotency_default_false(self) -> None:
        assert GreetSkill.requires_idempotency is False

    def test_requires_idempotency_override_true(self) -> None:
        assert RefundSkill.requires_idempotency is True

    def test_abstract_skill_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            Skill()  # type: ignore[abstract]

    def test_classvar_accessible_via_instance(self) -> None:
        skill = GreetSkill()
        assert skill.input_schema is GreetInput
        assert skill.output_schema is GreetOutput


class TestSkillInput:
    def test_valid_input_constructs(self) -> None:
        inp = GreetInput(name="Kenny")
        assert inp.name == "Kenny"

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            GreetInput()  # type: ignore[call-arg]

    def test_is_pydantic_model(self) -> None:
        from pydantic import BaseModel

        assert issubclass(GreetInput, BaseModel)

    def test_base_skill_input_has_no_required_fields(self) -> None:
        inp = SkillInput()
        assert inp.model_dump() == {}


class TestSkillOutput:
    def test_valid_output_constructs(self) -> None:
        out = GreetOutput(message="Hello!")
        assert out.message == "Hello!"

    def test_is_pydantic_model(self) -> None:
        from pydantic import BaseModel

        assert issubclass(GreetOutput, BaseModel)

    def test_base_skill_output_has_no_required_fields(self) -> None:
        out = SkillOutput()
        assert out.model_dump() == {}


class TestSkillContext:
    def test_context_stores_ids(self) -> None:
        ctx = SkillContext(tenant_id="tenant-abc", conversation_id="conv-xyz")
        assert ctx.tenant_id == "tenant-abc"
        assert ctx.conversation_id == "conv-xyz"

    def test_context_is_frozen(self) -> None:
        ctx = SkillContext(tenant_id="t", conversation_id="c")
        with pytest.raises(FrozenInstanceError):
            ctx.tenant_id = "other"  # type: ignore[misc]

    def test_context_equality(self) -> None:
        a = SkillContext(tenant_id="t", conversation_id="c")
        b = SkillContext(tenant_id="t", conversation_id="c")
        assert a == b


class TestToAnthropicTool:
    def test_returns_required_keys(self) -> None:
        tool = GreetSkill().to_anthropic_tool()
        assert set(tool.keys()) == {"name", "description", "input_schema"}

    def test_name_replaces_dots_with_underscores(self) -> None:
        tool = GreetSkill().to_anthropic_tool()
        assert tool["name"] == "test_greet"
        assert "." not in tool["name"]

    def test_description_preserved(self) -> None:
        tool = GreetSkill().to_anthropic_tool()
        assert tool["description"] == "Says hello to someone."

    def test_input_schema_is_json_schema_object(self) -> None:
        tool = GreetSkill().to_anthropic_tool()
        schema: dict[str, Any] = tool["input_schema"]
        assert schema["type"] == "object"

    def test_input_schema_has_properties(self) -> None:
        tool = GreetSkill().to_anthropic_tool()
        schema: dict[str, Any] = tool["input_schema"]
        assert "name" in schema.get("properties", {})

    def test_input_schema_marks_required_fields(self) -> None:
        tool = GreetSkill().to_anthropic_tool()
        schema: dict[str, Any] = tool["input_schema"]
        assert "name" in schema.get("required", [])

    def test_multi_segment_slug_underscored(self) -> None:
        tool = RefundSkill().to_anthropic_tool()
        assert tool["name"] == "test_refund"

    def test_empty_input_schema_still_valid(self) -> None:
        class NoInput(SkillInput):
            pass

        class NoOutput(SkillOutput):
            pass

        class NoInputSkill(Skill):
            slug = "test.noinput"
            description = "No inputs needed."
            tier: SkillTier = "L1"
            input_schema = NoInput
            output_schema = NoOutput
            default_threshold = 0.70

            async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
                return NoOutput()

        tool = NoInputSkill().to_anthropic_tool()
        schema: dict[str, Any] = tool["input_schema"]
        assert schema["type"] == "object"


class TestExecute:
    async def test_execute_returns_correct_output(self) -> None:
        skill = GreetSkill()
        ctx = SkillContext(tenant_id="t", conversation_id="c")
        inp = GreetInput(name="Kenny")
        result = await skill.execute(ctx, inp)
        assert isinstance(result, GreetOutput)
        assert result.message == "Hello, Kenny!"

    async def test_execute_l3_returns_correct_output(self) -> None:
        skill = RefundSkill()
        ctx = SkillContext(tenant_id="t", conversation_id="c")
        inp = RefundInput(order_id="order-1", amount=29.99)
        result = await skill.execute(ctx, inp)
        assert isinstance(result, RefundOutput)
        assert result.success is True
