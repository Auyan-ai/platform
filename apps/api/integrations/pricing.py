"""Cálculo de costo por llamada al LLM.

Las tarifas están hardcodeadas aquí porque cambian con poca frecuencia y se
auditan por revisión de código. Verificar contra
https://platform.claude.com/docs/en/about-claude/pricing antes de cada release.

Un modelo sin fila nunca cuesta $0: un cobro en cero dejaría pasar los topes de
`services/usage.py` y `cost_guard`. Se cobra a la tarifa más cara de la tabla
y se loguea como `error`. Agregá la fila acá; un test y el arranque de la API
avisan si un modelo configurado no la tiene.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelRates:
    """USD por millón de tokens, una tarifa por categoría de token de entrada.

    La lectura de caché no es un múltiplo fijo en todos los modelos (0,1x en los
    de esta tabla, menos en modelos más nuevos), así que cada fila la lleva explícita.
    """

    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float


# Verificado contra la página de precios el 2026-10-12.
#
# Nota Opus 4.7: el modelo usa un tokenizer actualizado. El mismo texto puede
# mapearse a 1.0–1.35× tokens vs. versiones previas (ver
# https://www.anthropic.com/news/claude-opus-4-7).
# Implicancia operativa: aunque el precio por token no cambió respecto a 4.6,
# el costo efectivo por conversación puede subir hasta ~35% sólo por la
# tokenización. Calibrar budgets, context windows y comparaciones históricas
# con esto en cuenta.
LLM_PRICING_PER_MILLION_TOKENS: dict[str, ModelRates] = {
    "claude-sonnet-4-6": ModelRates(
        input=3.0, cache_write_5m=3.75, cache_write_1h=6.0, cache_read=0.30, output=15.0
    ),
    "claude-opus-4-7": ModelRates(
        input=5.0, cache_write_5m=6.25, cache_write_1h=10.0, cache_read=0.50, output=25.0
    ),
    "claude-haiku-4-5-20251001": ModelRates(
        input=1.0, cache_write_5m=1.25, cache_write_1h=2.0, cache_read=0.10, output=5.0
    ),
}


def fallback_rates() -> ModelRates:
    """Tarifa más cara de la tabla, categoría a categoría: conservadora para los topes."""
    rows = LLM_PRICING_PER_MILLION_TOKENS.values()
    return ModelRates(
        input=max(r.input for r in rows),
        cache_write_5m=max(r.cache_write_5m for r in rows),
        cache_write_1h=max(r.cache_write_1h for r in rows),
        cache_read=max(r.cache_read for r in rows),
        output=max(r.output for r in rows),
    )


def models_without_price(models: dict[str, str]) -> dict[str, str]:
    """Subconjunto de `rol -> modelo` cuyo modelo no tiene fila en la tabla."""
    return {
        role: model
        for role, model in models.items()
        if model not in LLM_PRICING_PER_MILLION_TOKENS
    }


def check_model_prices(models: dict[str, str]) -> list[str]:
    """Loguea como `error` cada rol cuyo modelo no tiene precio. Devuelve los roles afectados."""
    missing = models_without_price(models)
    for role, model in missing.items():
        logger.error(
            "model_without_price role=%s model=%s: agregá la fila en integrations/pricing.py; "
            "mientras tanto se cobra a la tarifa más cara",
            role,
            model,
            extra={"role": role, "model": model},
        )
    return sorted(missing)


@dataclass(frozen=True)
class LLMUsage:
    """Tokens de una llamada, separados por tarifa.

    En la API de Anthropic `input_tokens` es solo la parte NO cacheada del prompt:
    el prompt completo es `input_tokens + cache_write + cache_read`.
    """

    input_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0

    @property
    def cache_write_tokens(self) -> int:
        return self.cache_write_5m_tokens + self.cache_write_1h_tokens

    @property
    def prompt_tokens(self) -> int:
        """Tokens de entrada que vio el modelo, cacheados o no."""
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens

    @classmethod
    def from_anthropic(cls, usage: Any) -> LLMUsage:
        """Parsea `response.usage`. Un contador ausente o no entero cuenta 0: una
        respuesta sin caching no trae los campos de caché."""
        cache_write = _int_field(usage, "cache_creation_input_tokens")
        # `cache_creation` desglosa la escritura por TTL. Con el SDK fijado (0.40)
        # llega como dict sin tipar; si falta, toda la escritura es de 5 minutos,
        # el TTL por defecto de `cache_control: ephemeral`.
        cache_write_1h = _int_field(
            getattr(usage, "cache_creation", None), "ephemeral_1h_input_tokens"
        )
        return cls(
            input_tokens=_int_field(usage, "input_tokens"),
            cache_write_5m_tokens=max(cache_write - cache_write_1h, 0),
            cache_write_1h_tokens=cache_write_1h,
            cache_read_tokens=_int_field(usage, "cache_read_input_tokens"),
            output_tokens=_int_field(usage, "output_tokens"),
        )


def _int_field(source: Any, name: str) -> int:
    value = source.get(name) if isinstance(source, dict) else getattr(source, name, None)
    return value if isinstance(value, int) else 0


def compute_llm_cost(model: str, usage: LLMUsage) -> float:
    """Costo en USD de una llamada al LLM. Un modelo desconocido se cobra a `fallback_rates()`."""
    rate = LLM_PRICING_PER_MILLION_TOKENS.get(model)
    if rate is None:
        logger.error(
            "model_without_price model=%s: cobrado a la tarifa más cara de la tabla",
            model,
            extra={"model": model},
        )
        rate = fallback_rates()
    return (
        usage.input_tokens * rate.input
        + usage.cache_write_5m_tokens * rate.cache_write_5m
        + usage.cache_write_1h_tokens * rate.cache_write_1h
        + usage.cache_read_tokens * rate.cache_read
        + usage.output_tokens * rate.output
    ) / 1_000_000
