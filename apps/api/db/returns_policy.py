"""Versiones de la política de devoluciones y cambios (`tenant_returns_policies`, ADR 0014 §2).

Solo inserciones: guardar crea la versión siguiente, y la vigente es la última sin
`deleted_at`. Llamar siempre dentro de `tenant_scope` del tenant.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class StoredPolicy:
    version: int
    policy: dict[str, Any]
    edited_by_email: str | None
    created_at: datetime


@dataclass(frozen=True)
class PolicyVersion:
    version: int
    edited_by_email: str | None
    created_at: datetime


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
    row = await conn.fetchrow(
        """
        SELECT p.version, p.policy, p.created_at, u.email AS edited_by_email
        FROM tenant_returns_policies p
        LEFT JOIN users u ON u.id = p.edited_by
        WHERE p.tenant_id = $1 AND p.deleted_at IS NULL
        ORDER BY p.version DESC
        LIMIT 1
        """,
        tenant_id,
    )
    if row is None:
        return None
    return StoredPolicy(
        version=row["version"],
        policy=_as_dict(row["policy"]),
        edited_by_email=row["edited_by_email"],
        created_at=row["created_at"],
    )


async def list_returns_policy_versions(
    conn: asyncpg.Connection, tenant_id: UUID, *, limit: int = 20
) -> list[PolicyVersion]:
    rows = await conn.fetch(
        """
        SELECT p.version, p.created_at, u.email AS edited_by_email
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
            version=r["version"], edited_by_email=r["edited_by_email"], created_at=r["created_at"]
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
        SELECT max(version) FILTER (WHERE deleted_at IS NULL) AS current,
               coalesce(max(version), 0) AS highest
        FROM tenant_returns_policies
        WHERE tenant_id = $1
        """,
        tenant_id,
    )
    current: int | None = row["current"]
    if current != expected_version:
        raise StaleVersionError(current)
    # Una versión borrada (soft delete) no libera su número.
    version = int(row["highest"]) + 1
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
