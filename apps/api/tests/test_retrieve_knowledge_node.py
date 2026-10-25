"""Tests del nodo `retrieve_knowledge`."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apps.api.agents.nodes.retrieve_knowledge import make_retrieve_knowledge_node

from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    DOCUMENT_ID,
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
    monkeypatch.setattr(f"{MODULE}.get_query_embedding", AsyncMock(return_value=[0.1] * 1536))
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", AsyncMock(return_value=chunks))
    node = make_retrieve_knowledge_node(fake_deps)

    out = await node(_state())

    assert "error" not in out
    assert len(out["retrieved_chunks"]) == 2
    assert out["retrieved_chunks"][0]["similarity"] == 0.92
    [event] = fake_deps.reasoning_tracker.events
    assert event["phase"] == "supervisor"
    assert event["event_type"] == "check"
    assert event["status"] == "done"
    assert event["label"] == "Knowledge retrieved (2 chunks)"
    assert event["detail"] == {
        "chunk_count": 2,
        "query_messages": 1,
        "top_similarity": 0.92,
        "chunks": [
            {
                "document_id": str(DOCUMENT_ID),
                "document_title": "FAQ",
                "similarity": 0.92,
            },
            {
                "document_id": str(DOCUMENT_ID),
                "document_title": "FAQ",
                "similarity": 0.75,
            },
        ],
    }
    assert "Envíos a Argentina" not in str(event)


@pytest.mark.asyncio
async def test_empty_knowledge_base(fake_deps, monkeypatch) -> None:
    """KB vacía o sin chunks relevantes → retrieved_chunks=[] (no es error)."""
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_query_embedding", AsyncMock(return_value=[0.0] * 1536))
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", AsyncMock(return_value=[]))
    node = make_retrieve_knowledge_node(fake_deps)

    out = await node(_state())

    assert out["retrieved_chunks"] == []
    assert "error" not in out
    [event] = fake_deps.reasoning_tracker.events
    assert event["label"] == "Knowledge retrieved (0 chunks)"
    assert event["status"] == "done"
    assert event["detail"] == {
        "chunk_count": 0,
        "query_messages": 1,
        "top_similarity": None,
        "chunks": [],
    }


@pytest.mark.asyncio
async def test_embedding_failure_degrades_to_no_chunks(fake_deps, monkeypatch) -> None:
    """Auditoría sesión 67 (d): OpenAI embeddings caído NO debe tumbar el turno
    (antes: excepción → @guarded → handle_error → escalar TODO). El RAG es
    contexto opcional: se degrada a chunks=[] y el agente sigue."""
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{MODULE}.get_query_embedding",
        AsyncMock(side_effect=RuntimeError("openai_down")),
    )
    search_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", search_mock)
    node = make_retrieve_knowledge_node(fake_deps)

    out = await node(_state())

    assert out["retrieved_chunks"] == []
    assert "error" not in out
    # Sin embedding no hay búsqueda que hacer.
    search_mock.assert_not_awaited()
    [event] = fake_deps.reasoning_tracker.events
    assert event["label"] == "Knowledge retrieval failed"
    assert event["status"] == "error"
    assert event["phase"] == "supervisor"
    assert event["detail"] == {
        "chunk_count": 0,
        "query_messages": 1,
        "error_type": "RuntimeError",
        "chunks": [],
    }
    assert "openai_down" not in str(event)


@pytest.mark.asyncio
async def test_search_failure_still_raises_to_guard(fake_deps, monkeypatch) -> None:
    """Un fallo de la búsqueda en Postgres NO se degrada: si la DB está caída,
    el resto del turno también va a fallar — mejor fail-fast vía guarded."""
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_query_embedding", AsyncMock(return_value=[0.0] * 1536))
    monkeypatch.setattr(
        f"{MODULE}.search_knowledge_chunks",
        AsyncMock(side_effect=RuntimeError("db_down")),
    )
    node = make_retrieve_knowledge_node(fake_deps)

    with pytest.raises(RuntimeError, match="db_down"):
        await node(_state())


@pytest.mark.asyncio
async def test_embeds_the_inbound_message(fake_deps, monkeypatch) -> None:
    """Sin historial, la consulta es el mensaje entrante."""
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
    monkeypatch.setattr(f"{MODULE}.get_query_embedding", AsyncMock(return_value=[0.0] * 1536))
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", search_mock)
    node = make_retrieve_knowledge_node(fake_deps)

    await node(_state())

    kwargs = search_mock.await_args.kwargs
    assert kwargs["top_k"] == 3
    assert kwargs["min_similarity"] == 0.8


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


@pytest.mark.asyncio
async def test_follow_up_query_includes_previous_customer_message(fake_deps, monkeypatch) -> None:
    """'¿Y a Canarias?' solo no dice nada: la consulta lleva también el mensaje anterior."""
    embed_mock = AsyncMock(return_value=[0.0] * 1536)
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_query_embedding", embed_mock)
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", AsyncMock(return_value=[]))
    node = make_retrieve_knowledge_node(fake_deps)
    state = _state(content="¿Y a Canarias?")
    state["conversation_history"] = [
        _msg("customer", "¿El envío es gratis?"),
        _msg("agent_ai", "Sí, a partir de 110 euros."),
        _msg("customer", "¿Y a Canarias?"),
    ]

    await node(state)

    query = embed_mock.await_args.args[1]
    assert query == "¿El envío es gratis?\n¿Y a Canarias?"
    [event] = fake_deps.reasoning_tracker.events
    assert event["detail"]["query_messages"] == 2


@pytest.mark.asyncio
async def test_query_keeps_only_last_n_customer_messages(fake_deps, monkeypatch) -> None:
    fake_deps.settings.rag_query_messages = 2
    embed_mock = AsyncMock(return_value=[0.0] * 1536)
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_query_embedding", embed_mock)
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", AsyncMock(return_value=[]))
    node = make_retrieve_knowledge_node(fake_deps)
    state = _state(content="tres")
    state["conversation_history"] = [
        _msg("customer", "uno"),
        _msg("customer", "dos"),
        _msg("customer", "tres"),
    ]

    await node(state)

    assert embed_mock.await_args.args[1] == "dos\ntres"


@pytest.mark.asyncio
async def test_inbound_missing_from_history_is_appended_last(fake_deps, monkeypatch) -> None:
    embed_mock = AsyncMock(return_value=[0.0] * 1536)
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_query_embedding", embed_mock)
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", AsyncMock(return_value=[]))
    node = make_retrieve_knowledge_node(fake_deps)
    state = _state(content="nuevo")
    state["conversation_history"] = [_msg("customer", "viejo")]

    await node(state)

    assert embed_mock.await_args.args[1] == "viejo\nnuevo"


@pytest.mark.asyncio
async def test_low_similarity_correct_chunk_is_returned_by_default(fake_deps, monkeypatch) -> None:
    """#410: con el umbral por defecto (0) un fragmento correcto a 0,54 no se descarta."""
    low = make_knowledge_chunk(content="Envío gratis desde 110 €.", similarity=0.54)

    async def _search(conn, tenant_id, *, query_embedding, top_k, min_similarity):
        return [low] if low.similarity >= min_similarity else []

    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_query_embedding", AsyncMock(return_value=[0.0] * 1536))
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", _search)
    node = make_retrieve_knowledge_node(fake_deps)

    out = await node(_state(content="¿El envío es gratis?"))

    assert [c["content"] for c in out["retrieved_chunks"]] == ["Envío gratis desde 110 €."]
    assert out["retrieval_summary"] == {
        "query_messages": 1,
        "chunk_count": 1,
        "top_similarity": 0.54,
    }


def test_settings_defaults_have_no_similarity_floor() -> None:
    from apps.api.core.config import Settings

    fields = Settings.model_fields
    assert fields["rag_min_similarity"].default == 0.0
    assert fields["rag_top_k"].default == 20
    assert fields["rag_query_messages"].default == 3


def _knowledge(mode: str, tokens: int = 1200, docs: int = 3) -> dict:
    documents = (
        [{"title": "Envíos", "source": None, "content": "Gratis desde 110 €."}]
        if mode == "full_context"
        else []
    )
    return {"mode": mode, "total_tokens": tokens, "doc_count": docs, "documents": documents}


@pytest.mark.asyncio
async def test_full_context_turn_never_embeds_or_searches(fake_deps, monkeypatch) -> None:
    embed_mock = AsyncMock(return_value=[0.0] * 1536)
    search_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_query_embedding", embed_mock)
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", search_mock)
    node = make_retrieve_knowledge_node(fake_deps)
    state = _state()
    state["knowledge"] = _knowledge("full_context")

    out = await node(state)

    embed_mock.assert_not_awaited()
    search_mock.assert_not_awaited()
    stats = {"mode": "full_context", "total_tokens": 1200, "doc_count": 3}
    assert out["retrieved_chunks"] == []
    assert out["retrieval_summary"] == stats
    [event] = fake_deps.reasoning_tracker.events
    assert event["label"] == "Knowledge in context (3 docs)"
    assert event["detail"] == stats


@pytest.mark.asyncio
async def test_retrieval_tenant_is_unchanged_and_records_mode(fake_deps, monkeypatch) -> None:
    chunks = [make_knowledge_chunk(content="Envíos.", similarity=0.7)]
    embed_mock = AsyncMock(return_value=[0.1] * 1536)
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_query_embedding", embed_mock)
    monkeypatch.setattr(f"{MODULE}.search_knowledge_chunks", AsyncMock(return_value=chunks))
    node = make_retrieve_knowledge_node(fake_deps)
    state = _state()
    state["knowledge"] = _knowledge("retrieval", tokens=80_000, docs=40)

    out = await node(state)

    embed_mock.assert_awaited_once()
    assert len(out["retrieved_chunks"]) == 1
    assert out["retrieval_summary"] == {
        "query_messages": 1,
        "chunk_count": 1,
        "top_similarity": 0.7,
        "mode": "retrieval",
        "total_tokens": 80_000,
        "doc_count": 40,
    }
    [event] = fake_deps.reasoning_tracker.events
    assert event["label"] == "Knowledge retrieved (1 chunk)"
    assert event["detail"]["mode"] == "retrieval"
    assert event["detail"]["total_tokens"] == 80_000
    assert event["detail"]["doc_count"] == 40
