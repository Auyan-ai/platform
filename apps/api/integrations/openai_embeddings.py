"""Wrapper para embeddings de OpenAI con reintentos.

Usamos OpenAI sólo para embeddings (`text-embedding-3-small`, 1536 dims).
Para LLM siempre Claude.
"""

from __future__ import annotations

import openai
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


async def get_query_embedding(
    client: openai.AsyncOpenAI,
    text: str,
    *,
    model: str = "text-embedding-3-small",
    max_retries: int = 3,
) -> list[float]:
    """Devuelve el embedding del texto. Vector list[float] de 1536 dims para 3-small."""
    if not text.strip():
        raise ValueError("No se puede embedir texto vacío")

    last_embedding: list[float] | None = None
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(RETRYABLE_ERRORS),
        reraise=True,
    ):
        with attempt:
            resp = await client.embeddings.create(model=model, input=text)
            last_embedding = resp.data[0].embedding
    assert last_embedding is not None
    return last_embedding


def build_openai_client(api_key: str, *, timeout: float = 30.0) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(api_key=api_key, timeout=timeout)
