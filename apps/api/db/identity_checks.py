"""Queries de `identity_checks` (ADR 0013 §4 y §9): intentos y grants `guest`.

Nada de emails ni teléfonos en claro: `attempt_key` y `claim_hashes` son HMAC con la sal
del tenant y `contact_masked` solo deja ver iniciales.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

FAILURE_OUTCOMES = ("order_not_found", "contact_mismatch")


@dataclass(frozen=True)
class GuestGrantRow:
    order_id: int
    claim_hashes: tuple[str, ...]
    valid_until: datetime


async def list_active_guest_grants(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID, now: datetime
) -> list[GuestGrantRow]:
    """Grants `guest` vigentes de esta conversación."""
    rows = await conn.fetch(
        """
        SELECT order_id, claim_hashes, valid_until
          FROM identity_checks
         WHERE tenant_id = $1 AND conversation_id = $2
           AND kind = 'guest' AND outcome = 'granted'
           AND valid_until > $3 AND deleted_at IS NULL
         ORDER BY created_at
        """,
        tenant_id,
        conversation_id,
        now,
    )
    return [
        GuestGrantRow(int(r["order_id"]), tuple(r["claim_hashes"]), r["valid_until"]) for r in rows
    ]


async def list_attempt_keys(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID
) -> set[str]:
    """Pares (pedido, contacto) ya probados en la conversación."""
    rows = await conn.fetch(
        """
        SELECT attempt_key
          FROM identity_checks
         WHERE tenant_id = $1 AND conversation_id = $2
           AND kind = 'guest' AND deleted_at IS NULL
        """,
        tenant_id,
        conversation_id,
    )
    return {str(r["attempt_key"]) for r in rows}


async def count_conversation_failures(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID
) -> int:
    value = await conn.fetchval(
        """
        SELECT count(*)
          FROM identity_checks
         WHERE tenant_id = $1 AND conversation_id = $2
           AND kind = 'guest' AND outcome = ANY($3::text[]) AND deleted_at IS NULL
        """,
        tenant_id,
        conversation_id,
        list(FAILURE_OUTCOMES),
    )
    return int(value or 0)


async def tenant_failure_stats(
    conn: asyncpg.Connection, tenant_id: UUID, since: datetime
) -> tuple[int, datetime | None]:
    """(fallos del tenant desde `since`, momento del último). Una consulta indexada."""
    row = await conn.fetchrow(
        """
        SELECT count(*) AS failures, max(created_at) AS latest
          FROM identity_checks
         WHERE tenant_id = $1 AND kind = 'guest'
           AND outcome = ANY($2::text[]) AND created_at > $3 AND deleted_at IS NULL
        """,
        tenant_id,
        list(FAILURE_OUTCOMES),
        since,
    )
    if row is None:
        return 0, None
    return int(row["failures"]), row["latest"]


async def insert_guest_check(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    outcome: str,
    order_id: int | None,
    claim_hashes: list[str],
    attempt_key: str,
    contact_masked: str | None,
    valid_until: datetime | None,
) -> bool:
    """Registra un intento. False si el par ya estaba probado (idempotente)."""
    row = await conn.fetchrow(
        """
        INSERT INTO identity_checks
            (tenant_id, conversation_id, kind, outcome, method, order_id,
             claim_hashes, attempt_key, contact_masked, valid_until)
        VALUES ($1, $2, 'guest', $3, 'order_contact', $4, $5, $6, $7, $8)
        ON CONFLICT (tenant_id, conversation_id, attempt_key) WHERE deleted_at IS NULL
        DO NOTHING
        RETURNING id
        """,
        tenant_id,
        conversation_id,
        outcome,
        order_id,
        claim_hashes,
        attempt_key,
        contact_masked,
        valid_until,
    )
    return row is not None
