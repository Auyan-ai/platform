"""Tests del wrapper `get_query_embedding`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest
from apps.api.integrations.openai_embeddings import get_query_embedding


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    import asyncio

    async def _noop(seconds):  # type: ignore[no-untyped-def]
        return

    monkeypatch.setattr(asyncio, "sleep", _noop)


def _conn_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(
        request=httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    )


def _fake_embedding_response(values: list[float] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.data = [MagicMock(embedding=values if values is not None else [0.0] * 1536)]
    return resp


@pytest.mark.asyncio
async def test_happy_path_returns_embedding() -> None:
    client = MagicMock()
    client.embeddings.create = AsyncMock(
        return_value=_fake_embedding_response([0.1, 0.2, 0.3] + [0.0] * 1533)
    )

    out = await get_query_embedding(client, "hola")

    assert isinstance(out, list)
    assert len(out) == 1536
    assert out[0] == 0.1


@pytest.mark.asyncio
async def test_empty_text_raises() -> None:
    """Embedir vacío no tiene sentido — error temprano."""
    client = MagicMock()
    with pytest.raises(ValueError, match="vacío"):
        await get_query_embedding(client, "   ")


@pytest.mark.asyncio
async def test_retries_on_connection_error() -> None:
    client = MagicMock()
    resp = _fake_embedding_response()
    client.embeddings.create = AsyncMock(
        side_effect=[_conn_error(), _conn_error(), resp]
    )

    out = await get_query_embedding(client, "hola", max_retries=3)

    assert len(out) == 1536
    assert client.embeddings.create.await_count == 3


@pytest.mark.asyncio
async def test_raises_after_exhausting_retries() -> None:
    client = MagicMock()
    client.embeddings.create = AsyncMock(side_effect=_conn_error())

    with pytest.raises(openai.APIConnectionError):
        await get_query_embedding(client, "hola", max_retries=2)

    assert client.embeddings.create.await_count == 2


@pytest.mark.asyncio
async def test_passes_model_to_client() -> None:
    client = MagicMock()
    client.embeddings.create = AsyncMock(return_value=_fake_embedding_response())

    await get_query_embedding(client, "hola", model="text-embedding-3-large")

    kwargs = client.embeddings.create.await_args.kwargs
    assert kwargs["model"] == "text-embedding-3-large"
    assert kwargs["input"] == "hola"
