"""Thinking y esfuerzo por rol: qué se manda a cada modelo y qué se rechaza al cargar."""

from __future__ import annotations

import pytest
from apps.api.core.config import ModelRegistry
from apps.api.integrations.model_capabilities import (
    MODEL_CAPABILITIES,
    UnsupportedModelSetting,
    thinking_settings,
)
from apps.api.integrations.pricing import LLM_PRICING_PER_MILLION_TOKENS
from pydantic import ValidationError

_PRESERVED = {
    "thinking": {
        "type": "adaptive",
        "block_binding": {"prefix_mismatch_behavior": "drop_block"},
    },
    "output_config": {"effort": "medium"},
    "extra_headers": {"anthropic-beta": "thinking-binding-controls-2026-08-01"},
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ModelRegistry.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    return monkeypatch


class TestThinkingSettings:
    @pytest.mark.parametrize(
        "model", ["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"]
    )
    def test_current_models_send_nothing_new(self, model: str) -> None:
        assert thinking_settings(model, mode=None, effort=None).request_options() == {}

    @pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-opus-5-5"])
    def test_5_5_models_send_adaptive_and_explicit_effort(self, model: str) -> None:
        assert thinking_settings(model, mode=None, effort=None).request_options() == _PRESERVED

    def test_role_effort_overrides_the_model_default(self) -> None:
        options = thinking_settings("claude-opus-5-5", mode=None, effort="low").request_options()
        assert options["output_config"] == {"effort": "low"}

    def test_sonnet_5_5_thinking_off_is_between_tools(self) -> None:
        options = thinking_settings("claude-sonnet-5-5", mode="off", effort="low").request_options()
        assert options == {
            "thinking": {"type": "between_tools"},
            "output_config": {"effort": "low"},
        }

    def test_sonnet_4_6_role_effort_is_sent_without_thinking(self) -> None:
        options = thinking_settings("claude-sonnet-4-6", mode=None, effort="low").request_options()
        assert options == {"output_config": {"effort": "low"}}

    def test_sonnet_4_6_adaptive_needs_no_beta(self) -> None:
        options = thinking_settings("claude-sonnet-4-6", mode="adaptive", effort=None)
        assert options.request_options() == {"thinking": {"type": "adaptive"}}
        assert options.thinking_on

    @pytest.mark.parametrize(
        ("model", "mode", "effort"),
        [
            ("claude-opus-5-5", "off", None),
            ("claude-sonnet-5-5", "off", "xhigh"),
            ("claude-haiku-4-5-20251001", None, "low"),
            ("claude-haiku-4-5-20251001", "adaptive", None),
            ("claude-sonnet-4-6", None, "xhigh"),
        ],
    )
    def test_rejects_what_the_model_answers_with_a_400(
        self, model: str, mode: str | None, effort: str | None
    ) -> None:
        with pytest.raises(UnsupportedModelSetting):
            thinking_settings(model, mode=mode, effort=effort)  # type: ignore[arg-type]

    def test_unknown_model_sends_nothing_and_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("ERROR"):
            options = thinking_settings("claude-future-99", mode=None, effort=None)
        assert options.request_options() == {}
        assert any("claude-future-99" in r.getMessage() for r in caplog.records)


class TestRegistryRoleSettings:
    def test_defaults_send_nothing_new_for_any_role(self, clean_env: pytest.MonkeyPatch) -> None:
        registry = ModelRegistry(_env_file=None)  # type: ignore[call-arg]
        assert {role: registry.thinking(role).request_options() for role in registry.by_role()} == {
            role: {} for role in registry.by_role()
        }

    def test_moving_a_role_to_5_5_is_an_env_change(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("INTENT_CLASSIFIER_MODEL", "claude-sonnet-5-5")
        clean_env.setenv("THINKING_BY_ROLE", '{"intent_classifier_model": "off"}')
        clean_env.setenv("EFFORT_BY_ROLE", '{"intent_classifier_model": "low"}')
        registry = ModelRegistry(_env_file=None)  # type: ignore[call-arg]
        assert registry.thinking("intent_classifier_model").request_options() == {
            "thinking": {"type": "between_tools"},
            "output_config": {"effort": "low"},
        }

    def test_tenant_model_uses_the_role_settings(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("EFFORT_BY_ROLE", '{"default_agent_model": "high"}')
        registry = ModelRegistry(_env_file=None)  # type: ignore[call-arg]
        options = registry.thinking("default_agent_model", model="claude-opus-5-5")
        assert options.request_options()["output_config"] == {"effort": "high"}

    def test_rejects_a_setting_the_role_model_would_400_at_load(
        self, clean_env: pytest.MonkeyPatch
    ) -> None:
        clean_env.setenv("EFFORT_BY_ROLE", '{"intent_classifier_model": "low"}')
        with pytest.raises(ValidationError, match="no acepta esfuerzo"):
            ModelRegistry(_env_file=None)  # type: ignore[call-arg]

    def test_rejects_unknown_roles(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("EFFORT_BY_ROLE", '{"reasoner": "low"}')
        with pytest.raises(ValidationError, match="reasoner"):
            ModelRegistry(_env_file=None)  # type: ignore[call-arg]

    def test_by_role_lists_only_models(self, clean_env: pytest.MonkeyPatch) -> None:
        registry = ModelRegistry(_env_file=None)  # type: ignore[call-arg]
        roles = registry.by_role()
        assert "effort_by_role" not in roles
        assert "thinking_by_role" not in roles
        assert roles["supervisor_model_l3"] == registry.supervisor_model_l3


def test_every_model_with_capabilities_has_a_price() -> None:
    assert set(MODEL_CAPABILITIES) == set(LLM_PRICING_PER_MILLION_TOKENS)
