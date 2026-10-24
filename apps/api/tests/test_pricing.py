"""Tests del cálculo de costo del LLM.

Los `usage` se construyen con la forma JSON que devuelve la API de Anthropic y los
parsea el SDK, igual que en producción.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from anthropic.types import Usage
from apps.api.core.config import ModelRegistry, get_models
from apps.api.integrations.pricing import (
    LLM_PRICING_PER_MILLION_TOKENS,
    LLMUsage,
    check_model_prices,
    compute_llm_cost,
    fallback_rates,
    models_without_price,
)


def _api_usage(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_write: int = 0,
    cache_read: int = 0,
    cache_write_1h: int = 0,
) -> Usage:
    raw: dict[str, Any] = {
        "input_tokens": input_tokens,
        "cache_creation_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read,
        "cache_creation": {
            "ephemeral_5m_input_tokens": cache_write - cache_write_1h,
            "ephemeral_1h_input_tokens": cache_write_1h,
        },
        "output_tokens": output_tokens,
        "service_tier": "standard",
    }
    return Usage.model_validate(raw)


def _cost(model: str, usage: Usage) -> float:
    return compute_llm_cost(model, LLMUsage.from_anthropic(usage))


class TestComputeLlmCost:
    def test_without_cache(self) -> None:
        # 1000 in @ $3 + 200 out @ $15 = $0.006
        usage = _api_usage(input_tokens=1000, output_tokens=200)
        assert _cost("claude-sonnet-4-6", usage) == pytest.approx(0.006)

    def test_cache_write_5m_charged_at_1_25x(self) -> None:
        # 1684 in @ $3 + 3426 escritos @ $3.75 + 166 out @ $15 = $0.0203895
        usage = _api_usage(input_tokens=1684, output_tokens=166, cache_write=3426)
        assert _cost("claude-sonnet-4-6", usage) == pytest.approx(0.0203895)

    def test_cache_read_charged_at_0_1x(self) -> None:
        # Caso medido en #331: in=1684 cache_r=3426 out=166.
        # 1684 @ $3 + 3426 leídos @ $0.30 + 166 @ $15 = $0.0085698 (antes: $0.007542).
        usage = _api_usage(input_tokens=1684, output_tokens=166, cache_read=3426)
        assert _cost("claude-sonnet-4-6", usage) == pytest.approx(0.0085698)

    def test_cache_read_adds_its_cost(self) -> None:
        # 1000 leídos en Opus 4.7 @ $0.50 = $0.0005 sobre la misma llamada sin caché.
        without = _api_usage(input_tokens=500, output_tokens=100)
        with_read = _api_usage(input_tokens=500, output_tokens=100, cache_read=1000)
        extra = _cost("claude-opus-4-7", with_read) - _cost("claude-opus-4-7", without)
        assert extra == pytest.approx(0.0005)

    def test_cache_write_1h_charged_at_2x(self) -> None:
        # 2000 escritos @ 5m $3.75 + 1000 escritos @ 1h $6 = $0.0135
        usage = _api_usage(input_tokens=0, output_tokens=0, cache_write=3000, cache_write_1h=1000)
        assert _cost("claude-sonnet-4-6", usage) == pytest.approx(0.0135)

    def test_haiku_cache_read(self) -> None:
        # 100 in @ $1 + 4000 leídos @ $0.10 + 50 out @ $5 = $0.00075
        usage = _api_usage(input_tokens=100, output_tokens=50, cache_read=4000)
        assert _cost("claude-haiku-4-5-20251001", usage) == pytest.approx(0.00075)

    def test_unknown_model_is_charged_at_the_most_expensive_rates(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Modelo desconocido → tarifa más cara de la tabla (nunca $0) y log de error."""
        usage = _api_usage(input_tokens=1000, output_tokens=500, cache_read=900)
        with caplog.at_level("ERROR"):
            cost = _cost("claude-future-99", usage)
        # Opus 4.7 es la fila más cara en todas las categorías hoy:
        # 1000 in a $5 + 900 cache read a $0.50 + 500 out a $25, por millón.
        assert cost == pytest.approx(0.01795)
        assert cost > 0.0
        assert any(
            r.levelname == "ERROR" and "claude-future-99" in r.getMessage() for r in caplog.records
        )

    def test_fallback_rates_take_the_max_of_each_category(self) -> None:
        rates = fallback_rates()
        rows = LLM_PRICING_PER_MILLION_TOKENS.values()
        assert rates.input == max(r.input for r in rows)
        assert rates.output == max(r.output for r in rows)
        assert rates.cache_read == max(r.cache_read for r in rows)

    def test_check_model_prices_reports_roles_without_price(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("ERROR"):
            missing = check_model_prices(
                {"agent": "claude-sonnet-4-6", "judge": "claude-future-99"}
            )
        assert missing == ["judge"]
        assert any("role=judge" in r.getMessage() for r in caplog.records)

    def test_check_model_prices_is_silent_when_all_priced(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("ERROR"):
            assert check_model_prices({"agent": "claude-sonnet-4-6"}) == []
        assert caplog.records == []

    def test_every_configured_model_has_a_price(self) -> None:
        """Si añades o cambias un rol en ModelRegistry, añade su fila en pricing.py."""
        models = get_models().by_role()
        assert len(models) >= 10
        assert models_without_price(models) == {}

    def test_every_configured_model_is_priced_even_with_env_defaults_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ModelRegistry.model_fields:
            monkeypatch.delenv(name.upper(), raising=False)
        registry = ModelRegistry(_env_file=None)  # type: ignore[call-arg]
        assert models_without_price(registry.by_role()) == {}

    def test_env_var_overrides_a_role(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUPERVISOR_MODEL_L3", "claude-future-99")
        registry = ModelRegistry(_env_file=None)  # type: ignore[call-arg]
        assert registry.supervisor_model_l3 == "claude-future-99"
        assert models_without_price(registry.by_role()) == {
            "supervisor_model_l3": "claude-future-99"
        }

    def test_zero_tokens(self) -> None:
        assert compute_llm_cost("claude-sonnet-4-6", LLMUsage()) == 0.0

    def test_pricing_table_has_expected_models(self) -> None:
        """Smoke test: asegurar que no se eliminó accidentalmente un modelo soportado."""
        assert set(LLM_PRICING_PER_MILLION_TOKENS) >= {
            "claude-sonnet-4-6",
            "claude-opus-4-7",
            "claude-haiku-4-5-20251001",
        }


class TestModels55Pricing:
    """Tarifas de la tabla del skill `claude-api` (2026-09-25): la caché de cada modelo es
    suya, así que el primer día tras el cambio se pagan escrituras."""

    def test_sonnet_5_5_with_cache_write_and_read(self) -> None:
        # 1000 in @ $2 + 1000 escritos 5m @ $2.50 + 2000 leídos @ $0.20 + 200 out @ $10
        usage = _api_usage(input_tokens=1000, output_tokens=200, cache_write=1000, cache_read=2000)
        assert _cost("claude-sonnet-5-5", usage) == pytest.approx(0.0069)

    def test_opus_5_5_with_cache_write_and_read(self) -> None:
        # 1000 in @ $4 + 1000 escritos 5m @ $5 + 2000 leídos @ $0.20 + 200 out @ $20
        usage = _api_usage(input_tokens=1000, output_tokens=200, cache_write=1000, cache_read=2000)
        assert _cost("claude-opus-5-5", usage) == pytest.approx(0.0134)

    def test_opus_5_5_cache_write_1h(self) -> None:
        # 1000 escritos 1h @ $8
        usage = _api_usage(input_tokens=0, output_tokens=0, cache_write=1000, cache_write_1h=1000)
        assert _cost("claude-opus-5-5", usage) == pytest.approx(0.008)

    def test_5_5_models_are_cheaper_than_the_ones_they_replace(self) -> None:
        usage = _api_usage(input_tokens=5000, output_tokens=800, cache_read=3000)
        assert _cost("claude-sonnet-5-5", usage) < _cost("claude-sonnet-4-6", usage)
        assert _cost("claude-opus-5-5", usage) < _cost("claude-opus-4-7", usage)


class TestLlmUsageSum:
    def test_adds_every_category(self) -> None:
        a = LLMUsage(input_tokens=1, cache_write_5m_tokens=2, cache_read_tokens=3, output_tokens=4)
        b = LLMUsage(
            input_tokens=10, cache_write_1h_tokens=20, cache_read_tokens=30, output_tokens=40
        )
        assert a + b == LLMUsage(
            input_tokens=11,
            cache_write_5m_tokens=2,
            cache_write_1h_tokens=20,
            cache_read_tokens=33,
            output_tokens=44,
        )


class TestLlmUsageFromAnthropic:
    def test_prompt_tokens_include_cache(self) -> None:
        usage = LLMUsage.from_anthropic(
            _api_usage(input_tokens=1684, output_tokens=166, cache_write=200, cache_read=3426)
        )
        assert usage == LLMUsage(
            input_tokens=1684,
            cache_write_5m_tokens=200,
            cache_write_1h_tokens=0,
            cache_read_tokens=3426,
            output_tokens=166,
        )
        assert usage.prompt_tokens == 5310
        assert usage.cache_write_tokens == 200

    def test_missing_cache_fields_count_zero(self) -> None:
        raw = MagicMock(spec=["input_tokens", "output_tokens"])
        raw.input_tokens = 30
        raw.output_tokens = 4
        assert LLMUsage.from_anthropic(raw) == LLMUsage(input_tokens=30, output_tokens=4)

    def test_write_without_ttl_breakdown_is_5m(self) -> None:
        raw = Usage.model_validate(
            {"input_tokens": 10, "output_tokens": 1, "cache_creation_input_tokens": 500}
        )
        usage = LLMUsage.from_anthropic(raw)
        assert usage.cache_write_5m_tokens == 500
        assert usage.cache_write_1h_tokens == 0
