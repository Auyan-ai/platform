"""Tests del nodo `retrieve_knowledge`."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.api.agents.nodes.retrieve_knowledge import make_retrieve_knowledge_node
from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    TENANT_ID,
    make_fake_tenant_scope,
    make_knowledge_chunk,
)

MODULE = "apps.api.agents.nodes.retrieve_knowledge"


def _state(content: str = "¿cuánto tarda el envío?") -> dict:
    return {
        "tenant_id": str(TENANT_ID),
        "conversation_id": str(CONVERSATION_ID),
        "end_customer_id": str(CUSTOMER_ID),
        "inbound_message_content": content,
    }


@pytest.mark.asyncio
async def test_happy_path_with_chunks(fake_deps, monkeypatch) -> None:
    chunks = [
        make_knowledge_chunk(content="Envíos a Argentina: 3-5 días.", similarity=0.92),
        make_knowledge_chunk(content="Otro fragmento.", similarity=0.75),
    ]
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_query_embedding", AsyncMock(return_value=[0.1] * 1536)
    )
    monkeypatch.setattr(
        f"{MODULE}.search_knowledge_chunks", AsyncMock(return_value=chunks)
    )
    node = make_retrieve_knowledge_node(fake_deps)

    out = await node(_state())

    assert "error" not in out
    assert len(out["retrieved_chunks"]) == 2
    assert out["retrieved_chunks"][0]["similarity"] == 0.92


@pytest.mark.asyncio
async def test_empty_knowledge_base(fake_deps, monkeypatch) -> None:
    """KB vacía o sin chunks relevantes → retrieved_chunks=[] (no es error)."""
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_query_embedding", AsyncMock(return_value=[0.0] * 1536)
    )
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", AsyncMock(return_value=[]))
    node = make_retrieve_knowledge_node(fake_deps)

    out = await node(_state())

    assert out["retrieved_chunks"] == []
    assert "error" not in out


@pytest.mark.asyncio
async def test_embeds_the_inbound_message(fake_deps, monkeypatch) -> None:
    """El embedding se calcula sobre el mensaje entrante, no sobre el historial."""
    embed_mock = AsyncMock(return_value=[0.0] * 1536)
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_query_embedding", embed_mock)
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", AsyncMock(return_value=[]))
    node = make_retrieve_knowledge_node(fake_deps)

    await node(_state(content="texto específico que se debe embedir"))

    call = embed_mock.await_args
    args_and_kwargs = list(call.args) + list(call.kwargs.values())
    assert "texto específico que se debe embedir" in args_and_kwargs


@pytest.mark.asyncio
async def test_uses_rag_settings(fake_deps, monkeypatch) -> None:
    """top_k y min_similarity vienen de settings."""
    fake_deps.settings.rag_top_k = 3
    fake_deps.settings.rag_min_similarity = 0.8
    search_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_query_embedding", AsyncMock(return_value=[0.0] * 1536)
    )
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", search_mock)
    node = make_retrieve_knowledge_node(fake_deps)

    await node(_state())

    kwargs = search_mock.await_args.kwargs
    assert kwargs["top_k"] == 3
    assert kwargs["min_similarity"] == 0.8
