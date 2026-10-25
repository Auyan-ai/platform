"""Nodo: retrieve_knowledge.

RAG sobre `knowledge_base_chunks` del tenant. La consulta junta los últimos
mensajes del cliente (un seguimiento como "¿Y a Canarias?" no dice nada solo),
se embebe vía OpenAI y se buscan los top-K por similitud coseno con un umbral
opcional (config; 0 = sin umbral).

Si el tenant tiene la KB entera en el prompt (`knowledge.mode == "full_context"`, ver
`services.knowledge_mode`), el nodo no embebe ni busca: `reason` lee los documentos.

Si la KB está vacía o no hay chunks suficientemente similares, `retrieved_chunks`
queda vacío — el agente igual puede decidir respond/escalate sin contexto extra.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.models import KnowledgeChunk, ReasoningStatus
from apps.api.db.queries import search_knowledge_chunks
from apps.api.integrations.openai_embeddings import get_query_embedding
from apps.api.services.knowledge_mode import KnowledgeContext

logger = logging.getLogger(__name__)


def build_retrieval_query(
    history: list[dict],
    inbound_content: str,
    *,
    max_messages: int,
) -> tuple[str, int]:
    """Consulta del RAG: los últimos `max_messages` mensajes del cliente, el más nuevo al final.

    Devuelve (consulta, nº de mensajes usados). El inbound siempre entra, esté o no
    ya en el historial.
    """
    texts = [
        m["content"]
        for m in history
        if m.get("role") == "customer" and (m.get("content") or "").strip()
    ]
    if not texts or texts[-1] != inbound_content:
        texts = [t for t in texts if t != inbound_content] + [inbound_content]
    used = texts[-max(1, max_messages) :]
    return "\n".join(used), len(used)


def _emit_retrieval_event(
    deps: AgentDependencies,
    state: AgentState,
    *,
    chunks: list[KnowledgeChunk],
    query_messages: int = 0,
    error_type: str | None = None,
    knowledge: KnowledgeContext | None = None,
) -> None:
    """Un evento por turno: lo que recuperó el RAG o la KB entera en contexto. Sin contenido."""
    if not state.get("conversation_id"):
        return
    mode_stats = knowledge.summary() if knowledge else {}
    if knowledge is not None and knowledge.mode == "full_context":
        noun = "doc" if knowledge.doc_count == 1 else "docs"
        label = f"Knowledge in context ({knowledge.doc_count} {noun})"
        detail: dict[str, object] = dict(mode_stats)
        status: ReasoningStatus = "done"
    elif error_type is not None:
        label = "Knowledge retrieval failed"
        detail = {
            "chunk_count": 0,
            "query_messages": query_messages,
            "error_type": error_type,
            "chunks": [],
            **mode_stats,
        }
        status = "error"
    else:
        noun = "chunk" if len(chunks) == 1 else "chunks"
        label = f"Knowledge retrieved ({len(chunks)} {noun})"
        detail = {
            "chunk_count": len(chunks),
            "query_messages": query_messages,
            "top_similarity": round(max(c.similarity for c in chunks), 4) if chunks else None,
            "chunks": [
                {
                    "document_id": str(c.document_id),
                    "document_title": c.document_title,
                    "similarity": round(c.similarity, 4),
                }
                for c in chunks
            ],
            **mode_stats,
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
    async def _node(state: AgentState) -> dict:
        tenant_id = UUID(state["tenant_id"])
        knowledge = KnowledgeContext.from_state(state.get("knowledge"))
        mode_stats = knowledge.summary() if knowledge else {}

        if knowledge is not None and knowledge.mode == "full_context":
            _emit_retrieval_event(deps, state, chunks=[], knowledge=knowledge)
            return {"retrieved_chunks": [], "retrieval_summary": dict(mode_stats)}

        query, query_messages = build_retrieval_query(
            state.get("conversation_history") or [],
            state["inbound_message_content"],
            max_messages=deps.settings.rag_query_messages,
        )

        # OpenAI embeddings caído NO tumba el turno: el RAG es contexto opcional
        # por diseño (KB vacía ya devuelve []), así que se degrada a chunks=[]
        # en vez de propagar a guarded → handle_error → escalar todo.
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
            _emit_retrieval_event(
                deps,
                state,
                chunks=[],
                query_messages=query_messages,
                error_type=type(exc).__name__,
                knowledge=knowledge,
            )
            return {
                "retrieved_chunks": [],
                "retrieval_summary": {
                    "query_messages": query_messages,
                    "chunk_count": 0,
                    "top_similarity": None,
                    "error_type": type(exc).__name__,
                    **mode_stats,
                },
            }

        async with tenant_scope(tenant_id) as conn:
            chunks = await search_knowledge_chunks(
                conn,
                tenant_id,
                query_embedding=embedding,
                top_k=deps.settings.rag_top_k,
                min_similarity=deps.settings.rag_min_similarity,
            )

        _emit_retrieval_event(
            deps, state, chunks=chunks, query_messages=query_messages, knowledge=knowledge
        )
        return {
            "retrieved_chunks": [c.model_dump(mode="json") for c in chunks],
            "retrieval_summary": {
                "query_messages": query_messages,
                "chunk_count": len(chunks),
                "top_similarity": round(max(c.similarity for c in chunks), 4) if chunks else None,
                **mode_stats,
            },
        }

    return _node
