"""Tests del cálculo de costo del LLM."""

from __future__ import annotations

import pytest

from apps.api.integrations.pricing import (
    LLM_PRICING_PER_MILLION_TOKENS,
    compute_llm_cost,
)


class TestComputeLlmCost:
    def test_sonnet_4_6(self) -> None:
        # 1M input @ $3 + 1M output @ $15 = $18
        cost = compute_llm_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0)

    def test_opus_4_7(self) -> None:
        # 100k input @ $5 + 50k output @ $25 = $0.5 + $1.25 = $1.75
        cost = compute_llm_cost("claude-opus-4-7", 100_000, 50_000)
        assert cost == pytest.approx(1.75)

    def test_haiku_4_5(self) -> None:
        # 1M input @ $1 + 1M output @ $5 = $6
        cost = compute_llm_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        assert cost == pytest.approx(6.0)

    def test_unknown_model_returns_zero(self) -> None:
        """Modelo desconocido → 0.0. Señal visible en Langfuse de 'agregar fila'."""
        assert compute_llm_cost("claude-future-99", 1000, 500) == 0.0

    def test_zero_tokens(self) -> None:
        assert compute_llm_cost("claude-sonnet-4-6", 0, 0) == 0.0

    def test_pricing_table_has_expected_models(self) -> None:
        """Smoke test: asegurar que no se eliminó accidentalmente un modelo soportado."""
        assert "claude-sonnet-4-6" in LLM_PRICING_PER_MILLION_TOKENS
        assert "claude-opus-4-7" in LLM_PRICING_PER_MILLION_TOKENS
        assert "claude-haiku-4-5-20251001" in LLM_PRICING_PER_MILLION_TOKENS
