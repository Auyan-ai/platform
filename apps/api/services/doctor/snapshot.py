"""Foto del tenant que usa el doctor: integraciones (credenciales descifradas) y actividad.

Se carga en una sola pasada por la base y después la conexión se suelta: los checks en
vivo (HTTP a Zendesk, Zernio, Shopify…) no mantienen una transacción abierta.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apps.api.db.queries import (
    get_integration_credentials_encrypted,
    get_tenant_by_id,
    list_integrations_for_tenant,
)
from apps.api.services.integrations_crypto import decrypt_credentials

if TYPE_CHECKING:
    import asyncpg

STUCK_JOB_MINUTES = 10
INBOUND_LOOKBACK_DAYS = 30


@dataclass
class IntegrationSnapshot:
    id: UUID
    kind: str
    provider: str
    is_active: bool
    is_primary: bool
    config: dict[str, Any]
    credentials: dict[str, Any] | None
    credentials_error: str | None = None


@dataclass
class ActivitySnapshot:
    last_inbound_by_channel: dict[str, datetime] = field(default_factory=dict)
    failed_jobs_24h: int = 0
    last_job_error: str | None = None
    stuck_jobs: int = 0


@dataclass
class TenantSnapshot:
    tenant_id: UUID
    slug: str
    integrations: list[IntegrationSnapshot]
    activity: ActivitySnapshot

    def find(self, kind: str, provider: str) -> IntegrationSnapshot | None:
        return next(
            (i for i in self.integrations if i.kind == kind and i.provider == provider), None
        )

    def primary(self, kind: str) -> IntegrationSnapshot | None:
        return next(
            (i for i in self.integrations if i.kind == kind and i.is_primary and i.is_active),
            None,
        )

    def of_kind(self, kind: str) -> list[IntegrationSnapshot]:
        return [i for i in self.integrations if i.kind == kind]


class TenantNotFoundError(LookupError):
    pass


async def load_tenant_snapshot(
    conn: asyncpg.Connection, tenant_id: UUID, crypto_key: bytes
) -> TenantSnapshot:
    """`conn` ya dentro del scope del tenant. Un fallo al descifrar no aborta: queda en
    `credentials_error` y el doctor lo reporta como check fallido."""
    tenant = await get_tenant_by_id(conn, tenant_id)
    if tenant is None:
        raise TenantNotFoundError(str(tenant_id))

    integrations: list[IntegrationSnapshot] = []
    for integration in await list_integrations_for_tenant(conn, tenant_id=tenant_id):
        credentials: dict[str, Any] | None = None
        error: str | None = None
        encrypted = await get_integration_credentials_encrypted(
            conn, tenant_id=tenant_id, integration_id=integration.id
        )
        if encrypted is None:
            error = "sin credenciales guardadas"
        else:
            try:
                credentials = json.loads(decrypt_credentials(encrypted, crypto_key).decode())
            except Exception as exc:  # se reporta como check fallido
                error = f"no se pudieron descifrar ({type(exc).__name__})"
        integrations.append(
            IntegrationSnapshot(
                id=integration.id,
                kind=integration.kind,
                provider=integration.provider,
                is_active=integration.is_active,
                is_primary=integration.is_primary_for_kind,
                config=dict(integration.config or {}),
                credentials=credentials,
                credentials_error=error,
            )
        )

    return TenantSnapshot(
        tenant_id=tenant_id,
        slug=tenant.slug,
        integrations=integrations,
        activity=await _load_activity(conn, tenant_id),
    )


async def _load_activity(conn: asyncpg.Connection, tenant_id: UUID) -> ActivitySnapshot:
    rows = await conn.fetch(
        """
        SELECT c.channel::text AS channel, max(m.created_at) AS last_at
          FROM messages m
          JOIN conversations c ON c.id = m.conversation_id
         WHERE m.tenant_id = $1
           AND m.role = 'customer'
           AND m.deleted_at IS NULL
           AND c.is_simulation = false
           AND m.created_at > now() - make_interval(days => $2)
         GROUP BY c.channel
        """,
        tenant_id,
        INBOUND_LOOKBACK_DAYS,
    )
    jobs = await conn.fetchrow(
        """
        SELECT
          count(*) FILTER (
            WHERE status = 'failed' AND finished_at > now() - interval '24 hours'
          ) AS failed_24h,
          count(*) FILTER (
            WHERE (status = 'pending' AND run_after < now() - make_interval(mins => $2))
               OR (status = 'running' AND locked_until < now() - make_interval(mins => $2))
          ) AS stuck,
          (SELECT last_error FROM inbound_jobs
            WHERE tenant_id = $1 AND status = 'failed' AND deleted_at IS NULL
            ORDER BY finished_at DESC NULLS LAST LIMIT 1) AS last_error
          FROM inbound_jobs
         WHERE tenant_id = $1 AND deleted_at IS NULL
        """,
        tenant_id,
        STUCK_JOB_MINUTES,
    )
    return ActivitySnapshot(
        last_inbound_by_channel={r["channel"]: r["last_at"] for r in rows if r["last_at"]},
        failed_jobs_24h=int(jobs["failed_24h"] or 0) if jobs else 0,
        last_job_error=jobs["last_error"] if jobs else None,
        stuck_jobs=int(jobs["stuck"] or 0) if jobs else 0,
    )
