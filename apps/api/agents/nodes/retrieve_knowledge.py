"""Nodo: retrieve_knowledge.

RAG sobre `knowledge_base_chunks` del tenant. Embedding del inbound vía OpenAI,
luego top-K por similitud coseno con filtro de similitud mínima (config).

Si la KB está vacía o no hay chunks suficientemente similares, `retrieved_chunks`
queda vacío — el agente igual puede decidir respond/escalate sin contexto extra.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.models import KnowledgeChunk, ReasoningStatus
from apps.api.db.queries import search_knowledge_chunks
from apps.api.integrations.openai_embeddings import get_query_embedding

logger = logging.getLogger(__name__)


def _emit_retrieval_event(
    deps: AgentDependencies,
    state: AgentState,
    *,
    chunks: list[KnowledgeChunk],
    error_type: str | None = None,
) -> None:
    """Un evento por turno con lo que recuperó el RAG. Sin contenido de chunks."""
    if not state.get("conversation_id"):
        return
    if error_type is not None:
        label = "Knowledge retrieval failed"
        detail: dict[str, object] = {
            "chunk_count": 0,
            "error_type": error_type,
            "chunks": [],
        }
        status: ReasoningStatus = "error"
    else:
        noun = "chunk" if len(chunks) == 1 else "chunks"
        label = f"Knowledge retrieved ({len(chunks)} {noun})"
        detail = {
            "chunk_count": len(chunks),
            "chunks": [
                {
                    "document_id": str(c.document_id),
                    "document_title": c.document_title,
                    "similarity": round(c.similarity, 4),
                }
                for c in chunks
            ],
        }
        status = "done"
    deps.reasoning_tracker.emit(
        tenant_id=state["tenant_id"],
        conversation_id=state["conversation_id"],
        phase="supervisor",
        event_type="check",
        label=label,
        detail=detail,
        status=status,
    )


def make_retrieve_knowledge_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    @guarded(name="retrieve_knowledge")
    async def _node(state: AgentState) -> dict:
        tenant_id = UUID(state["tenant_id"])
        query = state["inbound_message_content"]

        # OpenAI embeddings caído NO tumba el turno: el RAG es contexto opcional
        # por diseño (KB vacía ya devuelve []), así que se degrada a chunks=[]
        # en vez de propagar a @guarded → handle_error → escalar todo.
        try:
            embedding = await get_query_embedding(
                deps.openai,
                query,
                model=deps.settings.embedding_model,
                max_retries=deps.settings.llm_max_retries,
            )
        except Exception as exc:
            logger.exception(
                "rag_embedding_failed — degradando a retrieved_chunks=[]",
                extra={
                    "tenant_id": state.get("tenant_id"),
                    "conversation_id": state.get("conversation_id"),
                },
            )
            _emit_retrieval_event(deps, state, chunks=[], error_type=type(exc).__name__)
            return {"retrieved_chunks": []}

        async with tenant_scope(tenant_id) as conn:
            chunks = await search_knowledge_chunks(
                conn,
                tenant_id,
                query_embedding=embedding,
                top_k=deps.settings.rag_top_k,
                min_similarity=deps.settings.rag_min_similarity,
            )

        _emit_retrieval_event(deps, state, chunks=chunks)
        return {
            "retrieved_chunks": [c.model_dump(mode="json") for c in chunks],
        }

    return _node
