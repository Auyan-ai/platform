"""Utilidades para procesar submissions de conocimiento hacia la KB vectorial."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.api.integrations.openai_embeddings import get_query_embedding

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


async def embed_kb_chunks(
    openai_client: AsyncOpenAI,
    chunks: list[str],
    *,
    settings: Any,
) -> list[tuple[str, list[float]]]:
    embedded: list[tuple[str, list[float]]] = []
    for chunk in chunks:
        embedding = await get_query_embedding(
            openai_client,
            chunk,
            model=settings.embedding_model,
            max_retries=settings.llm_max_retries,
        )
        embedded.append((chunk, embedding))
    return embedded
