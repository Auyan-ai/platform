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
from apps.api.db.queries import search_knowledge_chunks
from apps.api.integrations.openai_embeddings import get_query_embedding

logger = logging.getLogger(__name__)


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
        except Exception:
            logger.exception(
                "rag_embedding_failed — degradando a retrieved_chunks=[]",
                extra={
                    "tenant_id": state.get("tenant_id"),
                    "conversation_id": state.get("conversation_id"),
                },
            )
            return {"retrieved_chunks": []}

        async with tenant_scope(tenant_id) as conn:
            chunks = await search_knowledge_chunks(
                conn,
                tenant_id,
                query_embedding=embedding,
                top_k=deps.settings.rag_top_k,
                min_similarity=deps.settings.rag_min_similarity,
            )

        return {
            "retrieved_chunks": [c.model_dump(mode="json") for c in chunks],
        }

    return _node
