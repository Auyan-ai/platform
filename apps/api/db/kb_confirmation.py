"""Confirmación de documentos de la KB traídos de la web de una demo (ADR 0015 §6).

Contrato (`knowledge_base_documents.metadata.confirmation`): `unconfirmed` para los documentos
que una demo aprobó sola, `confirmed` en el resto; sin clave se lee como `confirmed` (documentos
anteriores a este contrato). Llamar siempre dentro de `tenant_scope` del tenant.

`confirm_kb_documents` es el único punto de escritura de la confirmación. La escritura de
`unconfirmed` la hace la autoaprobación de las demos (`services/site_ingestion/auto_approve.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class UnconfirmedDocument:
    id: UUID
    title: str
    source: str | None
    created_at: datetime


async def list_unconfirmed_kb_documents(
    conn: asyncpg.Connection, tenant_id: UUID
) -> list[UnconfirmedDocument]:
    rows = await conn.fetch(
        """
        SELECT d.id, d.title, d.source, d.created_at
          FROM knowledge_base_documents d
         WHERE d.tenant_id = $1 AND d.deleted_at IS NULL
           AND COALESCE(d.metadata->>'confirmation', 'confirmed') = 'unconfirmed'
         ORDER BY d.created_at DESC
        """,
        tenant_id,
    )
    return [UnconfirmedDocument(**dict(r)) for r in rows]


async def count_unconfirmed_kb_documents(conn: asyncpg.Connection, tenant_id: UUID) -> int:
    count = await conn.fetchval(
        """
        SELECT COUNT(*) FROM knowledge_base_documents d
         WHERE d.tenant_id = $1 AND d.deleted_at IS NULL
           AND COALESCE(d.metadata->>'confirmation', 'confirmed') = 'unconfirmed'
        """,
        tenant_id,
    )
    return int(count or 0)


async def confirm_kb_documents(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    document_ids: list[UUID] | None,
    confirmed_by: UUID,
) -> int:
    """Marca como confirmados los documentos sin confirmar del tenant y devuelve cuántos.

    `document_ids=None` confirma todos. Un id de otro tenant, borrado o ya confirmado no
    cuenta: la consulta siempre filtra por `tenant_id`.
    """
    rows = await conn.fetch(
        """
        UPDATE knowledge_base_documents d
           SET metadata = d.metadata || jsonb_build_object(
                 'confirmation', 'confirmed',
                 'confirmed_by', $2::text,
                 'confirmed_at', to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
               )
         WHERE d.tenant_id = $1 AND d.deleted_at IS NULL
           AND COALESCE(d.metadata->>'confirmation', 'confirmed') = 'unconfirmed'
           AND ($3::uuid[] IS NULL OR d.id = ANY($3::uuid[]))
        RETURNING d.id
        """,
        tenant_id,
        str(confirmed_by),
        document_ids,
    )
    return len(rows)
