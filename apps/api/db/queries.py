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

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.db.models import (
    AgentReasoningEvent,
    AopVersion,
    AopWithContent,
    AopWorkspace,
    ChannelType,
    Conversation,
    ConversationStatus,
    EndCustomer,
    Escalation,
    EscalationStatus,
    IntentClassifierRun,
    KnowledgeChunk,
    Message,
    MessageDirection,
    MessageRole,
    ReasoningEventType,
    ReasoningPhase,
    ReasoningStatus,
    Tenant,
    TenantConfiguration,
    UserRole,
)

if TYPE_CHECKING:
    import asyncpg


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
               subject, status, assigned_user_id, last_message_at, created_at
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
               subject, status, assigned_user_id, last_message_at, created_at
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
                  subject, status, assigned_user_id, last_message_at, created_at
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
               subject, status, assigned_user_id, last_message_at, created_at
          FROM conversations
         WHERE tenant_id = $1 AND deleted_at IS NULL
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


async def list_all_tenants(conn: asyncpg.Connection) -> list[Tenant]:
    """Super-admin: listar todos los tenants activos sin tenant_scope."""
    rows = await conn.fetch(
        """
        SELECT id, slug, name, status
          FROM tenants
         WHERE deleted_at IS NULL
         ORDER BY name
        """,
    )
    return [Tenant(**dict(r)) for r in rows]


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


# ============================================================
# AOPs — Agent Operating Procedures
# ============================================================


def _row_to_aop_with_content(row: asyncpg.Record) -> AopWithContent:
    data = dict(row)
    data["yaml_frontmatter"] = dict(data["yaml_frontmatter"])
    return AopWithContent(**data)


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
    import json

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
        VALUES ($1, $2, 1, $3::jsonb, $4, $5, $6)
        """,
        aop_id,
        tenant_id,
        json.dumps(yaml_frontmatter),
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
    import json

    version_row = await conn.fetchrow(
        """
        INSERT INTO aop_versions
               (aop_id, tenant_id, version, yaml_frontmatter, body_markdown, raw_source, created_by)
        SELECT $1, $2, current_version + 1, $3::jsonb, $4, $5, $6
          FROM aops
         WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL
        RETURNING id, aop_id, tenant_id, version, yaml_frontmatter, body_markdown,
                  raw_source, created_by, created_at
        """,
        aop_id,
        tenant_id,
        json.dumps(yaml_frontmatter),
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
    import json

    row = await conn.fetchrow(
        """
        INSERT INTO agent_reasoning_events
               (tenant_id, conversation_id, phase, event_type, label, detail, status, seq)
        VALUES (
            $1, $2, $3, $4, $5, $6::jsonb, $7,
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
        json.dumps(detail) if detail is not None else None,
        status,
    )
    assert row is not None
    data = dict(row)
    data["detail"] = dict(data["detail"]) if data["detail"] is not None else None
    return AgentReasoningEvent(**data)


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
