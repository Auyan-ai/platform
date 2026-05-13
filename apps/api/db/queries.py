"""Queries de Supabase usadas por el grafo y los routers.

Reglas:
- Cada función recibe `conn: asyncpg.Connection` ya en su transacción (vía `tenant_scope`).
- `tenant_id` es siempre parámetro explícito — incluso cuando el GUC ya lo conoce —
  para que un WHERE accidentalmente mal escrito sea grep-able.
- Nunca concatenamos SQL: todo va por bind params $1, $2, ...
- Para columnas con enum custom de Postgres se castea explícito (`$N::enum_name`)
  para evitar ambigüedad con strings al hacer INSERT/UPDATE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.db.models import (
    ChannelType,
    Conversation,
    ConversationStatus,
    EndCustomer,
    Escalation,
    KnowledgeChunk,
    Message,
    MessageDirection,
    MessageRole,
    Tenant,
    TenantConfiguration,
)

if TYPE_CHECKING:
    import asyncpg


# ============================================================
# Tenants & configuración
# ============================================================


async def get_tenant_by_id(conn: asyncpg.Connection, tenant_id: UUID) -> Tenant | None:
    """Bootstrap: traer tenant por id. Útil para validar existencia."""
    row = await conn.fetchrow(
        """
        SELECT id, slug, name, status
          FROM tenants
         WHERE id = $1 AND deleted_at IS NULL
        """,
        tenant_id,
    )
    return None if row is None else Tenant(**dict(row))


async def get_tenant_by_slug(conn: asyncpg.Connection, slug: str) -> Tenant | None:
    """Bootstrap: traer tenant por slug. Se ejecuta SIN tenant scope."""
    row = await conn.fetchrow(
        """
        SELECT id, slug, name, status
          FROM tenants
         WHERE slug = $1 AND deleted_at IS NULL
        """,
        slug,
    )
    return None if row is None else Tenant(**dict(row))


async def get_tenant_configuration(
    conn: asyncpg.Connection, tenant_id: UUID
) -> TenantConfiguration | None:
    row = await conn.fetchrow(
        """
        SELECT tenant_id, agent_model, escalation_threshold,
               active_channels, branding, extra
          FROM tenant_configurations
         WHERE tenant_id = $1
        """,
        tenant_id,
    )
    if row is None:
        return None
    data = dict(row)
    # escalation_threshold es NUMERIC(3,2) → asyncpg lo entrega como Decimal.
    data["escalation_threshold"] = float(data["escalation_threshold"])
    return TenantConfiguration(**data)


async def get_active_system_prompt(
    conn: asyncpg.Connection, tenant_id: UUID, name: str = "system"
) -> str | None:
    """Trae el `content` del prompt activo (única fila con is_active=true por (tenant, name))."""
    return await conn.fetchval(
        """
        SELECT content
          FROM tenant_prompts
         WHERE tenant_id = $1 AND name = $2
           AND is_active = true AND deleted_at IS NULL
         LIMIT 1
        """,
        tenant_id,
        name,
    )


# ============================================================
# End customers
# ============================================================


async def get_end_customer(
    conn: asyncpg.Connection, tenant_id: UUID, customer_id: UUID
) -> EndCustomer | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, email, phone, external_id, full_name, metadata
          FROM end_customers
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
        """,
        tenant_id,
        customer_id,
    )
    return None if row is None else EndCustomer(**dict(row))


async def find_end_customer_by_email(
    conn: asyncpg.Connection, tenant_id: UUID, email: str
) -> EndCustomer | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, email, phone, external_id, full_name, metadata
          FROM end_customers
         WHERE tenant_id = $1 AND lower(email) = lower($2) AND deleted_at IS NULL
         LIMIT 1
        """,
        tenant_id,
        email,
    )
    return None if row is None else EndCustomer(**dict(row))


async def create_end_customer(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    email: str | None = None,
    phone: str | None = None,
    external_id: str | None = None,
    full_name: str | None = None,
    metadata: dict | None = None,
) -> EndCustomer:
    row = await conn.fetchrow(
        """
        INSERT INTO end_customers (
            tenant_id, email, phone, external_id, full_name, metadata
        ) VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, tenant_id, email, phone, external_id, full_name, metadata
        """,
        tenant_id,
        email,
        phone,
        external_id,
        full_name,
        metadata or {},
    )
    assert row is not None
    return EndCustomer(**dict(row))


# ============================================================
# Conversations
# ============================================================


async def get_conversation(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID
) -> Conversation | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, end_customer_id, channel, external_id,
               subject, status, assigned_user_id, last_message_at
          FROM conversations
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
        """,
        tenant_id,
        conversation_id,
    )
    return None if row is None else Conversation(**dict(row))


async def find_conversation_by_external(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    channel: ChannelType,
    external_id: str,
) -> Conversation | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, end_customer_id, channel, external_id,
               subject, status, assigned_user_id, last_message_at
          FROM conversations
         WHERE tenant_id = $1 AND channel = $2::channel_type AND external_id = $3
           AND deleted_at IS NULL
         LIMIT 1
        """,
        tenant_id,
        channel,
        external_id,
    )
    return None if row is None else Conversation(**dict(row))


async def create_conversation(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    end_customer_id: UUID,
    channel: ChannelType,
    external_id: str | None = None,
    subject: str | None = None,
) -> Conversation:
    row = await conn.fetchrow(
        """
        INSERT INTO conversations (
            tenant_id, end_customer_id, channel, external_id, subject, status
        ) VALUES ($1, $2, $3::channel_type, $4, $5, 'open'::conversation_status)
        RETURNING id, tenant_id, end_customer_id, channel, external_id,
                  subject, status, assigned_user_id, last_message_at
        """,
        tenant_id,
        end_customer_id,
        channel,
        external_id,
        subject,
    )
    assert row is not None
    return Conversation(**dict(row))


async def update_conversation_last_message(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID
) -> None:
    await conn.execute(
        """
        UPDATE conversations
           SET last_message_at = now()
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
        """,
        tenant_id,
        conversation_id,
    )


async def update_conversation_status(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
    status: ConversationStatus,
) -> None:
    await conn.execute(
        """
        UPDATE conversations
           SET status = $3::conversation_status
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
        """,
        tenant_id,
        conversation_id,
        status,
    )


# ============================================================
# Messages
# ============================================================


async def get_recent_messages(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
    limit: int = 20,
) -> list[Message]:
    """Últimos `limit` mensajes (excluye 'system' y soft-deleted), en orden cronológico ASC."""
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, conversation_id, role, direction,
               author_user_id, content, attachments, metadata, created_at
          FROM messages
         WHERE tenant_id = $1 AND conversation_id = $2 AND deleted_at IS NULL
           AND role IN ('customer', 'agent_ai', 'agent_human')
         ORDER BY created_at DESC
         LIMIT $3
        """,
        tenant_id,
        conversation_id,
        limit,
    )
    return [Message(**dict(r)) for r in reversed(rows)]


async def insert_message(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    role: MessageRole,
    direction: MessageDirection,
    content: str,
    author_user_id: UUID | None = None,
    attachments: list[dict] | None = None,
    metadata: dict | None = None,
) -> Message:
    row = await conn.fetchrow(
        """
        INSERT INTO messages (
            tenant_id, conversation_id, role, direction,
            author_user_id, content, attachments, metadata
        ) VALUES (
            $1, $2, $3::message_role, $4::message_direction,
            $5, $6, $7, $8
        )
        RETURNING id, tenant_id, conversation_id, role, direction,
                  author_user_id, content, attachments, metadata, created_at
        """,
        tenant_id,
        conversation_id,
        role,
        direction,
        author_user_id,
        content,
        attachments or [],
        metadata or {},
    )
    assert row is not None
    return Message(**dict(row))


# ============================================================
# Escalations
# ============================================================


async def insert_escalation(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    reason: str,
    triggered_by_message_id: UUID | None = None,
    metadata: dict | None = None,
) -> Escalation:
    """Crea una escalación en estado 'pending'. La razón es obligatoria por regla de CLAUDE.md."""
    row = await conn.fetchrow(
        """
        INSERT INTO escalations (
            tenant_id, conversation_id, reason,
            triggered_by_message_id, status, metadata
        ) VALUES (
            $1, $2, $3, $4, 'pending'::escalation_status, $5
        )
        RETURNING id, tenant_id, conversation_id, reason,
                  triggered_by_message_id, status, assigned_user_id, metadata
        """,
        tenant_id,
        conversation_id,
        reason,
        triggered_by_message_id,
        metadata or {},
    )
    assert row is not None
    return Escalation(**dict(row))


# ============================================================
# Knowledge base (RAG)
# ============================================================


async def search_knowledge_chunks(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    query_embedding: list[float],
    top_k: int = 5,
    min_similarity: float = 0.6,
) -> list[KnowledgeChunk]:
    """Top-K chunks por similitud coseno con filtro por similitud mínima.

    Estrategia: ORDER BY + LIMIT en una subquery para que el índice HNSW se aplique,
    después filtra por similitud mínima fuera del index scan. Para K pequeños y
    `min_similarity` razonable, sobre-pedir no impacta.
    """
    rows = await conn.fetch(
        """
        SELECT id, document_id, document_title, content, similarity
          FROM (
            SELECT c.id, c.document_id, c.content,
                   d.title AS document_title,
                   1 - (c.embedding <=> $2::vector) AS similarity
              FROM knowledge_base_chunks c
              JOIN knowledge_base_documents d
                ON d.id = c.document_id AND d.tenant_id = c.tenant_id
             WHERE c.tenant_id = $1
               AND d.deleted_at IS NULL
             ORDER BY c.embedding <=> $2::vector
             LIMIT $3
          ) sub
         WHERE sub.similarity >= $4
         ORDER BY sub.similarity DESC
        """,
        tenant_id,
        query_embedding,
        top_k,
        min_similarity,
    )
    return [KnowledgeChunk(**dict(r)) for r in rows]
