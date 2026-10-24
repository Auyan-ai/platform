"""Qué acepta cada modelo de Claude en la petición, en una sola tabla.

Los nodos no preguntan por el ID del modelo: piden una decisión estructurada o un texto
(`integrations/anthropic_client.py`) y esa pieza traduce la petición con esta tabla y con
lo que el registro (`ModelRegistry`) fija por rol. Pasar un rol a otro modelo es un cambio
de configuración: el modelo nuevo necesita su fila aquí y en `integrations/pricing.py`.

Fuente: skill `claude-api` (tabla de modelos del 2026-09-25 y `shared/model-migration.md`,
secciones Opus 4.7, Sonnet 5.5 y Opus 5.5).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

Effort = Literal["low", "medium", "high", "xhigh", "max"]
ThinkingMode = Literal["off", "adaptive"]

_ALL_EFFORTS: frozenset[Effort] = frozenset({"low", "medium", "high", "xhigh", "max"})
_BETWEEN_TOOLS_EFFORTS: frozenset[Effort] = frozenset({"low", "medium", "high"})
PRESERVED_THINKING_BETA = "thinking-binding-controls-2026-08-01"


class UnsupportedModelSetting(ValueError):
    """La combinación rol + modelo pide algo que el modelo rechaza con un 400."""


@dataclass(frozen=True)
class ModelCapabilities:
    """Lo que un modelo acepta. Cada campo corresponde a un 400 conocido si se ignora."""

    # `tool_choice` `any` / `tool`. Sin esto: `auto` + instrucción (+ `strict`).
    forced_tool_choice: bool
    # `strict: true` en la definición de una tool (structured outputs).
    strict_tools: bool
    # `temperature` / `top_p` / `top_k`.
    sampling_params: bool
    # Thinking que corre si el rol no elige.
    default_thinking: ThinkingMode
    # Cómo se apaga el thinking: "omit" (no mandar `thinking`), "between_tools", o None
    # si no se puede apagar.
    thinking_off: Literal["omit", "between_tools"] | None
    adaptive_thinking: bool
    efforts: frozenset[Effort]
    # Esfuerzo que se manda explícito si el rol no elige. None: no se manda.
    default_effort: Effort | None
    # Thinking blocks atados al modelo y a la conversación (preserved thinking).
    preserved_thinking: bool
    # Mensajes `role: system` a mitad de conversación (instrucciones del operador sin
    # editar el system de arriba).
    system_messages: bool


MODEL_CAPABILITIES: dict[str, ModelCapabilities] = {
    "claude-haiku-4-5-20251001": ModelCapabilities(
        forced_tool_choice=True,
        strict_tools=True,
        sampling_params=True,
        default_thinking="off",
        thinking_off="omit",
        adaptive_thinking=False,
        efforts=frozenset(),
        default_effort=None,
        preserved_thinking=False,
        system_messages=False,
    ),
    "claude-sonnet-4-6": ModelCapabilities(
        forced_tool_choice=True,
        strict_tools=False,
        sampling_params=True,
        default_thinking="off",
        thinking_off="omit",
        adaptive_thinking=True,
        efforts=frozenset({"low", "medium", "high", "max"}),
        default_effort=None,
        preserved_thinking=False,
        system_messages=False,
    ),
    "claude-opus-4-7": ModelCapabilities(
        forced_tool_choice=True,
        strict_tools=False,
        sampling_params=False,
        default_thinking="off",
        thinking_off="omit",
        adaptive_thinking=True,
        efforts=_ALL_EFFORTS,
        default_effort=None,
        preserved_thinking=False,
        system_messages=False,
    ),
    # Sonnet 5.5: `disabled` da 400 (se apaga con `between_tools`); esfuerzo explícito
    # porque los niveles se recalibraron.
    "claude-sonnet-5-5": ModelCapabilities(
        forced_tool_choice=False,
        strict_tools=True,
        sampling_params=False,
        default_thinking="adaptive",
        thinking_off="between_tools",
        adaptive_thinking=True,
        efforts=_ALL_EFFORTS,
        default_effort="medium",
        preserved_thinking=True,
        system_messages=True,
    ),
    # Opus 5.5: el thinking no se apaga; su esfuerzo por defecto en la API es `medium`
    # y se manda explícito.
    "claude-opus-5-5": ModelCapabilities(
        forced_tool_choice=False,
        strict_tools=True,
        sampling_params=False,
        default_thinking="adaptive",
        thinking_off=None,
        adaptive_thinking=True,
        efforts=_ALL_EFFORTS,
        default_effort="medium",
        preserved_thinking=True,
        system_messages=True,
    ),
}

# Modelo sin fila: la petición que acepta cualquier modelo actual (sin forzar tool, sin
# thinking ni esfuerzo explícitos, sin parámetros de muestreo).
UNKNOWN_MODEL_CAPABILITIES = ModelCapabilities(
    forced_tool_choice=False,
    strict_tools=False,
    sampling_params=False,
    default_thinking="off",
    thinking_off="omit",
    adaptive_thinking=False,
    efforts=frozenset(),
    default_effort=None,
    preserved_thinking=False,
    system_messages=False,
)


def capabilities_of(model: str) -> ModelCapabilities:
    caps = MODEL_CAPABILITIES.get(model)
    if caps is None:
        logger.error(
            "model_without_capabilities model=%s: agregá la fila en "
            "integrations/model_capabilities.py; mientras tanto la petición va sin forzar "
            "tool ni fijar thinking",
            model,
            extra={"model": model},
        )
        return UNKNOWN_MODEL_CAPABILITIES
    return caps


@dataclass(frozen=True)
class ThinkingSettings:
    """Thinking y esfuerzo que se mandan en una petición, ya validados para el modelo."""

    thinking: dict[str, Any] | None
    effort: Effort | None
    beta: str | None

    @property
    def thinking_on(self) -> bool:
        return self.thinking is not None and self.thinking["type"] == "adaptive"

    @property
    def writes_thinking_blocks(self) -> bool:
        """Adaptive piensa; `between_tools` no piensa, pero escribe notas de progreso como
        thinking blocks antes de cada tool. Las dos cuentan contra `max_tokens`."""
        return self.thinking is not None

    def request_options(self) -> dict[str, Any]:
        """Campos de `messages.create`. Vacío en los modelos actuales sin elección por rol."""
        options: dict[str, Any] = {}
        if self.thinking is not None:
            options["thinking"] = self.thinking
        if self.effort is not None:
            options["output_config"] = {"effort": self.effort}
        if self.beta is not None:
            options["extra_headers"] = {"anthropic-beta": self.beta}
        return options


def thinking_settings(
    model: str, *, mode: ThinkingMode | None, effort: Effort | None
) -> ThinkingSettings:
    """Traduce lo que pide un rol (o el default del modelo) a la petición de `model`.

    Lanza `UnsupportedModelSetting` si el modelo rechazaría la combinación con un 400.
    """
    caps = capabilities_of(model)
    resolved_mode = mode or caps.default_thinking
    resolved_effort = effort or caps.default_effort
    if resolved_effort is not None and resolved_effort not in caps.efforts:
        raise UnsupportedModelSetting(f"{model} no acepta esfuerzo '{resolved_effort}'")

    if resolved_mode == "adaptive":
        if not caps.adaptive_thinking:
            raise UnsupportedModelSetting(f"{model} no acepta thinking adaptive")
        thinking: dict[str, Any] = {"type": "adaptive"}
        if not caps.preserved_thinking:
            return ThinkingSettings(thinking=thinking, effort=resolved_effort, beta=None)
        # El loop ReAct mantiene el prefijo (hora fija; feedback y cierre como mensajes),
        # pero lo que entra al system a mitad de turno (datos verificados, identidad) lo
        # cambia: `drop_block` descarta lo que ya no vale en vez de dar 400. Con
        # `between_tools` no se admite y el cliente quita esos bloques (anthropic_client).
        thinking["block_binding"] = {"prefix_mismatch_behavior": "drop_block"}
        return ThinkingSettings(
            thinking=thinking, effort=resolved_effort, beta=PRESERVED_THINKING_BETA
        )

    if caps.thinking_off is None:
        raise UnsupportedModelSetting(f"{model} no permite apagar el thinking")
    if caps.thinking_off == "omit":
        return ThinkingSettings(thinking=None, effort=resolved_effort, beta=None)
    if resolved_effort is not None and resolved_effort not in _BETWEEN_TOOLS_EFFORTS:
        raise UnsupportedModelSetting(
            f"{model} con thinking apagado solo acepta esfuerzo hasta 'high'"
        )
    return ThinkingSettings(thinking={"type": "between_tools"}, effort=resolved_effort, beta=None)
