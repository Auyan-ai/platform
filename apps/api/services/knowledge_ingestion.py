"""Utilidades para procesar submissions de conocimiento hacia la KB vectorial."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from apps.api.integrations.openai_embeddings import get_embeddings

if TYPE_CHECKING:
    from openai import AsyncOpenAI


def chunk_text_for_kb(
    text: str,
    *,
    max_words: int = 220,
    overlap_words: int = 35,
) -> list[str]:
    """Chunking simple por palabras, suficiente para intake curado de políticas/FAQs."""
    words = text.split()
    if not words:
        return []
    if len(words) <= max_words:
        return [" ".join(words)]

    chunks: list[str] = []
    start = 0
    step = max_words - overlap_words
    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += step
    return chunks


Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


def make_embedder(openai_client: AsyncOpenAI, *, settings: Any) -> Embedder:
    """Embedder por lotes: una lista de textos entra, sus vectores salen en el mismo orden."""

    async def embed(texts: list[str]) -> list[list[float]]:
        return await get_embeddings(
            openai_client,
            texts,
            model=settings.embedding_model,
            max_retries=settings.llm_max_retries,
        )

    return embed
