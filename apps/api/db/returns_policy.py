"""Versiones de la política de devoluciones y cambios (`tenant_returns_policies`, ADR 0014 §2).

Solo inserciones: guardar crea la versión siguiente, y la vigente es la última sin
`deleted_at`. Llamar siempre dentro de `tenant_scope` del tenant.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredPolicy:
    version: int
    policy: dict[str, Any]
    edited_by_email: str | None
    created_at: datetime
    edited_by_role: str | None = None


@dataclass(frozen=True)
class PolicyVersion:
    version: int
    edited_by_email: str | None
    created_at: datetime
    edited_by_role: str | None = None


class StaleVersionError(Exception):
    """Otra persona guardó una versión después de la que se editaba."""

    def __init__(self, current: int | None) -> None:
        super().__init__(f"current_version={current}")
        self.current = current


def _as_dict(value: Any) -> dict[str, Any]:
    # asyncpg devuelve JSONB como str cuando no hay codec registrado.
    return json.loads(value) if isinstance(value, str) else dict(value)


async def get_current_returns_policy(
    conn: asyncpg.Connection, tenant_id: UUID
) -> StoredPolicy | None:
    """La última versión, o None si no hay o si está borrada (soft delete).

    Borrar la última versión deja al tenant sin política (fail-closed): nunca reactiva en
    silencio la anterior. Para volver a una versión vieja, se guarda de nuevo.
    """
    row = await conn.fetchrow(
        """
        SELECT p.version, p.policy, p.created_at, p.deleted_at,
               u.email AS edited_by_email, u.role::text AS edited_by_role
        FROM tenant_returns_policies p
        LEFT JOIN users u ON u.id = p.edited_by
        WHERE p.tenant_id = $1
        ORDER BY p.version DESC
        LIMIT 1
        """,
        tenant_id,
    )
    if row is None or row["deleted_at"] is not None:
        return None
    return StoredPolicy(
        version=row["version"],
        policy=_as_dict(row["policy"]),
        edited_by_email=row["edited_by_email"],
        created_at=row["created_at"],
        edited_by_role=row["edited_by_role"],
    )


async def load_current_returns_policy(
    conn: asyncpg.Connection, tenant_id: UUID
) -> StoredPolicy | None:
    """La política vigente para el turno del agente, o None si no se puede leer.

    Va en un savepoint: si la lectura falla (tabla sin migrar, error de la base), la
    transacción del turno sigue viva y el agente trata la política como no configurada
    (rechaza y escala), en vez de fallar todos los turnos de todos los tenants.
    """
    try:
        async with conn.transaction():
            return await get_current_returns_policy(conn, tenant_id)
    except asyncpg.PostgresError:
        logger.error(
            "returns_policy_read_failed", extra={"tenant_id": str(tenant_id)}, exc_info=True
        )
        return None


async def list_returns_policy_versions(
    conn: asyncpg.Connection, tenant_id: UUID, *, limit: int = 20
) -> list[PolicyVersion]:
    rows = await conn.fetch(
        """
        SELECT p.version, p.created_at, u.email AS edited_by_email,
               u.role::text AS edited_by_role
        FROM tenant_returns_policies p
        LEFT JOIN users u ON u.id = p.edited_by
        WHERE p.tenant_id = $1 AND p.deleted_at IS NULL
        ORDER BY p.version DESC
        LIMIT $2
        """,
        tenant_id,
        limit,
    )
    return [
        PolicyVersion(
            version=r["version"],
            edited_by_email=r["edited_by_email"],
            created_at=r["created_at"],
            edited_by_role=r["edited_by_role"],
        )
        for r in rows
    ]


async def insert_returns_policy_version(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    policy: dict[str, Any],
    schema_version: int,
    expected_version: int | None,
    edited_by: UUID | None,
) -> int:
    """Inserta la versión siguiente a `expected_version` (None = primera) y la devuelve.

    Lanza `StaleVersionError` si la vigente no es `expected_version`. El índice único
    `(tenant_id, version)` cubre la carrera entre la lectura y el insert.
    """
    row = await conn.fetchrow(
        """
        SELECT version AS highest, deleted_at
        FROM tenant_returns_policies
        WHERE tenant_id = $1
        ORDER BY version DESC
        LIMIT 1
        """,
        tenant_id,
    )
    highest = int(row["highest"]) if row else 0
    # Igual que `get_current_returns_policy`: la última versión borrada es "sin política".
    current: int | None = row["highest"] if row and row["deleted_at"] is None else None
    if current != expected_version:
        raise StaleVersionError(current)
    # Una versión borrada (soft delete) no libera su número.
    version = highest + 1
    try:
        await conn.execute(
            """
            INSERT INTO tenant_returns_policies
              (tenant_id, version, schema_version, policy, edited_by)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            """,
            tenant_id,
            version,
            schema_version,
            policy,
            edited_by,
        )
    except asyncpg.UniqueViolationError as exc:
        raise StaleVersionError(version) from exc
    return version
