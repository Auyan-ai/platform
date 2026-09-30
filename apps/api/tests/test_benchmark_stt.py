"""Métricas del mini-benchmark de voz a texto (scripts/benchmark_stt.py)."""

from __future__ import annotations

from apps.api.scripts.benchmark_stt import (
    SampleResult,
    critical_tokens,
    normalize_words,
    percentile,
    summarize,
    word_error_rate,
)


def test_normalize_ignores_case_accents_and_punctuation() -> None:
    assert normalize_words("¡Hola, Pedído #1432!") == ["hola", "pedido", "#1432"]


def test_wer() -> None:
    assert word_error_rate("mi pedido es el 1432", "mi pedido es el 1432") == 0.0
    assert word_error_rate("mi pedido es el 1432", "mi pedido es 1423") == 0.4
    assert word_error_rate("", "") == 0.0


def test_critical_tokens_are_orders_and_emails() -> None:
    assert critical_tokens("el #1432 y ana.lopez@gmail.com") == {"1432", "ana.lopez@gmail.com"}


def test_summary() -> None:
    results = [
        SampleResult("a", 0.1, 2, 2, 100, 5.0, 0.001),
        SampleResult("b", 0.3, 1, 0, 300, 5.0, 0.001),
    ]
    summary = summarize(results)
    assert summary["wer_mean"] == 0.2
    assert summary["critical_accuracy"] == round(2 / 3, 4)
    assert percentile([100.0, 300.0], 50) in (100.0, 300.0)
