"""Cálculo de costo por llamada al LLM.

Las tarifas están hardcodeadas aquí porque cambian con poca frecuencia y se
auditan por revisión de código. Verificar contra docs.anthropic.com antes de
cada release.

Si el modelo no está en la tabla, devolvemos 0.0 — preferible a inflar costo
con un valor inventado. Si ves $0 en Langfuse, agregá la fila acá.
"""

from __future__ import annotations

# USD por millón de tokens. Actualizado 2026-05-13.
# Verificar contra docs.anthropic.com antes de cada production deploy.
#
# Nota Opus 4.7: el modelo usa un tokenizer actualizado. El mismo texto puede
# mapearse a 1.0–1.35× tokens vs. versiones previas (ver
# https://www.anthropic.com/news/claude-opus-4-7).
# Implicancia operativa: aunque el precio por token no cambió respecto a 4.6,
# el costo efectivo por conversación puede subir hasta ~35% sólo por la
# tokenización. Calibrar budgets, context windows y comparaciones históricas
# con esto en cuenta.
LLM_PRICING_PER_MILLION_TOKENS: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
}


def compute_llm_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Costo en USD de una llamada al LLM. 0.0 si el modelo es desconocido."""
    rate = LLM_PRICING_PER_MILLION_TOKENS.get(model)
    if rate is None:
        return 0.0
    return (input_tokens * rate["input"] + output_tokens * rate["output"]) / 1_000_000
