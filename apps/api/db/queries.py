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

import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from apps.api.core.errors import ConflictError
from apps.api.db.models import (
    AgentReasoningEvent,
    AopVersion,
    AopWithContent,
    AopWorkspace,
    BillingSubscription,
    BillingTier,
    ChannelType,
    Conversation,
    ConversationJudgment,
    ConversationStatus,
    EndCustomer,
    Escalation,
    EscalationStatus,
    IdempotencyRecord,
    ImprovementProposal,
    IntegrationKind,
    IntentClassifierRun,
    InternalRole,
    InternalUser,
    KnowledgeChunk,
    Message,
    MessageDirection,
    MessageRole,
    OnboardingChecklist,
    OutboundEmailJob,
    OutboundEmailJobStatus,
    OutboundEmailTemplate,
    PendingApproval,
    ReasoningEventType,
    ReasoningPhase,
    ReasoningStatus,
    ResolutionEvent,
    RolePermission,
    SimulationRun,
    SimulationRunStatus,
    SimulationScenario,
    SkillAuditLog,
    SlowAgentRun,
    Tenant,
    TenantAssignment,
    TenantConfiguration,
    TenantFacts,
    TenantIntegration,
    TenantKnowledgeSourceType,
    TenantKnowledgeSubmission,
    TenantKnowledgeSubmissionStatus,
    TenantOnboarding,
    TenantPlaybook,
    TenantToolPermission,
    TenantUsageDaily,
    TerminationReason,
    UserProfile,
    UserRole,
    WeeklyReport,
    WeeklyReportStatus,
)

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


# ============================================================
# Users (lookup para auth — SIN tenant_scope; corre con bootstrap_connection)
# ============================================================


async def get_user_for_auth(
    conn: asyncpg.Connection, user_id: UUID
) -> tuple[UUID | None, UserRole, str] | None:
    """Devuelve (tenant_id, role, email) del usuario o None si no existe / soft-deleted.

    Sin tenant_scope a propósito: la auth tiene que correr antes de saber el tenant.
    `tenant_id` puede ser None solo cuando role = 'super_admin'.
    """
    row = await conn.fetchrow(
        """
        SELECT tenant_id, role, email
          FROM users
         WHERE id = $1 AND deleted_at IS NULL
        """,
        user_id,
    )
    if row is None:
        return None
    return row["tenant_id"], row["role"], row["email"]


# ============================================================
# Tenants & configuración
# ============================================================


async def get_tenant_by_id(conn: asyncpg.Connection, tenant_id: UUID) -> Tenant | None:
    """Bootstrap: traer tenant por id. Útil para validar existencia."""
    row = await conn.fetchrow(
        """
        SELECT id, slug, name, status, agent_lifecycle_state, plan_tier
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
        SELECT id, slug, name, status, agent_lifecycle_state, plan_tier
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
               subject, status, assigned_user_id, last_message_at, nudged_at, created_at
          FROM conversations
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
        """,
        tenant_id,
        conversation_id,
    )
    return None if row is None else Conversation(**dict(row))


async def find_conversation_by_id(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: str,
) -> Conversation | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, end_customer_id, channel, external_id,
               subject, status, assigned_user_id, last_message_at, nudged_at, created_at
          FROM conversations
         WHERE tenant_id = $1 AND id = $2::uuid
           AND deleted_at IS NULL
         LIMIT 1
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
               subject, status, assigned_user_id, last_message_at, nudged_at,
               resolved_at, created_at
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
    is_simulation: bool = False,
) -> Conversation:
    row = await conn.fetchrow(
        """
        INSERT INTO conversations (
            tenant_id, end_customer_id, channel, external_id, subject, status,
            is_simulation
        ) VALUES ($1, $2, $3::channel_type, $4, $5, 'open'::conversation_status, $6)
        RETURNING id, tenant_id, end_customer_id, channel, external_id,
                  subject, status, assigned_user_id, last_message_at, nudged_at,
                  is_simulation, created_at
        """,
        tenant_id,
        end_customer_id,
        channel,
        external_id,
        subject,
        is_simulation,
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


async def count_inbound_messages(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> int:
    """Retorna el número de mensajes inbound (role='customer') en la conversación."""
    row = await conn.fetchrow(
        """
        SELECT COUNT(*) AS cnt
          FROM messages
         WHERE tenant_id = $1
           AND conversation_id = $2
           AND role = 'customer'
           AND deleted_at IS NULL
        """,
        tenant_id,
        conversation_id,
    )
    return int(row["cnt"]) if row else 0


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


async def mark_conversation_resolved(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID
) -> bool:
    """Marca la conversación como resuelta por el agente (status + resolved_at).

    Solo aplica si está activa (open/pending): no re-resuelve una ya cerrada,
    escalada o abandonada. Retorna True si actualizó una fila.
    Invariante: resolved_at IS NOT NULL <=> status='resolved'.
    """
    result = await conn.execute(
        """
        UPDATE conversations
           SET status      = 'resolved'::conversation_status,
               resolved_at = now(),
               updated_at  = now()
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
           AND status IN ('open', 'pending')
        """,
        tenant_id,
        conversation_id,
    )
    return int(result.split()[-1]) > 0


async def reopen_conversation(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID
) -> bool:
    """Reabre una conversación resuelta cuando el cliente vuelve a escribir.

    Limpia resolved_at (mantiene el invariante) y vuelve a 'open'. Retorna True
    si reabrió una fila (estaba en 'resolved').
    """
    result = await conn.execute(
        """
        UPDATE conversations
           SET status      = 'open'::conversation_status,
               resolved_at = NULL,
               updated_at  = now()
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
           AND status = 'resolved'
        """,
        tenant_id,
        conversation_id,
    )
    return int(result.split()[-1]) > 0


async def soft_delete_conversation(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID
) -> None:
    """Soft-delete de una conversación. Usado para limpiar conversaciones de simulación."""
    await conn.execute(
        """
        UPDATE conversations
           SET deleted_at = now()
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
        """,
        tenant_id,
        conversation_id,
    )


async def list_conversations(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    status: ConversationStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Conversation]:
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, end_customer_id, channel, external_id,
               subject, status, assigned_user_id, last_message_at, nudged_at,
               is_simulation, created_at
          FROM conversations
         WHERE tenant_id = $1 AND deleted_at IS NULL
           AND is_simulation = FALSE
           AND ($2::conversation_status IS NULL OR status = $2::conversation_status)
         ORDER BY created_at DESC
         LIMIT $3 OFFSET $4
        """,
        tenant_id,
        status,
        limit,
        offset,
    )
    return [Conversation(**dict(r)) for r in rows]


# ============================================================
# Messages
# ============================================================


async def get_messages_for_conversation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
    *,
    include_system: bool = False,
) -> list[Message]:
    """Todos los mensajes de una conversación en orden cronológico ASC.

    `include_system=False` excluye mensajes de role='system' (prompts internos).
    """
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, conversation_id, role, direction,
               author_user_id, content, attachments, metadata, created_at
          FROM messages
         WHERE tenant_id = $1 AND conversation_id = $2 AND deleted_at IS NULL
           AND ($3 = true OR role != 'system')
         ORDER BY created_at ASC
        """,
        tenant_id,
        conversation_id,
        include_system,
    )
    return [Message(**dict(r)) for r in rows]


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
                  triggered_by_message_id, status, assigned_user_id, metadata, created_at
        """,
        tenant_id,
        conversation_id,
        reason,
        triggered_by_message_id,
        metadata or {},
    )
    assert row is not None
    return Escalation(**dict(row))


async def get_open_escalation_for_conversation(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID
) -> Escalation | None:
    """Devuelve la escalación activa (pending/claimed) de una conversación, si existe."""
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, conversation_id, reason,
               triggered_by_message_id, status, assigned_user_id, metadata, created_at
          FROM escalations
         WHERE tenant_id = $1
           AND conversation_id = $2
           AND status IN ('pending', 'claimed')
           AND deleted_at IS NULL
         LIMIT 1
        """,
        tenant_id,
        conversation_id,
    )
    return None if row is None else Escalation(**dict(row))


async def get_escalation(
    conn: asyncpg.Connection, tenant_id: UUID, escalation_id: UUID
) -> Escalation | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, conversation_id, reason,
               triggered_by_message_id, status, assigned_user_id, metadata, created_at
          FROM escalations
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
        """,
        tenant_id,
        escalation_id,
    )
    return None if row is None else Escalation(**dict(row))


async def list_escalations(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    status: EscalationStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Escalation]:
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, conversation_id, reason,
               triggered_by_message_id, status, assigned_user_id, metadata, created_at
          FROM escalations
         WHERE tenant_id = $1 AND deleted_at IS NULL
           AND ($2::escalation_status IS NULL OR status = $2::escalation_status)
         ORDER BY created_at DESC
         LIMIT $3 OFFSET $4
        """,
        tenant_id,
        status,
        limit,
        offset,
    )
    return [Escalation(**dict(r)) for r in rows]


async def claim_escalation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    escalation_id: UUID,
    agent_user_id: UUID,
) -> Escalation | None:
    """Marca la escalación como 'claimed' y asigna al agente.

    Devuelve None si la escalación no estaba en estado 'pending' (CAS pattern).
    """
    row = await conn.fetchrow(
        """
        UPDATE escalations
           SET status = 'claimed'::escalation_status,
               assigned_user_id = $3
         WHERE tenant_id = $1 AND id = $2
           AND status = 'pending'::escalation_status
           AND deleted_at IS NULL
        RETURNING id, tenant_id, conversation_id, reason,
                  triggered_by_message_id, status, assigned_user_id, metadata, created_at
        """,
        tenant_id,
        escalation_id,
        agent_user_id,
    )
    return None if row is None else Escalation(**dict(row))


async def resolve_escalation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    escalation_id: UUID,
) -> Escalation | None:
    """Marca la escalación como 'resolved'.

    Devuelve None si no estaba en estado 'claimed' (CAS pattern).
    """
    row = await conn.fetchrow(
        """
        UPDATE escalations
           SET status = 'resolved'::escalation_status
         WHERE tenant_id = $1 AND id = $2
           AND status = 'claimed'::escalation_status
           AND deleted_at IS NULL
        RETURNING id, tenant_id, conversation_id, reason,
                  triggered_by_message_id, status, assigned_user_id, metadata, created_at
        """,
        tenant_id,
        escalation_id,
    )
    return None if row is None else Escalation(**dict(row))


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


async def create_knowledge_document_with_chunks(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    title: str,
    source: str | None,
    content: str,
    metadata: dict[str, Any],
    chunks: list[tuple[str, list[float]]],
) -> UUID:
    """Inserta un documento RAG y sus chunks ya embedidos."""
    document_id = uuid4()
    await conn.execute(
        """
        INSERT INTO knowledge_base_documents
          (id, tenant_id, title, source, content, metadata)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        """,
        document_id,
        tenant_id,
        title,
        source,
        content,
        metadata,  # el codec del pool serializa a jsonb (no json.dumps manual)
    )
    # NOTA: pasamos `embedding` (lista Python) directamente. El pool tiene
    # `register_vector(conn)` en _init_connection (apps/api/db/client.py) que
    # registra el codec pgvector — asyncpg encoda la lista al tipo `vector`
    # automáticamente. Convertirlo manualmente a string con
    # _embedding_to_pg_vector rompe con el codec: asyncpg intenta convertir
    # el string a float, falla con DataError ("could not convert string to
    # float: '[0.1,...]'"). El _embedding_to_pg_vector es legacy pre-codec.
    rows = [
        (
            uuid4(),
            tenant_id,
            document_id,
            index,
            chunk_content,
            embedding,
            len(chunk_content.split()),
        )
        for index, (chunk_content, embedding) in enumerate(chunks)
    ]
    await conn.executemany(
        """
        INSERT INTO knowledge_base_chunks
          (id, tenant_id, document_id, chunk_index, content, embedding, token_count)
        VALUES ($1, $2, $3, $4, $5, $6::vector, $7)
        """,
        rows,
    )
    return document_id


async def get_tenant_metrics(
    conn: asyncpg.Connection, tenant_id: UUID
) -> dict[str, int]:
    """Conteos de conversaciones por status para un tenant.

    Devuelve un dict con claves: total, open, pending, escalated, resolved, closed.
    Corre dentro del tenant_scope del caller.
    """
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*)                                           AS total,
            COUNT(*) FILTER (WHERE status = 'open')           AS open_count,
            COUNT(*) FILTER (WHERE status = 'pending')        AS pending_count,
            COUNT(*) FILTER (WHERE status = 'escalated')      AS escalated_count,
            COUNT(*) FILTER (WHERE status = 'resolved')       AS resolved_count,
            COUNT(*) FILTER (WHERE status = 'closed')         AS closed_count
          FROM conversations
         WHERE tenant_id = $1 AND deleted_at IS NULL
        """,
        tenant_id,
    )
    assert row is not None
    return dict(row)


async def get_tenant_resolution_series(
    conn: asyncpg.Connection, tenant_id: UUID
) -> dict[str, list[dict[str, Any]]]:
    """Series de resolución/escalación para el dashboard del cliente."""

    daily_rows = await conn.fetch(
        """
        WITH windows(key, bucket_count) AS (
          VALUES ('30d'::text, 30), ('7d'::text, 7)
        ),
        buckets AS (
          SELECT
            w.key,
            gs.bucket::date AS bucket
          FROM windows w
          CROSS JOIN LATERAL generate_series(
            CURRENT_DATE - (w.bucket_count - 1) * INTERVAL '1 day',
            CURRENT_DATE,
            INTERVAL '1 day'
          ) AS gs(bucket)
        ),
        created_counts AS (
          SELECT
            b.key,
            c.created_at::date AS bucket,
            COUNT(*)::int AS conversations
          FROM conversations c
          JOIN buckets b ON c.created_at::date = b.bucket
          WHERE c.tenant_id = $1 AND c.deleted_at IS NULL
          GROUP BY b.key, c.created_at::date
        ),
        resolved_counts AS (
          SELECT
            b.key,
            c.updated_at::date AS bucket,
            COUNT(*)::int AS resolved
          FROM conversations c
          JOIN buckets b ON c.updated_at::date = b.bucket
          WHERE c.tenant_id = $1
            AND c.deleted_at IS NULL
            AND c.status IN ('resolved', 'closed')
          GROUP BY b.key, c.updated_at::date
        ),
        escalated_counts AS (
          SELECT
            b.key,
            e.created_at::date AS bucket,
            COUNT(*)::int AS escalated
          FROM escalations e
          JOIN buckets b ON e.created_at::date = b.bucket
          WHERE e.tenant_id = $1 AND e.deleted_at IS NULL
          GROUP BY b.key, e.created_at::date
        )
        SELECT
          b.key,
          b.bucket::text AS bucket,
          COALESCE(cc.conversations, 0)::int AS conversations,
          COALESCE(rc.resolved, 0)::int AS resolved,
          COALESCE(ec.escalated, 0)::int AS escalated
        FROM buckets b
        LEFT JOIN created_counts cc ON cc.key = b.key AND cc.bucket = b.bucket
        LEFT JOIN resolved_counts rc ON rc.key = b.key AND rc.bucket = b.bucket
        LEFT JOIN escalated_counts ec ON ec.key = b.key AND ec.bucket = b.bucket
        ORDER BY b.key, b.bucket
        """,
        tenant_id,
    )

    hourly_rows = await conn.fetch(
        """
        WITH buckets AS (
          SELECT gs.bucket AS bucket
          FROM generate_series(
            date_trunc('hour', NOW()) - INTERVAL '23 hours',
            date_trunc('hour', NOW()),
            INTERVAL '1 hour'
          ) AS gs(bucket)
        ),
        created_counts AS (
          SELECT
            b.bucket,
            COUNT(*)::int AS conversations
          FROM conversations c
          JOIN buckets b
            ON c.created_at >= b.bucket
           AND c.created_at < b.bucket + INTERVAL '1 hour'
          WHERE c.tenant_id = $1 AND c.deleted_at IS NULL
          GROUP BY b.bucket
        ),
        resolved_counts AS (
          SELECT
            b.bucket,
            COUNT(*)::int AS resolved
          FROM conversations c
          JOIN buckets b
            ON c.updated_at >= b.bucket
           AND c.updated_at < b.bucket + INTERVAL '1 hour'
          WHERE c.tenant_id = $1
            AND c.deleted_at IS NULL
            AND c.status IN ('resolved', 'closed')
          GROUP BY b.bucket
        ),
        escalated_counts AS (
          SELECT
            b.bucket,
            COUNT(*)::int AS escalated
          FROM escalations e
          JOIN buckets b
            ON e.created_at >= b.bucket
           AND e.created_at < b.bucket + INTERVAL '1 hour'
          WHERE e.tenant_id = $1 AND e.deleted_at IS NULL
          GROUP BY b.bucket
        )
        SELECT
          '24h'::text AS key,
          b.bucket::text AS bucket,
          COALESCE(cc.conversations, 0)::int AS conversations,
          COALESCE(rc.resolved, 0)::int AS resolved,
          COALESCE(ec.escalated, 0)::int AS escalated
        FROM buckets b
        LEFT JOIN created_counts cc ON cc.bucket = b.bucket
        LEFT JOIN resolved_counts rc ON rc.bucket = b.bucket
        LEFT JOIN escalated_counts ec ON ec.bucket = b.bucket
        ORDER BY b.bucket
        """,
        tenant_id,
    )

    result: dict[str, list[dict[str, Any]]] = {"30d": [], "7d": [], "24h": []}
    for row in [*daily_rows, *hourly_rows]:
        result[str(row["key"])].append(
            {
                "bucket": row["bucket"],
                "conversations": int(row["conversations"]),
                "resolved": int(row["resolved"]),
                "escalated": int(row["escalated"]),
            }
        )
    return result


async def get_tenant_insights(
    conn: asyncpg.Connection, tenant_id: UUID, days: int = 14
) -> dict[str, Any]:
    """Resumen ejecutivo para el dashboard cliente Insights.

    Usa sólo señales ya existentes: conversaciones, canales e intent_classifier_runs.
    """
    row = await conn.fetchrow(
        """
        WITH bounds AS (
          SELECT
            GREATEST($2::int, 1) AS days,
            (CURRENT_DATE - (GREATEST($2::int, 1) - 1) * INTERVAL '1 day')::date AS start_date,
            CURRENT_DATE::date AS end_date
        ),
        day_series AS (
          SELECT generate_series(b.start_date, b.end_date, INTERVAL '1 day')::date AS day
          FROM bounds b
        ),
        daily_counts AS (
          SELECT c.created_at::date AS day, COUNT(*)::int AS count
          FROM conversations c, bounds b
          WHERE c.tenant_id = $1
            AND c.deleted_at IS NULL
            AND c.is_simulation = FALSE
            AND c.created_at::date >= b.start_date
            AND c.created_at::date <= b.end_date
          GROUP BY c.created_at::date
        ),
        timeline AS (
          SELECT COALESCE(
            jsonb_agg(
              jsonb_build_object(
                'date', ds.day::text,
                'conversations', COALESCE(dc.count, 0)
              )
              ORDER BY ds.day
            ),
            '[]'::jsonb
          ) AS items
          FROM day_series ds
          LEFT JOIN daily_counts dc ON dc.day = ds.day
        ),
        intent_counts AS (
          SELECT i.primary_slug AS label, COUNT(*)::int AS count
          FROM intent_classifier_runs i, bounds b
          WHERE i.tenant_id = $1
            AND i.created_at::date >= b.start_date
            AND i.created_at::date <= b.end_date
          GROUP BY i.primary_slug
          ORDER BY count DESC, i.primary_slug ASC
          LIMIT 6
        ),
        top_intents AS (
          SELECT COALESCE(
            jsonb_agg(jsonb_build_object('label', label, 'count', count)),
            '[]'::jsonb
          ) AS items
          FROM intent_counts
        ),
        channel_counts AS (
          SELECT c.channel::text AS label, COUNT(*)::int AS count
          FROM conversations c, bounds b
          WHERE c.tenant_id = $1
            AND c.deleted_at IS NULL
            AND c.is_simulation = FALSE
            AND c.created_at::date >= b.start_date
            AND c.created_at::date <= b.end_date
          GROUP BY c.channel
          ORDER BY count DESC, c.channel ASC
        ),
        by_channel AS (
          SELECT COALESCE(
            jsonb_agg(jsonb_build_object('label', label, 'count', count)),
            '[]'::jsonb
          ) AS items
          FROM channel_counts
        ),
        status_counts AS (
          SELECT c.status::text AS label, COUNT(*)::int AS count
          FROM conversations c, bounds b
          WHERE c.tenant_id = $1
            AND c.deleted_at IS NULL
            AND c.is_simulation = FALSE
            AND c.created_at::date >= b.start_date
            AND c.created_at::date <= b.end_date
          GROUP BY c.status
          ORDER BY count DESC, c.status ASC
        ),
        by_status AS (
          SELECT COALESCE(
            jsonb_agg(jsonb_build_object('label', label, 'count', count)),
            '[]'::jsonb
          ) AS items
          FROM status_counts
        )
        SELECT jsonb_build_object(
          'days', (SELECT days FROM bounds),
          'timeline', timeline.items,
          'top_intents', top_intents.items,
          'by_channel', by_channel.items,
          'by_status', by_status.items
        ) AS insights
        FROM timeline, top_intents, by_channel, by_status
        """,
        tenant_id,
        days,
    )
    assert row is not None
    insights = row["insights"]
    if isinstance(insights, str):
        return json.loads(insights)
    return dict(insights)


async def list_all_tenants(conn: asyncpg.Connection) -> list[Tenant]:
    """Super-admin: listar todos los tenants activos sin tenant_scope."""
    rows = await conn.fetch(
        """
        SELECT id, slug, name, status, agent_lifecycle_state, plan_tier
          FROM tenants
         WHERE deleted_at IS NULL
         ORDER BY name
        """,
    )
    return [Tenant(**dict(r)) for r in rows]


async def list_admin_review_queue(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Cola cross-tenant para el Home interno.

    Corre con bootstrap_connection y sólo debe exponerse a super_admin.
    """
    rows = await conn.fetch(
        """
        WITH kb AS (
          SELECT tenant_id, COUNT(*)::int AS pending
          FROM tenant_knowledge_submissions
          WHERE status = 'pending_review'::tenant_knowledge_submission_status
            AND deleted_at IS NULL
          GROUP BY tenant_id
        ),
        weekly AS (
          SELECT tenant_id, COUNT(*)::int AS pending
          FROM weekly_reports
          WHERE status = 'pending_review'::weekly_report_status
            AND deleted_at IS NULL
          GROUP BY tenant_id
        ),
        approvals AS (
          SELECT tenant_id, COUNT(*)::int AS pending
          FROM pending_approvals
          WHERE status = 'pending'
          GROUP BY tenant_id
        ),
        proposals AS (
          SELECT tenant_id, COUNT(*)::int AS pending
          FROM improvement_proposals
          WHERE status = 'pending'
          GROUP BY tenant_id
        )
        SELECT
          t.id AS tenant_id,
          t.name AS tenant_name,
          t.status AS tenant_status,
          t.agent_lifecycle_state,
          COALESCE(kb.pending, 0)::int AS kb_pending,
          COALESCE(weekly.pending, 0)::int AS weekly_reports_pending,
          COALESCE(approvals.pending, 0)::int AS approvals_pending,
          COALESCE(proposals.pending, 0)::int AS proposals_pending,
          (
            COALESCE(kb.pending, 0)
            + COALESCE(weekly.pending, 0)
            + COALESCE(approvals.pending, 0)
            + COALESCE(proposals.pending, 0)
          )::int AS total_pending
        FROM tenants t
        LEFT JOIN kb ON kb.tenant_id = t.id
        LEFT JOIN weekly ON weekly.tenant_id = t.id
        LEFT JOIN approvals ON approvals.tenant_id = t.id
        LEFT JOIN proposals ON proposals.tenant_id = t.id
        WHERE t.deleted_at IS NULL
        ORDER BY total_pending DESC, t.name ASC
        """
    )
    return [dict(row) for row in rows]


# ============================================================
# Lifecycle de conversación — cleanup de abandonadas
# ============================================================


async def get_stale_conversations(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    cutoff: datetime,
) -> list[tuple[UUID, str, datetime]]:
    """Retorna (id, channel, last_activity) para conversaciones open/pending
    cuya última actividad es anterior a `cutoff`.

    Se usa `COALESCE(last_message_at, created_at)` como proxy de actividad para
    no perder tickets recién creados que aún no tienen mensajes registrados.
    """
    rows = await conn.fetch(
        """
        SELECT id,
               channel::text,
               COALESCE(last_message_at, created_at) AS last_activity
          FROM conversations
         WHERE tenant_id = $1
           AND deleted_at IS NULL
           AND is_simulation = FALSE
           AND status IN ('open', 'pending')
           AND COALESCE(last_message_at, created_at) < $2
        """,
        tenant_id,
        cutoff,
    )
    return [(row["id"], row["channel"], row["last_activity"]) for row in rows]


async def mark_conversations_abandoned(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_ids: list[UUID],
) -> int:
    """Marca conversaciones como `closed_abandoned`. Retorna el nº de filas actualizadas.

    El filtro `status IN ('open', 'pending')` evita doble-cierre si el job
    corre dos veces en paralelo (race condition en deploys).
    """
    result = await conn.execute(
        """
        UPDATE conversations
           SET status     = 'closed_abandoned'::conversation_status,
               updated_at = now()
         WHERE tenant_id = $1
           AND id         = ANY($2::uuid[])
           AND deleted_at IS NULL
           AND status IN ('open', 'pending')
        """,
        tenant_id,
        conversation_ids,
    )
    # asyncpg devuelve "UPDATE N" como string
    return int(result.split()[-1])


async def get_nudge_candidates(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    lenient_cutoff: datetime,
) -> list[tuple[UUID, str, datetime]]:
    """Retorna (id, channel, last_activity) para conversaciones que entran en la ventana de nudge.

    Pre-filtro SQL: activas, sin nudge previo, con última actividad antes del cutoff más permisivo.
    El refinamiento por canal (timeout específico) se hace en Python en el cleanup service.
    """
    rows = await conn.fetch(
        """
        SELECT id,
               channel::text,
               COALESCE(last_message_at, created_at) AS last_activity
          FROM conversations
         WHERE tenant_id = $1
           AND deleted_at IS NULL
           AND is_simulation = FALSE
           AND status IN ('open', 'pending')
           AND nudged_at IS NULL
           AND COALESCE(last_message_at, created_at) < $2
        """,
        tenant_id,
        lenient_cutoff,
    )
    return [(row["id"], row["channel"], row["last_activity"]) for row in rows]


async def mark_conversations_nudged(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_ids: list[UUID],
) -> int:
    """Setea nudged_at = now() en las conversaciones indicadas. Retorna el nº de filas."""
    result = await conn.execute(
        """
        UPDATE conversations
           SET nudged_at  = now(),
               updated_at = now()
         WHERE tenant_id = $1
           AND id         = ANY($2::uuid[])
           AND deleted_at IS NULL
           AND status IN ('open', 'pending')
           AND nudged_at IS NULL
        """,
        tenant_id,
        conversation_ids,
    )
    return int(result.split()[-1])


# ============================================================
# AOPs — Agent Operating Procedures
# ============================================================


def _row_to_aop_with_content(row: asyncpg.Record) -> AopWithContent:
    return AopWithContent(**dict(row))


async def get_active_aops(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    workspace: AopWorkspace = "production",
) -> list[AopWithContent]:
    """Catálogo de AOPs activos para un tenant+workspace.

    Usado por select_aop para construir la lista de slugs/descriptions
    que se le pasa al clasificador de intent.
    """
    rows = await conn.fetch(
        """
        SELECT a.id, a.tenant_id, a.slug, a.workspace, a.current_version, a.is_active,
               v.yaml_frontmatter, v.body_markdown, v.raw_source
          FROM aops a
          JOIN aop_versions v
            ON v.aop_id = a.id AND v.version = a.current_version
               AND v.tenant_id = a.tenant_id
         WHERE a.tenant_id = $1
           AND a.workspace = $2
           AND a.is_active = true
           AND a.deleted_at IS NULL
         ORDER BY a.slug
        """,
        tenant_id,
        workspace,
    )
    return [_row_to_aop_with_content(r) for r in rows]


async def get_aop_by_slug(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    slug: str,
    workspace: AopWorkspace = "production",
) -> AopWithContent | None:
    """AOP con su contenido actual para un slug específico."""
    row = await conn.fetchrow(
        """
        SELECT a.id, a.tenant_id, a.slug, a.workspace, a.current_version, a.is_active,
               v.yaml_frontmatter, v.body_markdown, v.raw_source
          FROM aops a
          JOIN aop_versions v
            ON v.aop_id = a.id AND v.version = a.current_version
               AND v.tenant_id = a.tenant_id
         WHERE a.tenant_id = $1
           AND a.slug = $2
           AND a.workspace = $3
           AND a.is_active = true
           AND a.deleted_at IS NULL
        """,
        tenant_id,
        slug,
        workspace,
    )
    return None if row is None else _row_to_aop_with_content(row)


async def create_aop(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    slug: str,
    workspace: AopWorkspace,
    yaml_frontmatter: dict,
    body_markdown: str,
    raw_source: str,
    created_by: UUID | None = None,
) -> AopWithContent:
    """Crea un AOP con su versión inicial (version=1). Operación en dos pasos dentro
    de la transacción del caller.

    Levanta `asyncpg.UniqueViolationError` si ya existe un AOP con el mismo
    (tenant_id, slug, workspace).
    """
    aop_row = await conn.fetchrow(
        """
        INSERT INTO aops (tenant_id, slug, workspace, current_version, is_active)
        VALUES ($1, $2, $3, 1, true)
        RETURNING id, tenant_id, slug, workspace, current_version
        """,
        tenant_id,
        slug,
        workspace,
    )
    assert aop_row is not None
    aop_id = aop_row["id"]

    await conn.execute(
        """
        INSERT INTO aop_versions
               (aop_id, tenant_id, version, yaml_frontmatter, body_markdown, raw_source, created_by)
        VALUES ($1, $2, 1, $3, $4, $5, $6)
        """,
        aop_id,
        tenant_id,
        yaml_frontmatter,
        body_markdown,
        raw_source,
        created_by,
    )

    result = await get_aop_by_slug(conn, tenant_id, slug, workspace)
    assert result is not None
    return result


async def save_aop_version(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    aop_id: UUID,
    yaml_frontmatter: dict,
    body_markdown: str,
    raw_source: str,
    created_by: UUID | None = None,
) -> AopVersion:
    """Añade una nueva versión al AOP y actualiza current_version.

    Usa la versión actual del AOP como base para el número de versión nuevo.
    El caller debe estar dentro de una transacción para garantizar atomicidad.
    """
    version_row = await conn.fetchrow(
        """
        INSERT INTO aop_versions
               (aop_id, tenant_id, version, yaml_frontmatter, body_markdown, raw_source, created_by)
        SELECT $1, $2, current_version + 1, $3, $4, $5, $6
          FROM aops
         WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL
        RETURNING id, aop_id, tenant_id, version, yaml_frontmatter, body_markdown,
                  raw_source, created_by, created_at
        """,
        aop_id,
        tenant_id,
        yaml_frontmatter,
        body_markdown,
        raw_source,
        created_by,
    )
    if version_row is None:
        raise ValueError(f"AOP {aop_id} no encontrado para tenant {tenant_id}")

    await conn.execute(
        """
        UPDATE aops
           SET current_version = current_version + 1
         WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL
        """,
        aop_id,
        tenant_id,
    )

    data = dict(version_row)
    data["yaml_frontmatter"] = dict(data["yaml_frontmatter"])
    return AopVersion(**data)


# ============================================================
# Intent classifier runs
# ============================================================


async def get_last_intent_for_conversation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
) -> str | None:
    """Retorna el slug del AOP del último intent classifier run de la conversación."""
    row = await conn.fetchrow(
        """
        SELECT primary_slug
          FROM intent_classifier_runs
         WHERE tenant_id = $1 AND conversation_id = $2
         ORDER BY created_at DESC
         LIMIT 1
        """,
        tenant_id,
        conversation_id,
    )
    return row["primary_slug"] if row else None


async def insert_intent_classifier_run(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    turn_number: int,
    primary_slug: str,
    primary_confidence: float,
    alternative_slug: str | None = None,
    alternative_confidence: float | None = None,
    ambiguity_detected: bool,
    was_reclassification: bool,
) -> IntentClassifierRun:
    """Registra una ejecución del clasificador de intent. Siempre se persiste, incluso
    cuando se cae al AOP 'default' — eso es exactamente lo que queremos auditar.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO intent_classifier_runs (
            tenant_id, conversation_id, turn_number,
            primary_slug, primary_confidence,
            alternative_slug, alternative_confidence,
            ambiguity_detected, was_reclassification
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id, tenant_id, conversation_id, turn_number,
                  primary_slug, primary_confidence::float,
                  alternative_slug, alternative_confidence::float,
                  ambiguity_detected, was_reclassification,
                  human_correction, created_at
        """,
        tenant_id,
        conversation_id,
        turn_number,
        primary_slug,
        primary_confidence,
        alternative_slug,
        alternative_confidence,
        ambiguity_detected,
        was_reclassification,
    )
    assert row is not None
    return IntentClassifierRun(**dict(row))


# ============================================================
# AOP management queries (dashboard editor)
# ============================================================


async def list_aops(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    workspace: AopWorkspace = "production",
) -> list[AopWithContent]:
    """Todos los AOPs del tenant (activos e inactivos), sin deleted.

    Para el dashboard editor — incluye is_active para gestión.
    """
    rows = await conn.fetch(
        """
        SELECT a.id, a.tenant_id, a.slug, a.workspace, a.current_version, a.is_active,
               v.yaml_frontmatter, v.body_markdown, v.raw_source
          FROM aops a
          JOIN aop_versions v
            ON v.aop_id = a.id AND v.version = a.current_version
               AND v.tenant_id = a.tenant_id
         WHERE a.tenant_id = $1
           AND a.workspace = $2
           AND a.deleted_at IS NULL
         ORDER BY a.slug
        """,
        tenant_id,
        workspace,
    )
    return [_row_to_aop_with_content(r) for r in rows]


async def get_aop_by_id(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    aop_id: UUID,
) -> AopWithContent | None:
    """AOP con contenido actual por UUID. No filtra is_active."""
    row = await conn.fetchrow(
        """
        SELECT a.id, a.tenant_id, a.slug, a.workspace, a.current_version, a.is_active,
               v.yaml_frontmatter, v.body_markdown, v.raw_source
          FROM aops a
          JOIN aop_versions v
            ON v.aop_id = a.id AND v.version = a.current_version
               AND v.tenant_id = a.tenant_id
         WHERE a.id = $1
           AND a.tenant_id = $2
           AND a.deleted_at IS NULL
        """,
        aop_id,
        tenant_id,
    )
    return None if row is None else _row_to_aop_with_content(row)


async def toggle_aop_active(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    aop_id: UUID,
    is_active: bool,
) -> None:
    """Activa o desactiva un AOP sin borrarlo."""
    await conn.execute(
        """
        UPDATE aops
           SET is_active = $3, updated_at = now()
         WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL
        """,
        aop_id,
        tenant_id,
        is_active,
    )


async def soft_delete_aop(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    aop_id: UUID,
) -> None:
    """Soft-delete un AOP — nunca borra la fila ni las versiones."""
    await conn.execute(
        """
        UPDATE aops
           SET deleted_at = now(), updated_at = now(), is_active = false
         WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL
        """,
        aop_id,
        tenant_id,
    )


# ============================================================
# Agent Reasoning Events (Sprint 8)
# ============================================================


async def insert_reasoning_event(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    phase: ReasoningPhase,
    event_type: ReasoningEventType,
    label: str,
    detail: dict | None = None,
    status: ReasoningStatus = "done",
) -> AgentReasoningEvent:
    """Inserta un evento de razonamiento. El seq se auto-calcula como MAX(seq)+1
    por conversation_id — es seguro porque los eventos son secuenciales dentro
    de una sola invocación del grafo.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO agent_reasoning_events
               (tenant_id, conversation_id, phase, event_type, label, detail, status, seq)
        VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            COALESCE(
                (SELECT MAX(seq) + 1
                   FROM agent_reasoning_events
                  WHERE conversation_id = $2 AND deleted_at IS NULL),
                0
            )
        )
        RETURNING id, tenant_id, conversation_id, phase, event_type, label, detail,
                  status, seq, created_at
        """,
        tenant_id,
        conversation_id,
        phase,
        event_type,
        label,
        detail,
        status,
    )
    assert row is not None
    return AgentReasoningEvent(**dict(row))


async def list_reasoning_events(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> list[AgentReasoningEvent]:
    """Lista eventos de razonamiento para una conversación, ordenados por seq."""
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, conversation_id, phase, event_type, label, detail,
               status, seq, created_at
          FROM agent_reasoning_events
         WHERE tenant_id = $1
           AND conversation_id = $2
           AND deleted_at IS NULL
         ORDER BY seq ASC, created_at ASC
        """,
        tenant_id,
        conversation_id,
    )
    result = []
    for r in rows:
        data = dict(r)
        data["detail"] = dict(data["detail"]) if data["detail"] is not None else None
        result.append(AgentReasoningEvent(**data))
    return result


# ============================================================
# Idempotency keys (Sprint 9.1)
# Corren con bootstrap_connection (sin tenant_scope) — misma razón
# que get_tenant_by_slug: la verificación ocurre antes de entrar al
# scope de tenant. El tenant_id se pasa siempre explícito en WHERE.
# ============================================================


async def try_insert_idempotency_key(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    key: str,
    request_path: str,
) -> IdempotencyRecord | None:
    """Intenta insertar una key con status 'pending'.

    Devuelve el registro creado, o None si ya existe una key activa
    (conflicto UNIQUE — el llamador decide qué hacer).
    """
    import asyncpg as _asyncpg  # import local para evitar ciclo en TYPE_CHECKING

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO idempotency_keys (tenant_id, key, request_path)
            VALUES ($1, $2, $3)
            RETURNING id, tenant_id, key, request_path, status,
                      response_status, response_body, created_at, expires_at
            """,
            tenant_id,
            key,
            request_path,
        )
    except _asyncpg.UniqueViolationError:
        return None
    assert row is not None
    data = dict(row)
    data["response_body"] = dict(data["response_body"]) if data["response_body"] else None
    return IdempotencyRecord(**data)


async def get_idempotency_record(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    key: str,
) -> IdempotencyRecord | None:
    """Devuelve el registro activo (no expirado, no borrado) o None."""
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, key, request_path, status,
               response_status, response_body, created_at, expires_at
          FROM idempotency_keys
         WHERE tenant_id = $1
           AND key = $2
           AND expires_at > now()
           AND deleted_at IS NULL
        """,
        tenant_id,
        key,
    )
    if row is None:
        return None
    data = dict(row)
    data["response_body"] = dict(data["response_body"]) if data["response_body"] else None
    return IdempotencyRecord(**data)


async def complete_idempotency_key(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    key: str,
    response_status: int,
    response_body: dict,
) -> None:
    """Marca la key como 'done' y persiste la respuesta para cachearla."""
    await conn.execute(
        """
        UPDATE idempotency_keys
           SET status = 'done',
               response_status = $3,
               response_body = $4
         WHERE tenant_id = $1
           AND key = $2
           AND deleted_at IS NULL
        """,
        tenant_id,
        key,
        response_status,
        response_body,
    )


async def delete_idempotency_key(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    key: str,
) -> None:
    """Soft-delete la key para que el siguiente intento pueda procesarse de nuevo.

    Se llama cuando el procesamiento falla — permite reintentos correctos.
    """
    await conn.execute(
        """
        UPDATE idempotency_keys
           SET deleted_at = now()
         WHERE tenant_id = $1
           AND key = $2
        """,
        tenant_id,
        key,
    )


# ─── Skill Audit Log (Sprint 9.3) ────────────────────────────────────────────


async def get_tenant_pii_salt(
    conn: asyncpg.Connection,
    tenant_id: UUID,
) -> str:
    """Devuelve el salt PII del tenant, creándolo si no existe."""
    import secrets as _secrets

    row = await conn.fetchrow(
        "SELECT pii_salt FROM tenant_secrets WHERE tenant_id = $1",
        tenant_id,
    )
    if row:
        return str(row["pii_salt"])
    salt = _secrets.token_hex(32)
    await conn.execute(
        """
        INSERT INTO tenant_secrets (tenant_id, pii_salt)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        """,
        tenant_id,
        salt,
    )
    # Re-fetch por si otro worker ganó el INSERT concurrente.
    row2 = await conn.fetchrow(
        "SELECT pii_salt FROM tenant_secrets WHERE tenant_id = $1",
        tenant_id,
    )
    return str(row2["pii_salt"]) if row2 else salt


async def insert_skill_audit_log(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    aop_slug: str,
    aop_version: int,
    skill_slug: str,
    skill_tier: str,
    inputs_redacted: dict,
    inputs_hash: str,
    status: str,
    outputs_redacted: dict | None = None,
    idempotency_key: UUID | None = None,
    confidence: float | None = None,
    supervisor_verdict: str | None = None,
    error_message: str | None = None,
    latency_ms: int | None = None,
    langfuse_trace_id: str | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO skill_audit_log (
            tenant_id, conversation_id,
            aop_slug, aop_version,
            skill_slug, skill_tier,
            idempotency_key,
            inputs_redacted, outputs_redacted, inputs_hash,
            confidence, supervisor_verdict,
            status, error_message, latency_ms, langfuse_trace_id
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16
        )
        """,
        tenant_id,
        conversation_id,
        aop_slug,
        aop_version,
        skill_slug,
        skill_tier,
        idempotency_key,
        inputs_redacted,
        outputs_redacted,
        inputs_hash,
        confidence,
        supervisor_verdict,
        status,
        error_message,
        latency_ms,
        langfuse_trace_id,
    )


async def list_skill_audit_log(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[SkillAuditLog]:
    """Lista entradas del audit log, opcionalmente filtradas por conversación."""
    if conversation_id:
        rows = await conn.fetch(
            """
            SELECT *
              FROM skill_audit_log
             WHERE tenant_id = $1
               AND conversation_id = $2
             ORDER BY created_at DESC
             LIMIT $3 OFFSET $4
            """,
            tenant_id,
            conversation_id,
            limit,
            offset,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT *
              FROM skill_audit_log
             WHERE tenant_id = $1
             ORDER BY created_at DESC
             LIMIT $2 OFFSET $3
            """,
            tenant_id,
            limit,
            offset,
        )
    return [SkillAuditLog(**dict(r)) for r in rows]


# ============================================================
# AOP cache invalidation — Postgres NOTIFY
# ============================================================


async def notify_aop_cache_invalidated(
    conn: asyncpg.Connection,
    tenant_id: Any,
    slug: str,
    workspace: str,
) -> None:
    """Emite pg_notify dentro de la transacción activa.

    Se dispara solo cuando la transacción hace commit — nunca en rollback.
    Todos los workers con LISTEN activo recibirán la notificación y descartarán
    su entrada local del cache para (tenant_id, slug, workspace).
    """
    payload = json.dumps({"tenant_id": str(tenant_id), "slug": slug, "workspace": workspace})
    await conn.execute("SELECT pg_notify('aop_cache_invalidated', $1)", payload)


# ============================================================
# Tenant Tool Permissions (Sprint 10)
# ============================================================


async def get_tool_permissions(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    slugs: list[str],
) -> dict[str, TenantToolPermission]:
    """Devuelve un dict slug→TenantToolPermission para los slugs solicitados.

    Si un slug no tiene row en la tabla, no aparece en el resultado — el caller
    debe tratarlo como deshabilitado (fail-safe).
    """
    if not slugs:
        return {}
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, skill_slug, is_enabled, threshold_override,
               human_approval_required, enabled_at, enabled_by, created_at
          FROM tenant_tool_permissions
         WHERE tenant_id = $1
           AND skill_slug = ANY($2::text[])
           AND deleted_at IS NULL
        """,
        tenant_id,
        slugs,
    )
    return {r["skill_slug"]: TenantToolPermission(**dict(r)) for r in rows}


async def upsert_tool_permission(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    skill_slug: str,
    is_enabled: bool,
    human_approval_required: bool = False,
    threshold_override: float | None = None,
    enabled_by: UUID | None = None,
    l3_autonomy_acknowledged: bool = False,
) -> TenantToolPermission:
    """Crea o actualiza el permiso de una skill para un tenant.

    `l3_autonomy_acknowledged` registra un opt-out CONSCIENTE de la aprobación humana
    para una L3: cuando es True sella acknowledged_at=NOW() + acknowledged_by; cuando es
    False los limpia a NULL. El opt-out solo persiste mientras se reafirme — un update
    posterior que no lo reconozca vuelve a fail-safe (execute_skill exige approval).
    """
    row = await conn.fetchrow(
        """
        INSERT INTO tenant_tool_permissions
            (tenant_id, skill_slug, is_enabled, human_approval_required,
             threshold_override, enabled_at, enabled_by,
             l3_autonomy_acknowledged_at, l3_autonomy_acknowledged_by)
        VALUES ($1, $2, $3, $4, $5, CASE WHEN $3 THEN NOW() ELSE NULL END, $6,
                CASE WHEN $7 THEN NOW() ELSE NULL END,
                CASE WHEN $7 THEN $6 ELSE NULL END)
        ON CONFLICT (tenant_id, skill_slug)
        DO UPDATE SET
            is_enabled              = EXCLUDED.is_enabled,
            human_approval_required = EXCLUDED.human_approval_required,
            threshold_override      = EXCLUDED.threshold_override,
            enabled_at              = CASE WHEN EXCLUDED.is_enabled
                                        THEN NOW()
                                        ELSE tenant_tool_permissions.enabled_at
                                      END,
            enabled_by              = COALESCE(
                                        EXCLUDED.enabled_by,
                                        tenant_tool_permissions.enabled_by
                                      ),
            l3_autonomy_acknowledged_at = EXCLUDED.l3_autonomy_acknowledged_at,
            l3_autonomy_acknowledged_by = EXCLUDED.l3_autonomy_acknowledged_by,
            updated_at              = NOW()
        RETURNING id, tenant_id, skill_slug, is_enabled, threshold_override,
                  human_approval_required, enabled_at, enabled_by,
                  l3_autonomy_acknowledged_at, l3_autonomy_acknowledged_by, created_at
        """,
        tenant_id,
        skill_slug,
        is_enabled,
        human_approval_required,
        threshold_override,
        enabled_by,
        l3_autonomy_acknowledged,
    )
    return TenantToolPermission(**dict(row))


async def list_tool_permissions(
    conn: asyncpg.Connection,
    tenant_id: UUID,
) -> list[TenantToolPermission]:
    """Lista todos los permisos de skills de un tenant."""
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, skill_slug, is_enabled, threshold_override,
               human_approval_required, enabled_at, enabled_by,
               l3_autonomy_acknowledged_at, l3_autonomy_acknowledged_by, created_at
          FROM tenant_tool_permissions
         WHERE tenant_id = $1
           AND deleted_at IS NULL
         ORDER BY skill_slug
        """,
        tenant_id,
    )
    return [TenantToolPermission(**dict(r)) for r in rows]


# ============================================================
# Pending Approvals (Sprint 10)
# ============================================================


async def create_pending_approval(
    conn: asyncpg.Connection,
    *,
    approval_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    skill_slug: str,
    skill_tier: str,
    inputs_raw: dict,
    inputs_redacted: dict,
    aop_slug: str,
    aop_version: int,
    langfuse_trace_id: str | None,
) -> PendingApproval:
    """Inserta una solicitud de aprobación humana para una skill L3."""
    row = await conn.fetchrow(
        """
        INSERT INTO pending_approvals
            (id, tenant_id, conversation_id, skill_slug, skill_tier,
             inputs_raw, inputs_redacted, aop_slug, aop_version, langfuse_trace_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id, tenant_id, conversation_id, skill_slug, skill_tier,
                  inputs_raw, inputs_redacted, aop_slug, aop_version,
                  langfuse_trace_id, status, reviewed_by, reviewed_at,
                  review_comment, created_at
        """,
        approval_id,
        tenant_id,
        conversation_id,
        skill_slug,
        skill_tier,
        inputs_raw,
        inputs_redacted,
        aop_slug,
        aop_version,
        langfuse_trace_id,
    )
    return PendingApproval(**dict(row))


async def get_pending_approval(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    approval_id: UUID,
) -> PendingApproval | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, conversation_id, skill_slug, skill_tier,
               inputs_raw, inputs_redacted, aop_slug, aop_version,
               langfuse_trace_id, status, reviewed_by, reviewed_at,
               review_comment, created_at
          FROM pending_approvals
         WHERE tenant_id = $1
           AND id = $2
           AND deleted_at IS NULL
        """,
        tenant_id,
        approval_id,
    )
    return PendingApproval(**dict(row)) if row else None


async def get_recent_approval_for_skill(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
    skill_slug: str,
) -> PendingApproval | None:
    """Devuelve la aprobación más reciente (pending o approved) de la conversación
    para esa skill, o None.

    Sirve para no duplicar el gate L3: si el cliente vuelve a escribir mientras su
    acción sigue en revisión (pending) o ya fue aprobada/ejecutada (approved), el
    agente reusa esa aprobación en vez de crear otra. Las rechazadas se ignoran:
    una acción rechazada sí puede re-intentarse.
    """
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, conversation_id, skill_slug, skill_tier,
               inputs_raw, inputs_redacted, aop_slug, aop_version,
               langfuse_trace_id, status, reviewed_by, reviewed_at,
               review_comment, created_at
          FROM pending_approvals
         WHERE tenant_id = $1
           AND conversation_id = $2
           AND skill_slug = $3
           AND status IN ('pending', 'approved')
           AND deleted_at IS NULL
         ORDER BY created_at DESC
         LIMIT 1
        """,
        tenant_id,
        conversation_id,
        skill_slug,
    )
    return PendingApproval(**dict(row)) if row else None


async def get_recent_read_outputs_for_conversation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
) -> list[tuple[str, dict]]:
    """Último output exitoso por skill de LECTURA (L1) de la conversación.

    Sirve para inyectar 'datos ya verificados' en el contexto del agente y del
    supervisor, y evitar re-consultar lo mismo cada turno. Solo devuelve reads
    POSTERIORES a la última escritura (L2/L3): un intento de mutación invalida los
    reads previos porque el pedido pudo cambiar.
    """
    rows = await conn.fetch(
        """
        WITH last_write AS (
            SELECT max(created_at) AS ts
              FROM skill_audit_log
             WHERE tenant_id = $1 AND conversation_id = $2
               AND skill_tier IN ('L2', 'L3')
        )
        SELECT DISTINCT ON (skill_slug) skill_slug, outputs_redacted
          FROM skill_audit_log
         WHERE tenant_id = $1 AND conversation_id = $2
           AND skill_tier = 'L1' AND status = 'success'
           AND outputs_redacted IS NOT NULL
           AND created_at > COALESCE(
               (SELECT ts FROM last_write), '-infinity'::timestamptz
           )
         ORDER BY skill_slug, created_at DESC
        """,
        tenant_id,
        conversation_id,
    )
    return [(r["skill_slug"], r["outputs_redacted"]) for r in rows]


async def get_approved_actions_for_conversation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
) -> list[tuple[str, dict]]:
    """Skills L3 ya APROBADAS (ejecutadas) en la conversación, con sus inputs.

    Se inyectan en el contexto como 'acciones ya hechas' para que el agente no las
    re-dispare ante un agradecimiento/confirmación del cliente (causa de gates
    espurios + latencia del supervisor L3).
    """
    rows = await conn.fetch(
        """
        SELECT skill_slug, inputs_redacted
          FROM pending_approvals
         WHERE tenant_id = $1 AND conversation_id = $2
           AND status = 'approved' AND deleted_at IS NULL
         ORDER BY created_at
        """,
        tenant_id,
        conversation_id,
    )
    return [(r["skill_slug"], r["inputs_redacted"]) for r in rows]


async def list_pending_approvals(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PendingApproval]:
    """Lista aprobaciones pendientes de un tenant, opcionalmente filtradas por status."""
    if status:
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, conversation_id, skill_slug, skill_tier,
                   inputs_raw, inputs_redacted, aop_slug, aop_version,
                   langfuse_trace_id, status, reviewed_by, reviewed_at,
                   review_comment, created_at
              FROM pending_approvals
             WHERE tenant_id = $1
               AND status = $2
               AND deleted_at IS NULL
             ORDER BY created_at DESC
             LIMIT $3 OFFSET $4
            """,
            tenant_id,
            status,
            limit,
            offset,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, conversation_id, skill_slug, skill_tier,
                   inputs_raw, inputs_redacted, aop_slug, aop_version,
                   langfuse_trace_id, status, reviewed_by, reviewed_at,
                   review_comment, created_at
              FROM pending_approvals
             WHERE tenant_id = $1
               AND deleted_at IS NULL
             ORDER BY created_at DESC
             LIMIT $2 OFFSET $3
            """,
            tenant_id,
            limit,
            offset,
        )
    return [PendingApproval(**dict(r)) for r in rows]


async def has_pending_approval_for_conversation(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
) -> bool:
    """Retorna True si existe al menos un pending_approval para la conversación."""
    row = await conn.fetchrow(
        """
        SELECT 1 FROM pending_approvals
         WHERE tenant_id = $1
           AND conversation_id = $2
           AND deleted_at IS NULL
         LIMIT 1
        """,
        tenant_id,
        conversation_id,
    )
    return row is not None


async def resolve_pending_approval(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    approval_id: UUID,
    new_status: str,
    reviewed_by: UUID,
    review_comment: str | None = None,
) -> PendingApproval | None:
    """Aprueba o rechaza una pending_approval (CAS sobre status='pending')."""
    row = await conn.fetchrow(
        """
        UPDATE pending_approvals
           SET status         = $3,
               reviewed_by    = $4,
               reviewed_at    = NOW(),
               review_comment = $5,
               updated_at     = NOW()
         WHERE tenant_id = $1
           AND id = $2
           AND status = 'pending'
           AND deleted_at IS NULL
        RETURNING id, tenant_id, conversation_id, skill_slug, skill_tier,
                  inputs_raw, inputs_redacted, aop_slug, aop_version,
                  langfuse_trace_id, status, reviewed_by, reviewed_at,
                  review_comment, created_at
        """,
        tenant_id,
        approval_id,
        new_status,
        reviewed_by,
        review_comment,
    )
    return PendingApproval(**dict(row)) if row else None


# ============================================================
# Slow Agent — runs, judgments, proposals (Sprint 11)
# ============================================================


async def insert_slow_agent_run(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    triggered_by: UUID | None,
) -> SlowAgentRun:
    row = await conn.fetchrow(
        """
        INSERT INTO slow_agent_runs (tenant_id, triggered_by, status)
        VALUES ($1, $2, 'running')
        RETURNING id, tenant_id, status, conversations_evaluated, proposals_generated,
                  sonnet_tokens, opus_tokens, cost_usd, triggered_by, error,
                  run_started_at, run_ended_at, created_at
        """,
        tenant_id,
        triggered_by,
    )
    return SlowAgentRun(**dict(row))


async def update_slow_agent_run(
    conn: asyncpg.Connection,
    run_id: UUID,
    tenant_id: UUID,
    *,
    status: str,
    conversations_evaluated: int,
    proposals_generated: int,
    sonnet_tokens: int,
    opus_tokens: int,
    cost_usd: float | None,
    error: str | None,
) -> None:
    await conn.execute(
        """
        UPDATE slow_agent_runs
           SET status                  = $3,
               conversations_evaluated = $4,
               proposals_generated     = $5,
               sonnet_tokens           = $6,
               opus_tokens             = $7,
               cost_usd                = $8,
               error                   = $9,
               run_ended_at            = NOW(),
               updated_at              = NOW()
         WHERE id = $1 AND tenant_id = $2
        """,
        run_id,
        tenant_id,
        status,
        conversations_evaluated,
        proposals_generated,
        sonnet_tokens,
        opus_tokens,
        cost_usd,
        error,
    )


async def list_judged_conversation_ids(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    since_days: int = 30,
) -> set[UUID]:
    """IDs de conversaciones ya juzgadas en los últimos `since_days` días."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT conversation_id
          FROM conversation_judgments
         WHERE tenant_id = $1
           AND created_at >= NOW() - ($2 || ' days')::interval
        """,
        tenant_id,
        str(since_days),
    )
    return {r["conversation_id"] for r in rows}


async def insert_conversation_judgment(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    run_id: UUID,
    conversation_id: UUID,
    verdict_summary: str | None,
    proposal_id: UUID | None,
) -> ConversationJudgment:
    row = await conn.fetchrow(
        """
        INSERT INTO conversation_judgments
               (tenant_id, run_id, conversation_id, verdict_summary, proposal_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (run_id, conversation_id) DO UPDATE
               SET verdict_summary = EXCLUDED.verdict_summary,
                   proposal_id     = EXCLUDED.proposal_id
        RETURNING id, tenant_id, run_id, conversation_id,
                  verdict_summary, proposal_id, created_at
        """,
        tenant_id,
        run_id,
        conversation_id,
        verdict_summary,
        proposal_id,
    )
    return ConversationJudgment(**dict(row))


async def insert_improvement_proposal(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    run_id: UUID,
    proposal_type: str,
    diff_markdown: str,
    rationale: str,
    evidence_conversations: list[UUID],
    judge_model_used: str,
    judge_confidence: float,
    aop_slug: str | None = None,
    requires_eval_pass: bool = True,
) -> ImprovementProposal:
    row = await conn.fetchrow(
        """
        INSERT INTO improvement_proposals
               (tenant_id, run_id, proposal_type, aop_slug, diff_markdown, rationale,
                evidence_conversations, judge_model_used, judge_confidence, requires_eval_pass)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id, tenant_id, run_id, proposal_type, aop_slug, diff_markdown, rationale,
                  evidence_conversations, judge_model_used, judge_confidence, requires_eval_pass,
                  status, reviewed_by, reviewed_at, review_comment, applied_version, created_at
        """,
        tenant_id,
        run_id,
        proposal_type,
        aop_slug,
        diff_markdown,
        rationale,
        evidence_conversations,
        judge_model_used,
        judge_confidence,
        requires_eval_pass,
    )
    data = dict(row)
    data["evidence_conversations"] = list(data["evidence_conversations"] or [])
    return ImprovementProposal(**data)


async def list_improvement_proposals(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ImprovementProposal]:
    where = "tenant_id = $1"
    params: list[Any] = [tenant_id]
    if status:
        params.append(status)
        where += f" AND status = ${len(params)}"
    rows = await conn.fetch(
        f"""
        SELECT id, tenant_id, run_id, proposal_type, aop_slug, diff_markdown, rationale,
               evidence_conversations, judge_model_used, judge_confidence, requires_eval_pass,
               status, reviewed_by, reviewed_at, review_comment, applied_version, created_at
          FROM improvement_proposals
         WHERE {where}
         ORDER BY created_at DESC
         LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params,
        limit,
        offset,
    )
    result = []
    for r in rows:
        data = dict(r)
        data["evidence_conversations"] = list(data["evidence_conversations"] or [])
        result.append(ImprovementProposal(**data))
    return result


async def get_improvement_proposal(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    proposal_id: UUID,
) -> ImprovementProposal | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, run_id, proposal_type, aop_slug, diff_markdown, rationale,
               evidence_conversations, judge_model_used, judge_confidence, requires_eval_pass,
               status, reviewed_by, reviewed_at, review_comment, applied_version, created_at
          FROM improvement_proposals
         WHERE tenant_id = $1 AND id = $2
        """,
        tenant_id,
        proposal_id,
    )
    if row is None:
        return None
    data = dict(row)
    data["evidence_conversations"] = list(data["evidence_conversations"] or [])
    return ImprovementProposal(**data)


async def update_proposal_status(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    proposal_id: UUID,
    status: str,
    reviewed_by: UUID,
    review_comment: str | None = None,
    applied_version: int | None = None,
) -> ImprovementProposal | None:
    row = await conn.fetchrow(
        """
        UPDATE improvement_proposals
           SET status          = $3,
               reviewed_by     = $4,
               reviewed_at     = NOW(),
               review_comment  = $5,
               applied_version = $6,
               updated_at      = NOW()
         WHERE tenant_id = $1 AND id = $2
        RETURNING id, tenant_id, run_id, proposal_type, aop_slug, diff_markdown, rationale,
                  evidence_conversations, judge_model_used, judge_confidence, requires_eval_pass,
                  status, reviewed_by, reviewed_at, review_comment, applied_version, created_at
        """,
        tenant_id,
        proposal_id,
        status,
        reviewed_by,
        review_comment,
        applied_version,
    )
    if row is None:
        return None
    data = dict(row)
    data["evidence_conversations"] = list(data["evidence_conversations"] or [])
    return ImprovementProposal(**data)


async def get_proposals_metrics(
    conn: asyncpg.Connection,
    tenant_id: UUID,
) -> dict[str, Any]:
    """Métricas del slow agent: tasa de aceptación y costo."""
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*)                                                     AS total,
            COUNT(*) FILTER (WHERE status = 'pending')                   AS pending,
            COUNT(*) FILTER (WHERE status = 'approved')                  AS approved,
            COUNT(*) FILTER (WHERE status = 'rejected')                  AS rejected,
            COUNT(*) FILTER (WHERE status = 'applied')                   AS applied,
            COALESCE(SUM(r.cost_usd), 0)                                 AS cost_usd_total,
            COALESCE(SUM(r.sonnet_tokens), 0)                            AS sonnet_tokens_total,
            COALESCE(SUM(r.opus_tokens), 0)                              AS opus_tokens_total
          FROM improvement_proposals p
          JOIN slow_agent_runs r ON r.id = p.run_id
         WHERE p.tenant_id = $1
        """,
        tenant_id,
    )
    data = dict(row)
    reviewed = data["approved"] + data["rejected"] + data["applied"]
    accepted = data["approved"] + data["applied"]
    data["acceptance_rate"] = round(accepted / reviewed, 4) if reviewed > 0 else None
    cost = float(data["cost_usd_total"]) if data["cost_usd_total"] else 0.0
    data["cost_per_accepted_proposal"] = (
        round(cost / accepted, 4) if accepted > 0 else None
    )
    return data



# ============================================================
# Rate limiting
# ============================================================


async def check_and_increment_rate_limit(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    bucket_key: str,
) -> int:
    """Incrementa el contador del bucket de la ventana actual y retorna el total.

    Ventana fija de 60s (date_trunc('minute', now())).
    La operación es atómica — INSERT ... ON CONFLICT DO UPDATE.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO rate_limit_buckets (tenant_id, bucket_key, window_start, count)
        VALUES ($1, $2, date_trunc('minute', now()), 1)
        ON CONFLICT (tenant_id, bucket_key, window_start)
        DO UPDATE SET count = rate_limit_buckets.count + 1
        RETURNING count
        """,
        tenant_id,
        bucket_key,
    )
    return int(row["count"])


async def delete_expired_rate_limit_buckets(conn: asyncpg.Connection) -> int:
    """Elimina buckets con window_start anterior a hace 1 hora. Retorna filas eliminadas."""
    result = await conn.execute(
        """
        DELETE FROM rate_limit_buckets
        WHERE window_start < now() - INTERVAL '1 hour'
        """
    )
    # asyncpg retorna 'DELETE N' como string
    return int(result.split()[-1])


# ---------------------------------------------------------------------------
# tenant_usage_daily
# ---------------------------------------------------------------------------


async def upsert_tenant_usage_daily(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> None:
    """Incrementa atómicamente el uso del día para un tenant.

    INSERT ... ON CONFLICT DO UPDATE garantiza que no se pierdan
    incrementos concurrentes de múltiples workers.
    """
    await conn.execute(
        """
        INSERT INTO tenant_usage_daily
            (tenant_id, date, tokens_in, tokens_out, cost_usd, request_count)
        VALUES ($1, CURRENT_DATE, $2, $3, $4, 1)
        ON CONFLICT (tenant_id, date)
        DO UPDATE SET
            tokens_in     = tenant_usage_daily.tokens_in     + EXCLUDED.tokens_in,
            tokens_out    = tenant_usage_daily.tokens_out    + EXCLUDED.tokens_out,
            cost_usd      = tenant_usage_daily.cost_usd      + EXCLUDED.cost_usd,
            request_count = tenant_usage_daily.request_count + 1,
            updated_at    = now()
        """,
        tenant_id,
        tokens_in,
        tokens_out,
        cost_usd,
    )


async def get_tenant_usage_range(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    days: int = 7,
) -> list[TenantUsageDaily]:
    """Retorna los últimos `days` días de uso para el tenant (más reciente primero).

    Incluye solo días con actividad registrada (no rellena días vacíos).
    """
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, date::text, tokens_in, tokens_out, cost_usd,
               request_count, created_at, updated_at
          FROM tenant_usage_daily
         WHERE tenant_id = $1
           AND date >= CURRENT_DATE - ($2 - 1) * INTERVAL '1 day'
           AND deleted_at IS NULL
         ORDER BY date DESC
        """,
        tenant_id,
        days,
    )
    return [TenantUsageDaily(**dict(row)) for row in rows]



async def get_tenant_usage_today(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
) -> TenantUsageDaily | None:
    """Retorna el registro de uso de hoy para el tenant, o None si no hay actividad."""
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, date::text, tokens_in, tokens_out, cost_usd,
               request_count, created_at, updated_at
        FROM tenant_usage_daily
        WHERE tenant_id = $1
          AND date = CURRENT_DATE
          AND deleted_at IS NULL
        """,
        tenant_id,
    )
    if row is None:
        return None
    return TenantUsageDaily(**dict(row))


# ============================================================
# Tenant Integrations (Bloque 0, Sub-PR 0.2)
# ============================================================

_INTEGRATION_SELECT = (
    "id, tenant_id, kind, provider, config, is_active, is_primary_for_kind,"
    " enabled_at, enabled_by, created_at, updated_at"
)


def _row_to_integration(row: Any) -> TenantIntegration:
    return TenantIntegration(**{k: row[k] for k in TenantIntegration.model_fields})


def _single_integration_or_collision(
    rows: list[Any],
    *,
    provider: str,
    lookup: str,
    value: str,
) -> TenantIntegration | None:
    """Resuelve un lookup cross-tenant a UNA integración, o falla cerrado.

    Las funciones `get_integration_by_*` resuelven el tenant de un webhook entrante
    por un identificador externo (account_id / subdomain / domain). Si ese
    identificador apunta a más de una integración activa, el routing es ambiguo:
    responder enrutaría al tenant equivocado (fuga cross-tenant). En ese caso
    NO adivinamos — logueamos la colisión y lanzamos ConflictError (fail-closed).

    El índice único parcial en tenant_integrations es la red de seguridad a nivel
    DB; este guard cubre el caso de que el índice aún no exista (migración no
    aplicada) o se haya caído.
    """
    if len(rows) > 1:
        tenant_ids = sorted({str(r["tenant_id"]) for r in rows})
        logger.error(
            "integration_routing_collision provider=%s %s=%s tenants=%s — fail-closed",
            provider,
            lookup,
            value,
            tenant_ids,
        )
        raise ConflictError(
            "Routing ambiguo: el identificador apunta a múltiples integraciones activas.",
            code="integration_routing_collision",
        )
    return _row_to_integration(rows[0]) if rows else None


async def get_active_integration(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    kind: IntegrationKind,
    provider: str,
) -> TenantIntegration | None:
    """Devuelve la integración activa para (tenant, kind, provider), o None."""
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, kind, provider, config, is_active, is_primary_for_kind,
               enabled_at, enabled_by, created_at, updated_at
          FROM tenant_integrations
         WHERE tenant_id = $1
           AND kind      = $2
           AND provider  = $3
           AND deleted_at IS NULL
           AND is_active = TRUE
        """,
        tenant_id,
        kind,
        provider,
    )
    return _row_to_integration(row) if row else None


async def get_primary_integration_for_kind(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    kind: IntegrationKind,
) -> TenantIntegration | None:
    """Devuelve la integración marcada como primaria para el kind, o None."""
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, kind, provider, config, is_active, is_primary_for_kind,
               enabled_at, enabled_by, created_at, updated_at
          FROM tenant_integrations
         WHERE tenant_id           = $1
           AND kind                = $2
           AND is_primary_for_kind = TRUE
           AND deleted_at IS NULL
           AND is_active = TRUE
        """,
        tenant_id,
        kind,
    )
    return _row_to_integration(row) if row else None


async def list_integrations_for_tenant(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    kind: IntegrationKind | None = None,
) -> list[TenantIntegration]:
    """Lista integraciones del tenant, opcionalmente filtradas por kind."""
    if kind:
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, kind, provider, config, is_active, is_primary_for_kind,
                   enabled_at, enabled_by, created_at, updated_at
              FROM tenant_integrations
             WHERE tenant_id  = $1
               AND kind       = $2
               AND deleted_at IS NULL
             ORDER BY kind, provider
            """,
            tenant_id,
            kind,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, kind, provider, config, is_active, is_primary_for_kind,
                   enabled_at, enabled_by, created_at, updated_at
              FROM tenant_integrations
             WHERE tenant_id  = $1
               AND deleted_at IS NULL
             ORDER BY kind, provider
            """,
            tenant_id,
        )
    return [_row_to_integration(r) for r in rows]


async def upsert_integration(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    kind: IntegrationKind,
    provider: str,
    credentials_encrypted: bytes,
    config: dict,
    is_active: bool = True,
    is_primary_for_kind: bool = False,
    enabled_by: UUID | None = None,
) -> TenantIntegration:
    """Crea o actualiza una integración. Las credentials ya deben venir cifradas."""
    row = await conn.fetchrow(
        """
        INSERT INTO tenant_integrations
            (tenant_id, kind, provider, credentials_encrypted, config,
             is_active, is_primary_for_kind, enabled_at, enabled_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7,
                CASE WHEN $6 THEN NOW() ELSE NULL END, $8)
        ON CONFLICT (tenant_id, kind, provider) WHERE deleted_at IS NULL
        DO UPDATE SET
            credentials_encrypted = EXCLUDED.credentials_encrypted,
            config                = EXCLUDED.config,
            is_active             = EXCLUDED.is_active,
            is_primary_for_kind   = EXCLUDED.is_primary_for_kind,
            enabled_at            = CASE WHEN EXCLUDED.is_active
                                      THEN COALESCE(
                                            tenant_integrations.enabled_at,
                                            NOW()
                                          )
                                      ELSE tenant_integrations.enabled_at
                                    END,
            enabled_by            = COALESCE(
                                        EXCLUDED.enabled_by,
                                        tenant_integrations.enabled_by
                                    ),
            updated_at            = NOW()
        RETURNING id, tenant_id, kind, provider, config, is_active, is_primary_for_kind,
                  enabled_at, enabled_by, created_at, updated_at
        """,
        tenant_id,
        kind,
        provider,
        credentials_encrypted,
        config,
        is_active,
        is_primary_for_kind,
        enabled_by,
    )
    return _row_to_integration(row)


async def get_integration_credentials_encrypted(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    integration_id: UUID,
) -> bytes | None:
    """Devuelve solo el campo credentials_encrypted para descifrado en el service layer."""
    row = await conn.fetchrow(
        """
        SELECT credentials_encrypted
          FROM tenant_integrations
         WHERE tenant_id  = $1
           AND id         = $2
           AND deleted_at IS NULL
        """,
        tenant_id,
        integration_id,
    )
    return bytes(row["credentials_encrypted"]) if row else None


async def soft_delete_integration(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    integration_id: UUID,
) -> bool:
    """Soft-delete. Retorna True si existía y fue borrado."""
    result = await conn.execute(
        """
        UPDATE tenant_integrations
           SET deleted_at = NOW(),
               updated_at = NOW(),
               is_active  = FALSE
         WHERE tenant_id  = $1
           AND id         = $2
           AND deleted_at IS NULL
        """,
        tenant_id,
        integration_id,
    )
    return result == "UPDATE 1"


async def get_integration_by_chatwoot_account(
    conn: asyncpg.Connection,
    *,
    account_id: str,
) -> TenantIntegration | None:
    """Busca la integración Chatwoot por account_id (cross-tenant, para el webhook handler).

    Debe llamarse con bootstrap_connection() porque no tiene tenant_scope.
    El account_id vive en config->>'account_id' (no está cifrado).
    """
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, kind, provider, config, is_active, is_primary_for_kind,
               enabled_at, enabled_by, created_at, updated_at
          FROM tenant_integrations
         WHERE provider    = 'chatwoot'
           AND kind        = 'helpdesk'
           AND config->>'account_id' = $1
           AND deleted_at IS NULL
           AND is_active = TRUE
         LIMIT 2
        """,
        account_id,
    )
    return _single_integration_or_collision(
        rows, provider="chatwoot", lookup="account_id", value=account_id
    )


async def get_integration_by_zendesk_subdomain(
    conn: asyncpg.Connection,
    *,
    subdomain: str,
) -> TenantIntegration | None:
    """Busca la integración Zendesk por subdomain (cross-tenant, para el webhook handler).

    Debe llamarse con bootstrap_connection() porque no tiene tenant_scope.
    El subdomain vive en config->>'subdomain' (no está cifrado).
    """
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, kind, provider, config, is_active, is_primary_for_kind,
               enabled_at, enabled_by, created_at, updated_at
          FROM tenant_integrations
         WHERE provider    = 'zendesk'
           AND kind        = 'helpdesk'
           AND config->>'subdomain' = $1
           AND deleted_at IS NULL
           AND is_active = TRUE
         LIMIT 2
        """,
        subdomain,
    )
    return _single_integration_or_collision(
        rows, provider="zendesk", lookup="subdomain", value=subdomain
    )


# ============================================================
# Internal Users (Bloque 0, Sub-PR 0.8)
# Corren con bootstrap_connection — sin tenant_scope, igual que get_user_for_auth.
# ============================================================


async def get_internal_user_by_auth_id(
    conn: asyncpg.Connection,
    auth_user_id: UUID,
) -> InternalUser | None:
    """Lookup para auth: dado el sub del JWT, devuelve el perfil interno o None.

    Corre sin tenant_scope — la auth ocurre antes de saber el tenant.
    """
    row = await conn.fetchrow(
        """
        SELECT id, auth_user_id, name, email, role, is_active,
               created_at, updated_at, deleted_at
          FROM internal_users
         WHERE auth_user_id = $1 AND deleted_at IS NULL AND is_active = TRUE
        """,
        auth_user_id,
    )
    return None if row is None else InternalUser(**dict(row))


async def get_internal_user_by_id(
    conn: asyncpg.Connection,
    internal_user_id: UUID,
) -> InternalUser | None:
    row = await conn.fetchrow(
        """
        SELECT id, auth_user_id, name, email, role, is_active,
               created_at, updated_at, deleted_at
          FROM internal_users
         WHERE id = $1 AND deleted_at IS NULL
        """,
        internal_user_id,
    )
    return None if row is None else InternalUser(**dict(row))


async def list_internal_users(conn: asyncpg.Connection) -> list[InternalUser]:
    """Lista todos los usuarios internos activos."""
    rows = await conn.fetch(
        """
        SELECT id, auth_user_id, name, email, role, is_active,
               created_at, updated_at, deleted_at
          FROM internal_users
         WHERE deleted_at IS NULL
         ORDER BY name
        """,
    )
    return [InternalUser(**dict(r)) for r in rows]


async def create_internal_user(
    conn: asyncpg.Connection,
    *,
    auth_user_id: UUID,
    name: str,
    email: str,
    role: InternalRole,
) -> InternalUser:
    row = await conn.fetchrow(
        """
        INSERT INTO internal_users (auth_user_id, name, email, role)
        VALUES ($1, $2, $3, $4::internal_role)
        RETURNING id, auth_user_id, name, email, role, is_active,
                  created_at, updated_at, deleted_at
        """,
        auth_user_id,
        name,
        email,
        role,
    )
    assert row is not None
    return InternalUser(**dict(row))


async def update_internal_user_role(
    conn: asyncpg.Connection,
    *,
    internal_user_id: UUID,
    role: InternalRole,
) -> InternalUser | None:
    row = await conn.fetchrow(
        """
        UPDATE internal_users
           SET role = $2::internal_role, updated_at = NOW()
         WHERE id = $1 AND deleted_at IS NULL
        RETURNING id, auth_user_id, name, email, role, is_active,
                  created_at, updated_at, deleted_at
        """,
        internal_user_id,
        role,
    )
    return None if row is None else InternalUser(**dict(row))


async def soft_delete_internal_user(
    conn: asyncpg.Connection,
    *,
    internal_user_id: UUID,
) -> bool:
    result = await conn.execute(
        """
        UPDATE internal_users
           SET deleted_at = NOW(), is_active = FALSE, updated_at = NOW()
         WHERE id = $1 AND deleted_at IS NULL
        """,
        internal_user_id,
    )
    return result == "UPDATE 1"


async def user_has_permission(
    conn: asyncpg.Connection,
    *,
    internal_user_id: UUID,
    permission: str,
) -> bool:
    """Verifica si el usuario interno tiene un permiso dado según su rol.

    No chequea tenant scope — el caller es responsable de filtrar por asignación
    cuando el rol es 'aide' (scoped). Para super_admin y qa_km basta con esta query.
    """
    row = await conn.fetchrow(
        """
        SELECT 1
          FROM internal_users u
          JOIN role_permissions rp ON rp.role = u.role
         WHERE u.id = $1
           AND rp.permission = $2
           AND u.deleted_at IS NULL
           AND u.is_active = TRUE
         LIMIT 1
        """,
        internal_user_id,
        permission,
    )
    return row is not None


async def get_permissions_for_user(
    conn: asyncpg.Connection,
    *,
    internal_user_id: UUID,
) -> list[str]:
    """Devuelve todos los permisos del usuario según su rol."""
    rows = await conn.fetch(
        """
        SELECT rp.permission
          FROM internal_users u
          JOIN role_permissions rp ON rp.role = u.role
         WHERE u.id = $1
           AND u.deleted_at IS NULL
           AND u.is_active = TRUE
         ORDER BY rp.permission
        """,
        internal_user_id,
    )
    return [r["permission"] for r in rows]


async def list_role_permissions(
    conn: asyncpg.Connection,
    role: InternalRole,
) -> list[RolePermission]:
    """Lista todos los permisos de un rol."""
    rows = await conn.fetch(
        """
        SELECT role, permission
          FROM role_permissions
         WHERE role = $1::internal_role
         ORDER BY permission
        """,
        role,
    )
    return [RolePermission(**dict(r)) for r in rows]


# ─── Tenant Assignments ───────────────────────────────────────────────────────


async def assign_internal_user_to_tenant(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    internal_user_id: UUID,
    role_in_tenant: str,
    assigned_by: UUID | None = None,
) -> TenantAssignment:
    row = await conn.fetchrow(
        """
        INSERT INTO tenant_assignments
               (tenant_id, internal_user_id, role_in_tenant, assigned_by)
        VALUES ($1, $2, $3, $4)
        RETURNING id, tenant_id, internal_user_id, role_in_tenant,
                  assigned_at, assigned_by, unassigned_at
        """,
        tenant_id,
        internal_user_id,
        role_in_tenant,
        assigned_by,
    )
    assert row is not None
    return TenantAssignment(**dict(row))


async def unassign_internal_user_from_tenant(
    conn: asyncpg.Connection,
    *,
    assignment_id: UUID,
) -> bool:
    result = await conn.execute(
        """
        UPDATE tenant_assignments
           SET unassigned_at = NOW()
         WHERE id = $1 AND unassigned_at IS NULL
        """,
        assignment_id,
    )
    return result == "UPDATE 1"


async def list_tenant_assignments_for_user(
    conn: asyncpg.Connection,
    *,
    internal_user_id: UUID,
) -> list[TenantAssignment]:
    """Qué tenants tiene asignados este usuario (activos)."""
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, internal_user_id, role_in_tenant,
               assigned_at, assigned_by, unassigned_at
          FROM tenant_assignments
         WHERE internal_user_id = $1 AND unassigned_at IS NULL
         ORDER BY assigned_at
        """,
        internal_user_id,
    )
    return [TenantAssignment(**dict(r)) for r in rows]


async def list_tenant_assignments_for_tenant(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
) -> list[TenantAssignment]:
    """Qué usuarios internos están asignados a este tenant (activos)."""
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, internal_user_id, role_in_tenant,
               assigned_at, assigned_by, unassigned_at
          FROM tenant_assignments
         WHERE tenant_id = $1 AND unassigned_at IS NULL
         ORDER BY role_in_tenant, assigned_at
        """,
        tenant_id,
    )
    return [TenantAssignment(**dict(r)) for r in rows]


async def is_user_assigned_to_tenant(
    conn: asyncpg.Connection,
    *,
    internal_user_id: UUID,
    tenant_id: UUID,
) -> bool:
    """Verifica si el usuario tiene alguna asignación activa a este tenant."""
    row = await conn.fetchrow(
        """
        SELECT 1
          FROM tenant_assignments
         WHERE internal_user_id = $1
           AND tenant_id = $2
           AND unassigned_at IS NULL
         LIMIT 1
        """,
        internal_user_id,
        tenant_id,
    )
    return row is not None


async def get_integration_by_gorgias_domain(
    conn: asyncpg.Connection,
    *,
    domain: str,
) -> TenantIntegration | None:
    """Busca la integración Gorgias por domain (cross-tenant, para el webhook handler).

    Debe llamarse con bootstrap_connection() porque no tiene tenant_scope.
    El domain vive en config->>'domain' (no está cifrado).
    """
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, kind, provider, config, is_active, is_primary_for_kind,
               enabled_at, enabled_by, created_at, updated_at
          FROM tenant_integrations
         WHERE provider    = 'gorgias'
           AND kind        = 'helpdesk'
           AND config->>'domain' = $1
           AND deleted_at IS NULL
           AND is_active = TRUE
         LIMIT 2
        """,
        domain,
    )
    return _single_integration_or_collision(
        rows, provider="gorgias", lookup="domain", value=domain
    )


# ============================================================
# Simulator (Bloque 0, Sub-PR 0.10)
# ============================================================

# ─── user_profiles ────────────────────────────────────────────────────────────


async def insert_user_profile(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    name: str,
    persona: dict,
    goal: str,
    initial_message: str,
    language: str = "es",
) -> UserProfile:
    row = await conn.fetchrow(
        """
        INSERT INTO user_profiles
            (tenant_id, name, persona, goal, initial_message, language)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, tenant_id, name, persona, goal, initial_message, language,
                  created_at, updated_at, deleted_at
        """,
        tenant_id,
        name,
        persona,
        goal,
        initial_message,
        language,
    )
    return UserProfile(**dict(row))


async def get_user_profile(
    conn: asyncpg.Connection, tenant_id: UUID, profile_id: UUID
) -> UserProfile | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, name, persona, goal, initial_message, language,
               created_at, updated_at, deleted_at
          FROM user_profiles
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
        """,
        tenant_id,
        profile_id,
    )
    return UserProfile(**dict(row)) if row else None


async def get_user_profile_by_name(
    conn: asyncpg.Connection, tenant_id: UUID, name: str
) -> UserProfile | None:
    """Lookup por nombre — usado por el seed para ser idempotente."""
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, name, persona, goal, initial_message, language,
               created_at, updated_at, deleted_at
          FROM user_profiles
         WHERE tenant_id = $1 AND name = $2 AND deleted_at IS NULL
         LIMIT 1
        """,
        tenant_id,
        name,
    )
    return UserProfile(**dict(row)) if row else None


async def update_user_profile(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    profile_id: UUID,
    persona: dict,
    goal: str,
    initial_message: str,
    language: str = "es",
) -> UserProfile | None:
    row = await conn.fetchrow(
        """
        UPDATE user_profiles
           SET persona = $3,
               goal = $4,
               initial_message = $5,
               language = $6,
               updated_at = now()
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
        RETURNING id, tenant_id, name, persona, goal, initial_message, language,
                  created_at, updated_at, deleted_at
        """,
        tenant_id,
        profile_id,
        persona,
        goal,
        initial_message,
        language,
    )
    return UserProfile(**dict(row)) if row else None


# ─── simulation_scenarios ─────────────────────────────────────────────────────


async def insert_simulation_scenario(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    name: str,
    aop_slug: str,
    user_profile_id: UUID,
    expected_outcome: str,
    description: str | None = None,
    mock_fixtures: dict | None = None,
    assertions: dict | None = None,
    max_turns: int = 8,
) -> SimulationScenario:
    row = await conn.fetchrow(
        """
        INSERT INTO simulation_scenarios
            (tenant_id, name, description, aop_slug, user_profile_id, expected_outcome,
             mock_fixtures, assertions, max_turns)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id, tenant_id, name, description, aop_slug, user_profile_id,
                  expected_outcome, mock_fixtures, assertions, max_turns, is_active,
                  created_at, updated_at, deleted_at
        """,
        tenant_id,
        name,
        description,
        aop_slug,
        user_profile_id,
        expected_outcome,
        mock_fixtures or {},
        assertions or {},
        max_turns,
    )
    return SimulationScenario(**dict(row))


async def update_simulation_scenario(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    scenario_id: UUID,
    aop_slug: str,
    expected_outcome: str,
    description: str | None = None,
    mock_fixtures: dict | None = None,
    assertions: dict | None = None,
    max_turns: int = 8,
) -> SimulationScenario | None:
    row = await conn.fetchrow(
        """
        UPDATE simulation_scenarios
           SET description = $3, aop_slug = $4, expected_outcome = $5,
               mock_fixtures = $6, assertions = $7, max_turns = $8,
               updated_at = now()
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
        RETURNING id, tenant_id, name, description, aop_slug, user_profile_id,
                  expected_outcome, mock_fixtures, assertions, max_turns, is_active,
                  created_at, updated_at, deleted_at
        """,
        tenant_id,
        scenario_id,
        description,
        aop_slug,
        expected_outcome,
        mock_fixtures or {},
        assertions or {},
        max_turns,
    )
    return SimulationScenario(**dict(row)) if row else None


async def get_simulation_scenario(
    conn: asyncpg.Connection, tenant_id: UUID, scenario_id: UUID
) -> SimulationScenario | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, name, description, aop_slug, user_profile_id,
               expected_outcome, mock_fixtures, assertions, max_turns, is_active,
               created_at, updated_at, deleted_at
          FROM simulation_scenarios
         WHERE tenant_id = $1 AND id = $2 AND deleted_at IS NULL
        """,
        tenant_id,
        scenario_id,
    )
    return SimulationScenario(**dict(row)) if row else None


async def get_scenario_by_name(
    conn: asyncpg.Connection, tenant_id: UUID, name: str
) -> SimulationScenario | None:
    """Lookup por nombre — usado por el seed para ser idempotente."""
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, name, description, aop_slug, user_profile_id,
               expected_outcome, mock_fixtures, assertions, max_turns, is_active,
               created_at, updated_at, deleted_at
          FROM simulation_scenarios
         WHERE tenant_id = $1 AND name = $2 AND deleted_at IS NULL
         LIMIT 1
        """,
        tenant_id,
        name,
    )
    return SimulationScenario(**dict(row)) if row else None


async def list_simulation_scenarios(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    aop_slug: str | None = None,
    active_only: bool = True,
) -> list[SimulationScenario]:
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, name, description, aop_slug, user_profile_id,
               expected_outcome, mock_fixtures, assertions, max_turns, is_active,
               created_at, updated_at, deleted_at
          FROM simulation_scenarios
         WHERE tenant_id = $1
           AND deleted_at IS NULL
           AND ($2::text IS NULL OR aop_slug = $2)
           AND ($3::boolean IS FALSE OR is_active = TRUE)
         ORDER BY aop_slug, name
        """,
        tenant_id,
        aop_slug,
        active_only,
    )
    return [SimulationScenario(**dict(r)) for r in rows]


# ─── simulation_runs ──────────────────────────────────────────────────────────


async def insert_simulation_run(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    scenario_id: UUID,
    aop_slug: str,
    aop_version: int | None,
    conversation_id: UUID | None,
    batch_id: UUID | None,
    triggered_by: UUID | None,
) -> SimulationRun:
    row = await conn.fetchrow(
        """
        INSERT INTO simulation_runs
            (tenant_id, scenario_id, aop_slug, aop_version, conversation_id,
             batch_id, triggered_by, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'running')
        RETURNING id, tenant_id, scenario_id, aop_slug, aop_version, conversation_id,
                  batch_id, status, termination_reason, turns_count, transcript,
                  judge_eval, assertions_results, assertions_passed, assertions_total,
                  triggered_by, tokens_simulator, tokens_agent, tokens_judge,
                  cost_cents, started_at, completed_at
        """,
        tenant_id,
        scenario_id,
        aop_slug,
        aop_version,
        conversation_id,
        batch_id,
        triggered_by,
    )
    return SimulationRun(**dict(row))


async def finalize_simulation_run(
    conn: asyncpg.Connection,
    run_id: UUID,
    tenant_id: UUID,
    *,
    status: SimulationRunStatus,
    termination_reason: TerminationReason | None,
    turns_count: int,
    transcript: list[dict],
    judge_eval: dict | None,
    assertions_results: list[dict],
    assertions_passed: int,
    assertions_total: int,
    tokens_simulator: int,
    tokens_agent: int,
    tokens_judge: int,
    cost_cents: float,
) -> None:
    await conn.execute(
        """
        UPDATE simulation_runs
           SET status             = $3,
               termination_reason = $4,
               turns_count        = $5,
               transcript         = $6,
               judge_eval         = $7,
               assertions_results = $8,
               assertions_passed  = $9,
               assertions_total   = $10,
               tokens_simulator   = $11,
               tokens_agent       = $12,
               tokens_judge       = $13,
               cost_cents         = $14,
               completed_at       = NOW(),
               updated_at         = NOW()
         WHERE id = $1 AND tenant_id = $2
        """,
        run_id,
        tenant_id,
        status,
        termination_reason,
        turns_count,
        transcript,
        judge_eval,
        assertions_results,
        assertions_passed,
        assertions_total,
        tokens_simulator,
        tokens_agent,
        tokens_judge,
        cost_cents,
    )


async def get_simulation_run(
    conn: asyncpg.Connection, tenant_id: UUID, run_id: UUID
) -> SimulationRun | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, scenario_id, aop_slug, aop_version, conversation_id,
               batch_id, status, termination_reason, turns_count, transcript,
               judge_eval, assertions_results, assertions_passed, assertions_total,
               triggered_by, tokens_simulator, tokens_agent, tokens_judge,
               cost_cents, started_at, completed_at
          FROM simulation_runs
         WHERE tenant_id = $1 AND id = $2
        """,
        tenant_id,
        run_id,
    )
    return SimulationRun(**dict(row)) if row else None


async def list_runs_for_scenario(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    scenario_id: UUID,
    *,
    limit: int = 50,
) -> list[SimulationRun]:
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, scenario_id, aop_slug, aop_version, conversation_id,
               batch_id, status, termination_reason, turns_count, transcript,
               judge_eval, assertions_results, assertions_passed, assertions_total,
               triggered_by, tokens_simulator, tokens_agent, tokens_judge,
               cost_cents, started_at, completed_at
          FROM simulation_runs
         WHERE tenant_id = $1 AND scenario_id = $2
         ORDER BY started_at DESC
         LIMIT $3
        """,
        tenant_id,
        scenario_id,
        limit,
    )
    return [SimulationRun(**dict(r)) for r in rows]


async def list_runs_for_batch(
    conn: asyncpg.Connection, tenant_id: UUID, batch_id: UUID
) -> list[SimulationRun]:
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, scenario_id, aop_slug, aop_version, conversation_id,
               batch_id, status, termination_reason, turns_count, transcript,
               judge_eval, assertions_results, assertions_passed, assertions_total,
               triggered_by, tokens_simulator, tokens_agent, tokens_judge,
               cost_cents, started_at, completed_at
          FROM simulation_runs
         WHERE tenant_id = $1 AND batch_id = $2
         ORDER BY started_at ASC
        """,
        tenant_id,
        batch_id,
    )
    return [SimulationRun(**dict(r)) for r in rows]


async def get_tenant_sim_cost_cents_today(
    conn: asyncpg.Connection, tenant_id: UUID
) -> float:
    """Suma cost_cents de runs terminados del tenant en las últimas 24h. Para el cost cap."""
    row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(cost_cents), 0) AS total
          FROM simulation_runs
         WHERE tenant_id = $1
           AND started_at >= NOW() - INTERVAL '1 day'
           AND status IN ('passed', 'partial', 'failed', 'errored')
        """,
        tenant_id,
    )
    return float(row["total"]) if row else 0.0


async def get_global_sim_cost_cents_today(conn: asyncpg.Connection) -> float:
    """Suma cost_cents de todos los runs terminados en las últimas 24h. Para el cap global."""
    row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(cost_cents), 0) AS total
          FROM simulation_runs
         WHERE started_at >= NOW() - INTERVAL '1 day'
           AND status IN ('passed', 'partial', 'failed', 'errored')
        """
    )
    return float(row["total"]) if row else 0.0


# ============================================================
# Tenant Playbook (Bloque 1, Sub-PR 1.1)
# ============================================================


async def get_tenant_playbook(
    conn: asyncpg.Connection, tenant_id: UUID
) -> TenantPlaybook | None:
    row = await conn.fetchrow(
        "SELECT * FROM tenant_playbook WHERE tenant_id = $1",
        tenant_id,
    )
    return TenantPlaybook(**dict(row)) if row else None


async def upsert_tenant_playbook(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    brand_voice: str = "",
    product_overview: str = "",
    policies: str = "",
    escalation_notes: str = "",
    agent_instructions: str = "",
    edited_by: UUID | None = None,
) -> TenantPlaybook:
    row = await conn.fetchrow(
        """
        INSERT INTO tenant_playbook
          (tenant_id, brand_voice, product_overview, policies,
           escalation_notes, agent_instructions, last_edited_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (tenant_id) DO UPDATE SET
          brand_voice        = EXCLUDED.brand_voice,
          product_overview   = EXCLUDED.product_overview,
          policies           = EXCLUDED.policies,
          escalation_notes   = EXCLUDED.escalation_notes,
          agent_instructions = EXCLUDED.agent_instructions,
          last_edited_by     = EXCLUDED.last_edited_by,
          version            = tenant_playbook.version + 1
        RETURNING *
        """,
        tenant_id,
        brand_voice,
        product_overview,
        policies,
        escalation_notes,
        agent_instructions,
        edited_by,
    )
    return TenantPlaybook(**dict(row))


async def update_tenant_playbook_section(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    section: str,
    content: str,
    edited_by: UUID | None = None,
) -> TenantPlaybook | None:
    """Actualiza una sola sección del playbook. `section` debe ser una columna válida."""
    allowed = {
        "brand_voice",
        "product_overview",
        "policies",
        "escalation_notes",
        "agent_instructions",
    }
    if section not in allowed:
        raise ValueError(f"Invalid playbook section: {section!r}. Allowed: {allowed}")
    row = await conn.fetchrow(
        f"""
        UPDATE tenant_playbook
           SET {section} = $2,
               last_edited_by = $3,
               version = version + 1
         WHERE tenant_id = $1
         RETURNING *
        """,  # noqa: S608 — section validated against allowlist above
        tenant_id,
        content,
        edited_by,
    )
    return TenantPlaybook(**dict(row)) if row else None


# ============================================================
# Tenant Facts (Bloque 1, Sub-PR 1.2)
# ============================================================


async def get_tenant_facts(
    conn: asyncpg.Connection, tenant_id: UUID
) -> TenantFacts | None:
    row = await conn.fetchrow(
        "SELECT * FROM tenant_facts WHERE tenant_id = $1",
        tenant_id,
    )
    if not row:
        return None
    d = dict(row)
    # asyncpg devuelve JSONB como str cuando no hay codec registrado
    if isinstance(d.get("data"), str):
        import json as _json
        d["data"] = _json.loads(d["data"])
    return TenantFacts(**d)


async def upsert_tenant_facts(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    data: dict,
    edited_by: UUID | None = None,
) -> TenantFacts:
    row = await conn.fetchrow(
        """
        INSERT INTO tenant_facts (tenant_id, data, last_edited_by)
        VALUES ($1, $2::jsonb, $3)
        ON CONFLICT (tenant_id) DO UPDATE SET
          data           = EXCLUDED.data,
          last_edited_by = EXCLUDED.last_edited_by,
          version        = tenant_facts.version + 1
        RETURNING *
        """,
        tenant_id,
        data,  # el codec del pool serializa a jsonb (no json.dumps manual)
        edited_by,
    )
    return TenantFacts(**dict(row))


# ============================================================
# Tenant Onboarding (Bloque 1, Sub-PR 1.3)
# ============================================================


def _tenant_onboarding_from_row(row: asyncpg.Record) -> TenantOnboarding:
    d = dict(row)
    for key in ("completed_steps", "step_data"):
        if isinstance(d.get(key), str):
            d[key] = json.loads(d[key])
    return TenantOnboarding(**d)


async def get_tenant_onboarding(
    conn: asyncpg.Connection, tenant_id: UUID
) -> TenantOnboarding | None:
    row = await conn.fetchrow(
        "SELECT * FROM tenant_onboarding WHERE tenant_id = $1",
        tenant_id,
    )
    return _tenant_onboarding_from_row(row) if row else None


async def upsert_tenant_onboarding(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    current_step: int,
    completed_steps: list[int],
    step_data: dict[str, Any],
    edited_by: UUID | None = None,
) -> TenantOnboarding:
    # NO json.dumps() aquí: el pool registra un type codec para jsonb que
    # llama json.dumps automáticamente (ver apps/api/db/client.py:_init_connection).
    # Si encodamos manualmente, asyncpg lo encoda DE NUEVO y termina guardando
    # un JSON string "[1]" en lugar de un array [1], violando el check
    # constraint jsonb_typeof(completed_steps) = 'array'.
    row = await conn.fetchrow(
        """
        INSERT INTO tenant_onboarding
          (tenant_id, current_step, completed_steps, step_data, last_edited_by)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (tenant_id) DO UPDATE SET
          current_step    = EXCLUDED.current_step,
          completed_steps = EXCLUDED.completed_steps,
          step_data       = EXCLUDED.step_data,
          last_edited_by  = EXCLUDED.last_edited_by
        RETURNING *
        """,
        tenant_id,
        current_step,
        completed_steps,
        step_data,
        edited_by,
    )
    return _tenant_onboarding_from_row(row)


async def submit_tenant_onboarding(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    edited_by: UUID | None = None,
) -> TenantOnboarding:
    row = await conn.fetchrow(
        """
        INSERT INTO tenant_onboarding
          (tenant_id, current_step, completed_steps, step_data,
           submitted_at, last_edited_by)
        VALUES ($1, 9, '[1,2,3,4,5,6,7,8,9]'::jsonb, '{}'::jsonb, NOW(), $2)
        ON CONFLICT (tenant_id) DO UPDATE SET
          current_step    = 9,
          completed_steps = '[1,2,3,4,5,6,7,8,9]'::jsonb,
          submitted_at    = COALESCE(tenant_onboarding.submitted_at, NOW()),
          last_edited_by  = EXCLUDED.last_edited_by
        RETURNING *
        """,
        tenant_id,
        edited_by,
    )
    return _tenant_onboarding_from_row(row)


async def compute_onboarding_checklist(
    conn: asyncpg.Connection,
    tenant_id: UUID,
) -> OnboardingChecklist:
    """Evalúa las cuatro condiciones que gatean discovery → building.

    'KB con contenido' = ≥1 submission no borrada; el CHECK de la tabla ya
    garantiza que cada submission tiene contenido o URL.
    """
    row = await conn.fetchrow(
        """
        SELECT
          COALESCE(
            (SELECT submitted_at IS NOT NULL
               FROM tenant_onboarding WHERE tenant_id = $1),
            FALSE
          ) AS onboarding_submitted,
          EXISTS(
            SELECT 1 FROM tenant_integrations
             WHERE tenant_id = $1 AND kind = 'commerce'
               AND is_active AND deleted_at IS NULL
          ) AS has_commerce,
          EXISTS(
            SELECT 1 FROM tenant_integrations
             WHERE tenant_id = $1 AND kind = 'helpdesk'
               AND is_active AND deleted_at IS NULL
          ) AS has_helpdesk,
          EXISTS(
            SELECT 1 FROM tenant_knowledge_submissions
             WHERE tenant_id = $1 AND deleted_at IS NULL
          ) AS has_knowledge
        """,
        tenant_id,
    )
    return OnboardingChecklist(
        onboarding_submitted=row["onboarding_submitted"],
        has_commerce_integration=row["has_commerce"],
        has_helpdesk_integration=row["has_helpdesk"],
        has_knowledge=row["has_knowledge"],
    )


async def update_tenant_lifecycle_state(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    state: str,
) -> Tenant:
    row = await conn.fetchrow(
        """
        UPDATE tenants
           SET agent_lifecycle_state = $2::agent_lifecycle_state
         WHERE id = $1 AND deleted_at IS NULL
         RETURNING id, slug, name, status, agent_lifecycle_state
        """,
        tenant_id,
        state,
    )
    return Tenant(**dict(row))


# ============================================================
# Tenant Knowledge Submissions (Bloque 1, Sub-PR 1.4)
# ============================================================


def _tenant_knowledge_submission_from_row(
    row: asyncpg.Record,
) -> TenantKnowledgeSubmission:
    d = dict(row)
    if isinstance(d.get("metadata"), str):
        d["metadata"] = json.loads(d["metadata"])
    return TenantKnowledgeSubmission(**d)


async def list_tenant_knowledge_submissions(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    status: TenantKnowledgeSubmissionStatus | None = None,
) -> list[TenantKnowledgeSubmission]:
    rows = await conn.fetch(
        """
        SELECT *
          FROM tenant_knowledge_submissions
         WHERE tenant_id = $1
           AND deleted_at IS NULL
           AND ($2::tenant_knowledge_submission_status IS NULL OR status = $2)
         ORDER BY created_at DESC
        """,
        tenant_id,
        status,
    )
    return [_tenant_knowledge_submission_from_row(r) for r in rows]


async def get_tenant_knowledge_submission(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    submission_id: UUID,
) -> TenantKnowledgeSubmission | None:
    row = await conn.fetchrow(
        """
        SELECT *
          FROM tenant_knowledge_submissions
         WHERE tenant_id = $1
           AND id = $2
           AND deleted_at IS NULL
        """,
        tenant_id,
        submission_id,
    )
    return _tenant_knowledge_submission_from_row(row) if row else None


async def create_tenant_knowledge_submission(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    title: str,
    source_type: TenantKnowledgeSourceType,
    source_url: str | None = None,
    original_filename: str | None = None,
    content: str = "",
    notes: str | None = None,
    metadata: dict[str, Any] | None = None,
    submitted_by: UUID | None = None,
) -> TenantKnowledgeSubmission:
    row = await conn.fetchrow(
        """
        INSERT INTO tenant_knowledge_submissions
          (tenant_id, title, source_type, source_url, original_filename,
           content, notes, metadata, submitted_by)
        VALUES ($1, $2, $3::tenant_knowledge_source_type, $4, $5, $6, $7, $8::jsonb, $9)
        RETURNING *
        """,
        tenant_id,
        title,
        source_type,
        source_url,
        original_filename,
        content,
        notes,
        metadata or {},  # el codec del pool serializa a jsonb (no json.dumps manual)
        submitted_by,
    )
    return _tenant_knowledge_submission_from_row(row)


async def reject_tenant_knowledge_submission(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    submission_id: UUID,
    *,
    reviewed_by: UUID,
    review_note: str | None = None,
) -> TenantKnowledgeSubmission | None:
    row = await conn.fetchrow(
        """
        UPDATE tenant_knowledge_submissions
           SET status = 'rejected'::tenant_knowledge_submission_status,
               reviewed_by = $3,
               reviewed_at = NOW(),
               review_note = $4
         WHERE tenant_id = $1
           AND id = $2
           AND status = 'pending_review'::tenant_knowledge_submission_status
           AND deleted_at IS NULL
        RETURNING *
        """,
        tenant_id,
        submission_id,
        reviewed_by,
        review_note,
    )
    return _tenant_knowledge_submission_from_row(row) if row else None


async def approve_tenant_knowledge_submission_with_document(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    submission_id: UUID,
    *,
    reviewed_by: UUID,
    review_note: str | None,
    chunks: list[tuple[str, list[float]]],
) -> TenantKnowledgeSubmission | None:
    row = await conn.fetchrow(
        """
        SELECT *
          FROM tenant_knowledge_submissions
         WHERE tenant_id = $1
           AND id = $2
           AND deleted_at IS NULL
         FOR UPDATE
        """,
        tenant_id,
        submission_id,
    )
    if row is None:
        return None
    submission = _tenant_knowledge_submission_from_row(row)
    if submission.status != "pending_review":
        return None

    document_id = await create_knowledge_document_with_chunks(
        conn,
        tenant_id,
        title=submission.title,
        source=submission.source_url or submission.original_filename or submission.source_type,
        content=submission.content,
        metadata={
            **submission.metadata,
            "source_submission_id": str(submission.id),
            "source_type": submission.source_type,
            "reviewed_by": str(reviewed_by),
        },
        chunks=chunks,
    )
    updated = await conn.fetchrow(
        """
        UPDATE tenant_knowledge_submissions
           SET status = 'approved'::tenant_knowledge_submission_status,
               reviewed_by = $3,
               reviewed_at = NOW(),
               review_note = $4,
               processed_document_id = $5
         WHERE tenant_id = $1
           AND id = $2
        RETURNING *
        """,
        tenant_id,
        submission_id,
        reviewed_by,
        review_note,
        document_id,
    )
    return _tenant_knowledge_submission_from_row(updated)


# ============================================================
# Weekly Reports (Bloque 1, Sub-PR 1.5)
# ============================================================


def _weekly_report_from_row(row: asyncpg.Record) -> WeeklyReport:
    d = dict(row)
    for key in ("week_start", "week_end"):
        value = d.get(key)
        if hasattr(value, "isoformat"):
            d[key] = value.isoformat()
    if isinstance(d.get("metrics"), str):
        d["metrics"] = json.loads(d["metrics"])
    return WeeklyReport(**d)


def _build_weekly_report_narrative(metrics: dict[str, Any]) -> str:
    volume = metrics.get("volume", {})
    cost = metrics.get("cost", {})
    resolution_rate = metrics.get("resolution_rate", 0.0)
    escalation_rate = metrics.get("escalation_rate", 0.0)
    top_intents = metrics.get("top_intents", [])
    escalation_drivers = metrics.get("escalation_drivers", [])

    top_intent_label = "sin intents suficientes"
    if top_intents:
        top = top_intents[0]
        top_intent_label = f"{top.get('intent', 'desconocido')} ({top.get('count', 0)})"

    driver_label = "sin drivers destacados"
    if escalation_drivers:
        driver = escalation_drivers[0]
        driver_label = f"{driver.get('reason', 'Sin razon')} ({driver.get('count', 0)})"

    return (
        "Resumen de la semana\n\n"
        f"- Conversaciones recibidas: {volume.get('conversations', 0)}.\n"
        f"- Mensajes procesados: {volume.get('messages', 0)}.\n"
        f"- Resolution rate: {resolution_rate:.1f}%.\n"
        f"- Escalation rate: {escalation_rate:.1f}%.\n"
        f"- Principal intent detectado: {top_intent_label}.\n"
        f"- Principal driver de escalacion: {driver_label}.\n"
        f"- Coste LLM estimado: ${float(cost.get('usd', 0.0)):.4f}.\n\n"
        "Notas de Auyan\n\n"
        "Editar esta seccion antes de enviar al cliente."
    )


async def build_weekly_report_metrics(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    week_start: str,
    week_end: str,
) -> dict[str, Any]:
    """Calcula los agregados base para el reporte semanal del tenant."""
    metrics = await conn.fetchval(
        """
        WITH bounds AS (
          SELECT $2::date AS week_start, $3::date AS week_end
        ),
        conversation_counts AS (
          SELECT
            COUNT(*)::int AS total,
            COUNT(*) FILTER (WHERE status IN ('resolved', 'closed'))::int AS resolved,
            COUNT(*) FILTER (WHERE status = 'escalated')::int AS escalated
          FROM conversations c, bounds b
          WHERE c.tenant_id = $1
            AND c.deleted_at IS NULL
            AND c.is_simulation = FALSE
            AND c.created_at >= b.week_start
            AND c.created_at < b.week_end + INTERVAL '1 day'
        ),
        message_counts AS (
          SELECT COUNT(*)::int AS total
          FROM messages m, bounds b
          WHERE m.tenant_id = $1
            AND m.deleted_at IS NULL
            AND m.created_at >= b.week_start
            AND m.created_at < b.week_end + INTERVAL '1 day'
        ),
        usage_counts AS (
          SELECT
            COALESCE(SUM(tokens_in), 0)::int AS tokens_in,
            COALESCE(SUM(tokens_out), 0)::int AS tokens_out,
            COALESCE(SUM(cost_usd), 0)::float AS cost_usd,
            COALESCE(SUM(request_count), 0)::int AS request_count
          FROM tenant_usage_daily u, bounds b
          WHERE u.tenant_id = $1
            AND u.deleted_at IS NULL
            AND u.date >= b.week_start
            AND u.date <= b.week_end
        ),
        escalation_driver_counts AS (
          SELECT e.reason, COUNT(*)::int AS count
          FROM escalations e, bounds b
          WHERE e.tenant_id = $1
            AND e.created_at >= b.week_start
            AND e.created_at < b.week_end + INTERVAL '1 day'
          GROUP BY e.reason
          ORDER BY count DESC, e.reason ASC
          LIMIT 5
        ),
        intent_counts AS (
          SELECT i.primary_slug, COUNT(*)::int AS count
          FROM intent_classifier_runs i, bounds b
          WHERE i.tenant_id = $1
            AND i.created_at >= b.week_start
            AND i.created_at < b.week_end + INTERVAL '1 day'
          GROUP BY i.primary_slug
          ORDER BY count DESC, i.primary_slug ASC
          LIMIT 5
        ),
        escalation_drivers AS (
          SELECT COALESCE(
            jsonb_agg(jsonb_build_object('reason', reason, 'count', count)),
            '[]'::jsonb
          ) AS items
          FROM escalation_driver_counts
        ),
        top_intents AS (
          SELECT COALESCE(
            jsonb_agg(jsonb_build_object('intent', primary_slug, 'count', count)),
            '[]'::jsonb
          ) AS items
          FROM intent_counts
        )
        SELECT jsonb_build_object(
          'week_start', $2::date::text,
          'week_end', $3::date::text,
          'volume', jsonb_build_object(
            'conversations', cc.total,
            'messages', mc.total
          ),
          'resolution_rate',
            CASE
              WHEN cc.total = 0 THEN 0
              ELSE ROUND((cc.resolved::numeric / cc.total) * 100, 1)
            END,
          'escalation_rate',
            CASE
              WHEN cc.total = 0 THEN 0
              ELSE ROUND((cc.escalated::numeric / cc.total) * 100, 1)
            END,
          'escalation_drivers', ed.items,
          'top_intents', ti.items,
          'cost', jsonb_build_object(
            'usd', uc.cost_usd,
            'tokens_in', uc.tokens_in,
            'tokens_out', uc.tokens_out,
            'request_count', uc.request_count
          )
        )
        FROM conversation_counts cc,
             message_counts mc,
             usage_counts uc,
             escalation_drivers ed,
             top_intents ti
        """,
        tenant_id,
        week_start,
        week_end,
    )
    if isinstance(metrics, str):
        return json.loads(metrics)
    return dict(metrics or {})


async def list_weekly_reports(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    status: WeeklyReportStatus | None = None,
) -> list[WeeklyReport]:
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, week_start::text, week_end::text, status, subject,
               recipient_email, metrics, narrative, created_by, approved_by,
               approved_at, sent_by, sent_at, postmark_message_id, send_error,
               created_at, updated_at
          FROM weekly_reports
         WHERE tenant_id = $1
           AND deleted_at IS NULL
           AND ($2::weekly_report_status IS NULL OR status = $2)
         ORDER BY week_start DESC, created_at DESC
        """,
        tenant_id,
        status,
    )
    return [_weekly_report_from_row(r) for r in rows]


async def get_weekly_report(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    report_id: UUID,
) -> WeeklyReport | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, week_start::text, week_end::text, status, subject,
               recipient_email, metrics, narrative, created_by, approved_by,
               approved_at, sent_by, sent_at, postmark_message_id, send_error,
               created_at, updated_at
          FROM weekly_reports
         WHERE tenant_id = $1
           AND id = $2
           AND deleted_at IS NULL
        """,
        tenant_id,
        report_id,
    )
    return _weekly_report_from_row(row) if row else None


async def create_or_refresh_weekly_report_draft(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    week_start: str,
    week_end: str,
    created_by: UUID | None,
    recipient_email: str | None = None,
) -> WeeklyReport:
    metrics = await build_weekly_report_metrics(
        conn,
        tenant_id,
        week_start=week_start,
        week_end=week_end,
    )
    subject = f"Reporte semanal Auyan: {week_start} a {week_end}"
    narrative = _build_weekly_report_narrative(metrics)
    row = await conn.fetchrow(
        """
        INSERT INTO weekly_reports
          (tenant_id, week_start, week_end, status, subject, recipient_email,
           metrics, narrative, created_by)
        VALUES ($1, $2::date, $3::date, 'draft'::weekly_report_status, $4, $5, $6::jsonb, $7, $8)
        ON CONFLICT (tenant_id, week_start)
        DO UPDATE SET
          week_end = CASE
            WHEN weekly_reports.status = 'draft'::weekly_report_status THEN EXCLUDED.week_end
            ELSE weekly_reports.week_end
          END,
          subject = CASE
            WHEN weekly_reports.status = 'draft'::weekly_report_status THEN EXCLUDED.subject
            ELSE weekly_reports.subject
          END,
          recipient_email = CASE
            WHEN weekly_reports.status = 'draft'::weekly_report_status THEN EXCLUDED.recipient_email
            ELSE weekly_reports.recipient_email
          END,
          metrics = CASE
            WHEN weekly_reports.status = 'draft'::weekly_report_status THEN EXCLUDED.metrics
            ELSE weekly_reports.metrics
          END,
          narrative = CASE
            WHEN weekly_reports.status = 'draft'::weekly_report_status THEN EXCLUDED.narrative
            ELSE weekly_reports.narrative
          END
        RETURNING id, tenant_id, week_start::text, week_end::text, status, subject,
                  recipient_email, metrics, narrative, created_by, approved_by,
                  approved_at, sent_by, sent_at, postmark_message_id, send_error,
                  created_at, updated_at
        """,
        tenant_id,
        week_start,
        week_end,
        subject,
        recipient_email,
        metrics,  # el codec del pool serializa a jsonb (no json.dumps manual)
        narrative,
        created_by,
    )
    assert row is not None
    return _weekly_report_from_row(row)


async def update_weekly_report_draft(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    report_id: UUID,
    *,
    subject: str,
    narrative: str,
    recipient_email: str | None,
) -> WeeklyReport | None:
    row = await conn.fetchrow(
        """
        UPDATE weekly_reports
           SET subject = $3,
               narrative = $4,
               recipient_email = $5
         WHERE tenant_id = $1
           AND id = $2
           AND status = 'draft'::weekly_report_status
           AND deleted_at IS NULL
        RETURNING id, tenant_id, week_start::text, week_end::text, status, subject,
                  recipient_email, metrics, narrative, created_by, approved_by,
                  approved_at, sent_by, sent_at, postmark_message_id, send_error,
                  created_at, updated_at
        """,
        tenant_id,
        report_id,
        subject,
        narrative,
        recipient_email,
    )
    return _weekly_report_from_row(row) if row else None


async def submit_weekly_report_for_review(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    report_id: UUID,
) -> WeeklyReport | None:
    row = await conn.fetchrow(
        """
        UPDATE weekly_reports
           SET status = 'pending_review'::weekly_report_status
         WHERE tenant_id = $1
           AND id = $2
           AND status = 'draft'::weekly_report_status
           AND deleted_at IS NULL
        RETURNING id, tenant_id, week_start::text, week_end::text, status, subject,
                  recipient_email, metrics, narrative, created_by, approved_by,
                  approved_at, sent_by, sent_at, postmark_message_id, send_error,
                  created_at, updated_at
        """,
        tenant_id,
        report_id,
    )
    return _weekly_report_from_row(row) if row else None


async def approve_weekly_report(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    report_id: UUID,
    *,
    approved_by: UUID,
) -> WeeklyReport | None:
    row = await conn.fetchrow(
        """
        UPDATE weekly_reports
           SET status = 'approved'::weekly_report_status,
               approved_by = $3,
               approved_at = NOW()
         WHERE tenant_id = $1
           AND id = $2
           AND status = 'pending_review'::weekly_report_status
           AND deleted_at IS NULL
        RETURNING id, tenant_id, week_start::text, week_end::text, status, subject,
                  recipient_email, metrics, narrative, created_by, approved_by,
                  approved_at, sent_by, sent_at, postmark_message_id, send_error,
                  created_at, updated_at
        """,
        tenant_id,
        report_id,
        approved_by,
    )
    return _weekly_report_from_row(row) if row else None


async def mark_weekly_report_sent(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    report_id: UUID,
    *,
    sent_by: UUID,
    postmark_message_id: str | None,
) -> WeeklyReport | None:
    row = await conn.fetchrow(
        """
        UPDATE weekly_reports
           SET status = 'sent'::weekly_report_status,
               sent_by = $3,
               sent_at = NOW(),
               postmark_message_id = $4,
               send_error = NULL
         WHERE tenant_id = $1
           AND id = $2
           AND status = 'approved'::weekly_report_status
           AND deleted_at IS NULL
        RETURNING id, tenant_id, week_start::text, week_end::text, status, subject,
                  recipient_email, metrics, narrative, created_by, approved_by,
                  approved_at, sent_by, sent_at, postmark_message_id, send_error,
                  created_at, updated_at
        """,
        tenant_id,
        report_id,
        sent_by,
        postmark_message_id,
    )
    return _weekly_report_from_row(row) if row else None


async def mark_weekly_report_send_failed(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    report_id: UUID,
    *,
    send_error: str,
) -> WeeklyReport | None:
    row = await conn.fetchrow(
        """
        UPDATE weekly_reports
           SET send_error = $3
         WHERE tenant_id = $1
           AND id = $2
           AND status = 'approved'::weekly_report_status
           AND deleted_at IS NULL
        RETURNING id, tenant_id, week_start::text, week_end::text, status, subject,
                  recipient_email, metrics, narrative, created_by, approved_by,
                  approved_at, sent_by, sent_at, postmark_message_id, send_error,
                  created_at, updated_at
        """,
        tenant_id,
        report_id,
        send_error,
    )
    return _weekly_report_from_row(row) if row else None


# ============================================================
# Outbound Email (Bloque 1, Sub-PR 1.9)
# ============================================================


def _outbound_email_template_from_row(row: asyncpg.Record) -> OutboundEmailTemplate:
    data = dict(row)
    if isinstance(data.get("variables"), str):
        data["variables"] = json.loads(data["variables"])
    return OutboundEmailTemplate(**data)


def _outbound_email_job_from_row(row: asyncpg.Record) -> OutboundEmailJob:
    data = dict(row)
    if isinstance(data.get("payload"), str):
        data["payload"] = json.loads(data["payload"])
    return OutboundEmailJob(**data)


async def list_outbound_email_templates(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    include_inactive: bool = False,
) -> list[OutboundEmailTemplate]:
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, key, name, subject_template, text_body_template,
               html_body_template, variables, is_active, version, created_by,
               updated_by, created_at, updated_at
          FROM outbound_email_templates
         WHERE tenant_id = $1
           AND deleted_at IS NULL
           AND ($2::boolean OR is_active = TRUE)
         ORDER BY is_active DESC, key ASC
        """,
        tenant_id,
        include_inactive,
    )
    return [_outbound_email_template_from_row(r) for r in rows]


async def get_outbound_email_template(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    template_id: UUID,
) -> OutboundEmailTemplate | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, key, name, subject_template, text_body_template,
               html_body_template, variables, is_active, version, created_by,
               updated_by, created_at, updated_at
          FROM outbound_email_templates
         WHERE tenant_id = $1
           AND id = $2
           AND deleted_at IS NULL
        """,
        tenant_id,
        template_id,
    )
    return _outbound_email_template_from_row(row) if row else None


async def create_outbound_email_template(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    key: str,
    name: str,
    subject_template: str,
    text_body_template: str,
    html_body_template: str | None,
    variables: list[str],
    created_by: UUID | None,
    is_active: bool = True,
) -> OutboundEmailTemplate:
    row = await conn.fetchrow(
        """
        INSERT INTO outbound_email_templates
          (tenant_id, key, name, subject_template, text_body_template,
           html_body_template, variables, is_active, created_by, updated_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $9)
        RETURNING id, tenant_id, key, name, subject_template, text_body_template,
                  html_body_template, variables, is_active, version, created_by,
                  updated_by, created_at, updated_at
        """,
        tenant_id,
        key,
        name,
        subject_template,
        text_body_template,
        html_body_template,
        variables,  # el codec del pool serializa a jsonb (no json.dumps manual)
        is_active,
        created_by,
    )
    assert row is not None
    return _outbound_email_template_from_row(row)


async def update_outbound_email_template(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    template_id: UUID,
    *,
    name: str,
    subject_template: str,
    text_body_template: str,
    html_body_template: str | None,
    variables: list[str],
    is_active: bool,
    updated_by: UUID | None,
) -> OutboundEmailTemplate | None:
    row = await conn.fetchrow(
        """
        UPDATE outbound_email_templates
           SET name = $3,
               subject_template = $4,
               text_body_template = $5,
               html_body_template = $6,
               variables = $7::jsonb,
               is_active = $8,
               version = version + 1,
               updated_by = $9
         WHERE tenant_id = $1
           AND id = $2
           AND deleted_at IS NULL
        RETURNING id, tenant_id, key, name, subject_template, text_body_template,
                  html_body_template, variables, is_active, version, created_by,
                  updated_by, created_at, updated_at
        """,
        tenant_id,
        template_id,
        name,
        subject_template,
        text_body_template,
        html_body_template,
        variables,  # el codec del pool serializa a jsonb (no json.dumps manual)
        is_active,
        updated_by,
    )
    return _outbound_email_template_from_row(row) if row else None


async def list_outbound_email_jobs(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    status: OutboundEmailJobStatus | None = None,
    limit: int = 50,
) -> list[OutboundEmailJob]:
    rows = await conn.fetch(
        """
        SELECT id, tenant_id, template_id, recipient_email, subject, text_body,
               html_body, tag, payload, status, attempts, max_attempts,
               next_attempt_at, last_attempt_at, sent_at, postmark_message_id,
               error, requested_by, idempotency_key, created_at, updated_at
          FROM outbound_email_jobs
         WHERE tenant_id = $1
           AND deleted_at IS NULL
           AND ($2::outbound_email_job_status IS NULL OR status = $2)
         ORDER BY created_at DESC
         LIMIT $3
        """,
        tenant_id,
        status,
        limit,
    )
    return [_outbound_email_job_from_row(r) for r in rows]


async def get_outbound_email_job(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    job_id: UUID,
) -> OutboundEmailJob | None:
    row = await conn.fetchrow(
        """
        SELECT id, tenant_id, template_id, recipient_email, subject, text_body,
               html_body, tag, payload, status, attempts, max_attempts,
               next_attempt_at, last_attempt_at, sent_at, postmark_message_id,
               error, requested_by, idempotency_key, created_at, updated_at
          FROM outbound_email_jobs
         WHERE tenant_id = $1
           AND id = $2
           AND deleted_at IS NULL
        """,
        tenant_id,
        job_id,
    )
    return _outbound_email_job_from_row(row) if row else None


async def enqueue_outbound_email_job(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    recipient_email: str,
    subject: str,
    text_body: str,
    html_body: str | None,
    template_id: UUID | None,
    tag: str | None,
    payload: dict[str, Any],
    requested_by: UUID | None,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
) -> OutboundEmailJob:
    row = await conn.fetchrow(
        """
        INSERT INTO outbound_email_jobs
          (tenant_id, template_id, recipient_email, subject, text_body, html_body,
           tag, payload, max_attempts, requested_by, idempotency_key)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, $11)
        ON CONFLICT (tenant_id, idempotency_key)
          WHERE idempotency_key IS NOT NULL AND deleted_at IS NULL
        DO UPDATE SET updated_at = outbound_email_jobs.updated_at
        RETURNING id, tenant_id, template_id, recipient_email, subject, text_body,
                  html_body, tag, payload, status, attempts, max_attempts,
                  next_attempt_at, last_attempt_at, sent_at, postmark_message_id,
                  error, requested_by, idempotency_key, created_at, updated_at
        """,
        tenant_id,
        template_id,
        recipient_email,
        subject,
        text_body,
        html_body,
        tag,
        payload,  # el codec del pool serializa a jsonb (no json.dumps manual)
        max_attempts,
        requested_by,
        idempotency_key,
    )
    assert row is not None
    return _outbound_email_job_from_row(row)


async def claim_due_outbound_email_jobs(
    conn: asyncpg.Connection,
    *,
    limit: int = 25,
) -> list[OutboundEmailJob]:
    rows = await conn.fetch(
        """
        WITH due AS (
          SELECT id
            FROM outbound_email_jobs
           WHERE deleted_at IS NULL
             AND status IN (
               'queued'::outbound_email_job_status,
               'failed'::outbound_email_job_status
             )
             AND attempts < max_attempts
             AND next_attempt_at <= NOW()
           ORDER BY next_attempt_at ASC, created_at ASC
           LIMIT $1
           FOR UPDATE SKIP LOCKED
        )
        UPDATE outbound_email_jobs j
           SET status = 'sending'::outbound_email_job_status,
               attempts = j.attempts + 1,
               last_attempt_at = NOW(),
               error = NULL
          FROM due
         WHERE j.id = due.id
        RETURNING j.id, j.tenant_id, j.template_id, j.recipient_email, j.subject,
                  j.text_body, j.html_body, j.tag, j.payload, j.status, j.attempts,
                  j.max_attempts, j.next_attempt_at, j.last_attempt_at, j.sent_at,
                  j.postmark_message_id, j.error, j.requested_by, j.idempotency_key,
                  j.created_at, j.updated_at
        """,
        limit,
    )
    return [_outbound_email_job_from_row(r) for r in rows]


async def mark_outbound_email_job_sent(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    job_id: UUID,
    *,
    postmark_message_id: str | None,
) -> OutboundEmailJob | None:
    row = await conn.fetchrow(
        """
        UPDATE outbound_email_jobs
           SET status = 'sent'::outbound_email_job_status,
               sent_at = NOW(),
               postmark_message_id = $3,
               error = NULL
         WHERE tenant_id = $1
           AND id = $2
           AND status = 'sending'::outbound_email_job_status
           AND deleted_at IS NULL
        RETURNING id, tenant_id, template_id, recipient_email, subject, text_body,
                  html_body, tag, payload, status, attempts, max_attempts,
                  next_attempt_at, last_attempt_at, sent_at, postmark_message_id,
                  error, requested_by, idempotency_key, created_at, updated_at
        """,
        tenant_id,
        job_id,
        postmark_message_id,
    )
    return _outbound_email_job_from_row(row) if row else None


async def mark_outbound_email_job_failed(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    job_id: UUID,
    *,
    error: str,
    retry_delay_seconds: int,
) -> OutboundEmailJob | None:
    row = await conn.fetchrow(
        """
        UPDATE outbound_email_jobs
           SET status = CASE
                 WHEN attempts >= max_attempts THEN 'failed'::outbound_email_job_status
                 ELSE 'queued'::outbound_email_job_status
               END,
               next_attempt_at = CASE
                 WHEN attempts >= max_attempts THEN next_attempt_at
                 ELSE NOW() + ($3::int * INTERVAL '1 second')
               END,
               error = $4
         WHERE tenant_id = $1
           AND id = $2
           AND status = 'sending'::outbound_email_job_status
           AND deleted_at IS NULL
        RETURNING id, tenant_id, template_id, recipient_email, subject, text_body,
                  html_body, tag, payload, status, attempts, max_attempts,
                  next_attempt_at, last_attempt_at, sent_at, postmark_message_id,
                  error, requested_by, idempotency_key, created_at, updated_at
        """,
        tenant_id,
        job_id,
        retry_delay_seconds,
        error[:1_000],
    )
    return _outbound_email_job_from_row(row) if row else None


# ─── Billing por resolución (Bloque 2) ──────────────────────────────────────────


async def insert_resolution_event(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID
) -> ResolutionEvent:
    """Registra una resolución cobrable (append-only). Lo llama el nodo respond
    cuando el agente marca la conversación resolved."""
    row = await conn.fetchrow(
        """
        INSERT INTO resolution_events (tenant_id, conversation_id)
        VALUES ($1, $2)
        RETURNING id, tenant_id, conversation_id, resolved_at, reverted_at, created_at
        """,
        tenant_id,
        conversation_id,
    )
    assert row is not None
    return ResolutionEvent(**dict(row))


async def mark_resolution_event_reverted(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID
) -> bool:
    """Marca como revertido el evento abierto más reciente de la conversación cuando
    el cliente reabre el mismo thread. El conteo de billing decide si descuenta según
    la ventana de reapertura. No-op si no hay evento abierto. Retorna True si marcó."""
    result = await conn.execute(
        """
        UPDATE resolution_events
           SET reverted_at = now()
         WHERE id = (
             SELECT id FROM resolution_events
              WHERE tenant_id = $1 AND conversation_id = $2 AND reverted_at IS NULL
              ORDER BY resolved_at DESC
              LIMIT 1
         )
        """,
        tenant_id,
        conversation_id,
    )
    return int(result.split()[-1]) > 0


async def count_billable_resolutions(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    period_start: datetime,
    period_end: datetime,
    reopen_window: timedelta,
) -> int:
    """Cuenta las resoluciones cobrables del periodo [start, end).

    Una resolución cuenta si su resolved_at cae en el periodo y NO fue revertida, o
    fue revertida DESPUÉS de la ventana de reapertura (duró resuelta lo suficiente →
    resolución legítima). Si se revirtió DENTRO de la ventana no cuenta (mismo tema,
    no estaba resuelto del todo) — docs/billing-engine.md §2.3."""
    count = await conn.fetchval(
        """
        SELECT count(*)
          FROM resolution_events
         WHERE tenant_id = $1
           AND resolved_at >= $2
           AND resolved_at < $3
           AND (reverted_at IS NULL OR reverted_at - resolved_at > $4)
        """,
        tenant_id,
        period_start,
        period_end,
        reopen_window,
    )
    return int(count or 0)


async def get_billing_subscription(
    conn: asyncpg.Connection, tenant_id: UUID
) -> BillingSubscription | None:
    row = await conn.fetchrow(
        """
        SELECT tenant_id, tier, floor_cents, included_resolutions, overage_cents,
               currency, reopen_window_days, period_anchor_day, status,
               stripe_customer_id, stripe_subscription_id, created_at, updated_at
          FROM billing_subscriptions
         WHERE tenant_id = $1
        """,
        tenant_id,
    )
    return BillingSubscription(**dict(row)) if row else None


async def upsert_billing_subscription(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    tier: BillingTier,
    floor_cents: int,
    included_resolutions: int,
    overage_cents: int,
    currency: str = "EUR",
    reopen_window_days: int = 7,
    period_anchor_day: int = 1,
    status: str = "active",
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
) -> BillingSubscription:
    """Crea o actualiza la suscripción del tenant. Idempotente por tenant_id."""
    row = await conn.fetchrow(
        """
        INSERT INTO billing_subscriptions (
            tenant_id, tier, floor_cents, included_resolutions, overage_cents,
            currency, reopen_window_days, period_anchor_day, status,
            stripe_customer_id, stripe_subscription_id
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (tenant_id) DO UPDATE SET
            tier = EXCLUDED.tier,
            floor_cents = EXCLUDED.floor_cents,
            included_resolutions = EXCLUDED.included_resolutions,
            overage_cents = EXCLUDED.overage_cents,
            currency = EXCLUDED.currency,
            reopen_window_days = EXCLUDED.reopen_window_days,
            period_anchor_day = EXCLUDED.period_anchor_day,
            status = EXCLUDED.status,
            stripe_customer_id = EXCLUDED.stripe_customer_id,
            stripe_subscription_id = EXCLUDED.stripe_subscription_id
        RETURNING tenant_id, tier, floor_cents, included_resolutions, overage_cents,
                  currency, reopen_window_days, period_anchor_day, status,
                  stripe_customer_id, stripe_subscription_id, created_at, updated_at
        """,
        tenant_id,
        tier,
        floor_cents,
        included_resolutions,
        overage_cents,
        currency,
        reopen_window_days,
        period_anchor_day,
        status,
        stripe_customer_id,
        stripe_subscription_id,
    )
    assert row is not None
    return BillingSubscription(**dict(row))
