"""Wrapper para llamadas a Claude con tools y reintentos.

Reintentos: backoff exponencial sobre errores transitorios
(`APIConnectionError`, `APITimeoutError`, `RateLimitError`, `InternalServerError`).
Los errores 4xx no-rate-limited NO se reintentan — son problemas nuestros.

Soporta múltiples tools en una sola llamada (loop ReAct). El caller decide
`tool_choice`: `{"type":"any"}` para forzar alguna tool, `{"type":"tool","name":...}`
para forzar una específica, `None` para dejarlo libre.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import anthropic
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

if TYPE_CHECKING:
    from anthropic.types import Message

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


def _usage_int(usage: Any, attr: str) -> int:
    """Lee un contador de `usage` como int. Si el atributo falta o no es int
    (p.ej. None cuando no hubo caching), devuelve 0 — así el logging de
    instrumentación nunca rompe ante respuestas sin breakdown de cache."""
    val = getattr(usage, attr, 0)
    return val if isinstance(val, int) else 0


async def call_claude_with_tools(
    *,
    client: anthropic.AsyncAnthropic,
    model: str,
    system: str | list[dict[str, Any]],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any] | None = None,
    max_tokens: int = 1024,
    max_retries: int = 3,
    timeout_seconds: int = 30,
    cache: bool = False,
    trace_label: str | None = None,
) -> Message:
    """Llama a Claude con una lista de tools, con reintentos en errores transitorios.

    Args:
        tools: lista de tool definitions ({"name", "description", "input_schema"}).
        tool_choice: si None, Claude elige libremente entre tools o texto.
            `{"type": "any"}` fuerza el uso de alguna tool.
            `{"type": "tool", "name": "..."}` fuerza una tool específica.
        cache: si True activa prompt caching (cache_control ephemeral) sobre el
            prefijo tools + system. Cachea las definiciones de tools (marca la última)
            y, si `system` llega como string, lo envuelve en un bloque cacheado. Si
            `system` llega ya como lista de bloques, el caller controla los breakpoints
            (debe marcar el bloque ESTABLE con cache_control). Pega solo si el prefijo
            es idéntico entre llamadas (TTL ~5 min).
        trace_label: si se pasa, loguea a INFO una línea por llamada con duración
            real + breakdown de tokens (input/cache_write/cache_read/output). Sirve
            para medir el efecto del prompt caching: el primer turno escribe cache
            (cache_w>0), los siguientes dentro del TTL lo leen (cache_r>0). Sin
            label no loguea — así solo se instrumentan los callers que lo piden.

    Raises:
        anthropic.APIError o subclase si después de los reintentos sigue fallando.
    """
    system_param: Any = system
    tools_param = tools
    if cache:
        if tools_param:
            # cache_control en la última tool cachea TODO el bloque de tools.
            # Copia superficial: no mutamos el input del caller.
            tools_param = [
                *tools_param[:-1],
                {**tools_param[-1], "cache_control": {"type": "ephemeral"}},
            ]
        if isinstance(system_param, str):
            system_param = [
                {
                    "type": "text",
                    "text": system_param,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_param,
        "messages": messages,
        "tools": tools_param,
        "timeout": timeout_seconds,
    }
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice

    last_response: Message | None = None
    start = time.monotonic()
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(RETRYABLE_ERRORS),
        reraise=True,
    ):
        with attempt:
            last_response = await client.messages.create(**kwargs)
    assert last_response is not None

    if trace_label is not None:
        # Instrumentación de latencia/cache: una línea por llamada al LLM.
        # dur_ms cubre el happy path (sin reintentos = la llamada en sí); si
        # hubo reintentos incluye los backoffs, lo cual es raro y se nota.
        usage = last_response.usage
        logger.info(
            "llm_call label=%s model=%s dur_ms=%d in=%d cache_w=%d cache_r=%d out=%d",
            trace_label,
            model,
            int((time.monotonic() - start) * 1000),
            _usage_int(usage, "input_tokens"),
            _usage_int(usage, "cache_creation_input_tokens"),
            _usage_int(usage, "cache_read_input_tokens"),
            _usage_int(usage, "output_tokens"),
        )
    return last_response


def build_anthropic_client(api_key: str, *, timeout: float = 60.0) -> anthropic.AsyncAnthropic:
    """Construye el cliente async. El timeout aquí es el del transport HTTP global."""
    return anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)
