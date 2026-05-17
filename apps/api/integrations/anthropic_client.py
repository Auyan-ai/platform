"""Wrapper para llamadas a Claude con tools y reintentos.

Reintentos: backoff exponencial sobre errores transitorios
(`APIConnectionError`, `APITimeoutError`, `RateLimitError`, `InternalServerError`).
Los errores 4xx no-rate-limited NO se reintentan — son problemas nuestros.

Soporta múltiples tools en una sola llamada (loop ReAct). El caller decide
`tool_choice`: `{"type":"any"}` para forzar alguna tool, `{"type":"tool","name":...}`
para forzar una específica, `None` para dejarlo libre.
"""

from __future__ import annotations

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

RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


async def call_claude_with_tools(
    *,
    client: anthropic.AsyncAnthropic,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any] | None = None,
    max_tokens: int = 1024,
    max_retries: int = 3,
    timeout_seconds: int = 30,
) -> Message:
    """Llama a Claude con una lista de tools, con reintentos en errores transitorios.

    Args:
        tools: lista de tool definitions ({"name", "description", "input_schema"}).
        tool_choice: si None, Claude elige libremente entre tools o texto.
            `{"type": "any"}` fuerza el uso de alguna tool.
            `{"type": "tool", "name": "..."}` fuerza una tool específica.

    Raises:
        anthropic.APIError o subclase si después de los reintentos sigue fallando.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "tools": tools,
        "timeout": timeout_seconds,
    }
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice

    last_response: Message | None = None
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(RETRYABLE_ERRORS),
        reraise=True,
    ):
        with attempt:
            last_response = await client.messages.create(**kwargs)
    assert last_response is not None
    return last_response


def build_anthropic_client(api_key: str, *, timeout: float = 60.0) -> anthropic.AsyncAnthropic:
    """Construye el cliente async. El timeout aquí es el del transport HTTP global."""
    return anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)
