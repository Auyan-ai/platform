"""Dispatcher para cola persistente de email outbound.

El dispatcher reclama jobs due de `outbound_email_jobs`, los envía vía
`EmailSender.send_email_now` y persiste éxito o retry con backoff exponencial.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from apps.api.db.queries import (
    claim_due_outbound_email_jobs,
    mark_outbound_email_job_failed,
    mark_outbound_email_job_sent,
)

if TYPE_CHECKING:
    import asyncpg
    from apps.api.db.models import OutboundEmailJob
    from apps.api.services.email_sender import EmailSender


@dataclass(frozen=True)
class OutboundEmailDispatchResult:
    claimed: int
    sent: int
    retry_scheduled: int
    failed: int


def retry_delay_seconds(job: OutboundEmailJob) -> int:
    """Backoff exponencial simple: 60s, 120s, 240s... capped a 1h."""
    return min(3600, 60 * (2 ** max(job.attempts - 1, 0)))


def postmark_message_id(result: dict[str, Any]) -> str | None:
    message_id = result.get("MessageID") or result.get("MessageId")
    return str(message_id) if message_id else None


async def dispatch_due_outbound_emails(
    conn: asyncpg.Connection,
    email_sender: EmailSender,
    *,
    limit: int = 25,
) -> OutboundEmailDispatchResult:
    """Procesa hasta `limit` jobs due y devuelve contadores de resultado."""
    jobs = await claim_due_outbound_email_jobs(conn, limit=limit)
    sent = 0
    retry_scheduled = 0
    failed = 0

    for job in jobs:
        try:
            result = await email_sender.send_email_now(
                to=job.recipient_email,
                subject=job.subject,
                text_body=job.text_body,
                html_body=job.html_body,
                tag=job.tag,
            )
            await mark_outbound_email_job_sent(
                conn,
                job.tenant_id,
                job.id,
                postmark_message_id=postmark_message_id(result),
            )
            sent += 1
        except Exception as exc:
            updated = await mark_outbound_email_job_failed(
                conn,
                job.tenant_id,
                job.id,
                error=str(exc),
                retry_delay_seconds=retry_delay_seconds(job),
            )
            if updated is not None and updated.status == "failed":
                failed += 1
            else:
                retry_scheduled += 1

    return OutboundEmailDispatchResult(
        claimed=len(jobs),
        sent=sent,
        retry_scheduled=retry_scheduled,
        failed=failed,
    )
