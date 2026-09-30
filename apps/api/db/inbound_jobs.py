"""Cola duradera de turnos inbound (`inbound_jobs`, #260) + serialización por conversación.

Dos caminos:
- **Intake** (webhook, dentro de su `tenant_scope`): `claim_webhook_idempotency_key` +
  `enqueue_inbound_job` en la MISMA transacción que persiste el mensaje. Si la
  transacción cae, no queda ni key ni job → el reintento del proveedor reprocesa limpio.
- **Worker** (cross-tenant, `bootstrap_connection`): `claim_next_inbound_job` reclama el
  siguiente turno bajo un advisory lock por (tenant_id, conversation_id). Mientras una
  conversación tenga un job `running` con lease vigente, ningún otro worker la toca.

Ráfagas: si el cliente manda varios mensajes antes de que su conversación quede libre,
se procesa solo el más nuevo (su historial ya contiene los anteriores) y los demás
pasan a `superseded` con `superseded_by` → una sola respuesta a toda la ráfaga.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from datetime import datetime

    import asyncpg


@dataclass(frozen=True)
class ClaimedInboundJob:
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    inbound_message_id: UUID
    end_customer_id: UUID
    channel: str
    attempts: int  # incluye el intento actual
    max_attempts: int
    # Mensajes inbound absorbidos por este turno (más viejos primero, sin el propio).
    absorbed_message_ids: tuple[UUID, ...]
    # True si un intento anterior llegó a correr (crash / lease expirado / reintento):
    # el turno puede haber respondido ya → el worker lo verifica antes de re-correr.
    is_retry: bool
    enqueued_at: datetime


async def claim_webhook_idempotency_key(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    key: str,
    request_path: str,
) -> bool:
    """Reclama la key de idempotencia del webhook dentro de la transacción del intake.

    True si es la primera vez; False si ya existe (duplicado). Con `ON CONFLICT` un
    reintento concurrente espera a que la transacción original confirme (o caiga) en
    vez de fallar: no hay estado `in_flight` que pueda quedarse colgado. Se inserta
    ya como `done`: si la transacción confirma, el mensaje quedó persistido y encolado.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO idempotency_keys (tenant_id, key, request_path, status,
                                      response_status, response_body)
        VALUES ($1, $2, $3, 'done', 200, '{"queued": true}'::jsonb)
        ON CONFLICT (tenant_id, key) DO NOTHING
        RETURNING id
        """,
        tenant_id,
        key,
        request_path,
    )
    return row is not None


async def lock_inbound_intake(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    channel: str,
    external_id: str,
    customer_email: str | None,
) -> None:
    """Serializa intakes concurrentes que crearían el mismo cliente o conversación.

    Dos webhooks casi simultáneos del primer mensaje de un ticket hacían ambos
    find → None → INSERT y el segundo chocaba con `uq_end_customers_email` /
    `uq_conversations_external` (500). Con estos locks de transacción el segundo espera
    al primero y encuentra lo que creó. Orden fijo de adquisición → sin deadlocks.
    """
    keys = [f"intake:{tenant_id}:conv:{channel}:{external_id}"]
    if customer_email:
        keys.append(f"intake:{tenant_id}:customer:{customer_email.strip().lower()}")
    for key in sorted(keys):
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))", key)


async def enqueue_inbound_job(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    inbound_message_id: UUID,
    end_customer_id: UUID,
    channel: str,
) -> UUID:
    """Encola el turno del mensaje inbound. Llamar en la transacción que lo persiste."""
    job_id = await conn.fetchval(
        """
        INSERT INTO inbound_jobs (tenant_id, conversation_id, inbound_message_id,
                                  end_customer_id, channel)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        tenant_id,
        conversation_id,
        inbound_message_id,
        end_customer_id,
        channel,
    )
    assert job_id is not None
    return UUID(str(job_id))


async def claim_next_inbound_job(
    conn: asyncpg.Connection,
    *,
    lease_seconds: int,
    scan_limit: int = 20,
) -> ClaimedInboundJob | None:
    """Reclama el siguiente turno listo, o None si no hay ninguno reclamable.

    Por conversación candidata (la más antigua primero):
      1. `pg_try_advisory_xact_lock(tenant:conversation)` — si otro worker la está
         reclamando ahora mismo, se salta (no bloquea).
      2. Si ya hay un job `running` con lease vigente, se salta: el turno sigue vivo.
      3. Se toma el job vivo más NUEVO de la conversación; los más viejos pasan a
         `superseded`. Si el más nuevo está en backoff (`run_after` futuro), se espera.

    El lock es de transacción (compatible con cualquier modo del pooler); la
    exclusión durante el turno la da el estado `running` + `locked_until`.
    """
    async with conn.transaction():
        candidates = await conn.fetch(
            """
            SELECT tenant_id, conversation_id
              FROM inbound_jobs
             WHERE deleted_at IS NULL
               AND ((status = 'pending' AND run_after <= now())
                    OR (status = 'running' AND locked_until < now()))
             GROUP BY tenant_id, conversation_id
             ORDER BY min(created_at)
             LIMIT $1
            """,
            scan_limit,
        )
        for cand in candidates:
            tenant_id: UUID = cand["tenant_id"]
            conversation_id: UUID = cand["conversation_id"]
            locked = await conn.fetchval(
                """
                SELECT pg_try_advisory_xact_lock(
                    hashtextextended($1::uuid::text || ':' || $2::uuid::text, 0))
                """,
                tenant_id,
                conversation_id,
            )
            if not locked:
                continue
            busy = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM inbound_jobs
                     WHERE tenant_id = $1 AND conversation_id = $2 AND deleted_at IS NULL
                       AND status = 'running' AND locked_until >= now()
                )
                """,
                tenant_id,
                conversation_id,
            )
            if busy:
                continue
            live = await conn.fetch(
                """
                SELECT id, inbound_message_id, end_customer_id, channel, status,
                       attempts, max_attempts, created_at, run_after <= now() AS ready
                  FROM inbound_jobs
                 WHERE tenant_id = $1 AND conversation_id = $2 AND deleted_at IS NULL
                   AND status IN ('pending', 'running')
                 ORDER BY created_at DESC, id DESC
                   FOR UPDATE
                """,
                tenant_id,
                conversation_id,
            )
            if not live:
                continue
            target = live[0]
            if target["status"] == "pending" and not target["ready"]:
                continue  # el mensaje más nuevo está en backoff: esperar a que toque
            older = live[1:]
            if older:
                await conn.execute(
                    """
                    UPDATE inbound_jobs
                       SET status = 'superseded', superseded_by = $2,
                           locked_until = NULL, finished_at = now()
                     WHERE id = ANY($1::uuid[])
                    """,
                    [r["id"] for r in older],
                    target["id"],
                )
            await conn.execute(
                """
                UPDATE inbound_jobs
                   SET status = 'running', attempts = attempts + 1,
                       locked_until = now() + make_interval(secs => $2),
                       started_at = coalesce(started_at, now())
                 WHERE id = $1
                """,
                target["id"],
                lease_seconds,
            )
            return ClaimedInboundJob(
                id=target["id"],
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                inbound_message_id=target["inbound_message_id"],
                end_customer_id=target["end_customer_id"],
                channel=target["channel"],
                attempts=target["attempts"] + 1,
                max_attempts=target["max_attempts"],
                absorbed_message_ids=tuple(r["inbound_message_id"] for r in reversed(older)),
                is_retry=target["attempts"] > 0,
                enqueued_at=target["created_at"],
            )
    return None


async def extend_inbound_job_lease(
    conn: asyncpg.Connection, *, job_id: UUID, lease_seconds: int
) -> None:
    """Heartbeat: renueva el lease de un job que sigue corriendo."""
    await conn.execute(
        """
        UPDATE inbound_jobs
           SET locked_until = now() + make_interval(secs => $2)
         WHERE id = $1 AND status = 'running'
        """,
        job_id,
        lease_seconds,
    )


async def release_inbound_job(conn: asyncpg.Connection, *, job_id: UUID) -> None:
    """Devuelve a `pending` un job interrumpido (shutdown de la instancia) para que otro
    worker lo retome ya, sin esperar a que venza el lease. Cuenta como reintento."""
    await conn.execute(
        """
        UPDATE inbound_jobs
           SET status = 'pending', locked_until = NULL, run_after = now()
         WHERE id = $1 AND status = 'running'
        """,
        job_id,
    )


async def complete_inbound_job(conn: asyncpg.Connection, *, job_id: UUID, decision: str) -> None:
    await conn.execute(
        """
        UPDATE inbound_jobs
           SET status = 'done', decision = $2, locked_until = NULL, finished_at = now()
         WHERE id = $1
        """,
        job_id,
        decision,
    )


async def fail_inbound_job(
    conn: asyncpg.Connection,
    *,
    job_id: UUID,
    error: str,
    retry_in_seconds: int | None,
) -> str:
    """Registra un fallo. Con `retry_in_seconds` vuelve a `pending` con backoff; sin él
    (o reintentos agotados) queda `failed`. Devuelve el estado resultante."""
    status = await conn.fetchval(
        """
        UPDATE inbound_jobs
           SET status = CASE WHEN $3::int IS NOT NULL AND attempts < max_attempts
                             THEN 'pending' ELSE 'failed' END,
               run_after = CASE WHEN $3::int IS NOT NULL
                                THEN now() + make_interval(secs => $3::int) ELSE run_after END,
               finished_at = CASE WHEN $3::int IS NOT NULL AND attempts < max_attempts
                                  THEN NULL ELSE now() END,
               locked_until = NULL,
               last_error = left($2, 2000)
         WHERE id = $1
        RETURNING status
        """,
        job_id,
        error,
        retry_in_seconds,
    )
    return str(status)


async def get_inbound_message_contents(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    message_ids: list[UUID],
) -> list[str]:
    """Contenido de los mensajes inbound dados, en orden cronológico."""
    rows = await conn.fetch(
        """
        SELECT content
          FROM messages
         WHERE tenant_id = $1 AND conversation_id = $2 AND id = ANY($3::uuid[])
           AND deleted_at IS NULL
         ORDER BY created_at ASC
        """,
        tenant_id,
        conversation_id,
        message_ids,
    )
    return [str(r["content"]) for r in rows]


async def inbound_already_answered(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    inbound_message_id: UUID,
) -> bool:
    """True si el agente ya respondió a este inbound (respuesta enlazada vía metadata)."""
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM messages
                 WHERE tenant_id = $1 AND conversation_id = $2 AND deleted_at IS NULL
                   AND role = 'agent_ai'
                   AND metadata->>'inbound_message_id' = $3::uuid::text
            )
            """,
            tenant_id,
            conversation_id,
            inbound_message_id,
        )
    )
