"""Auto-aprobación del lote de una ingesta de demo (ADR 0015 §5)."""

from __future__ import annotations

import logging
from uuid import UUID

from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.site_ingestions import ClaimedIngestion, list_ingestion_submissions
from apps.api.services.kb_approval import BatchApproval, approve_submissions_batch
from apps.api.services.knowledge_ingestion import Embedder

logger = logging.getLogger(__name__)

DEMO_REVIEW_NOTE = "demo: auto-aprobado"


async def tenant_is_demo(tenant_id: UUID) -> bool:
    async with bootstrap_connection() as conn:
        origin = await conn.fetchval(
            "SELECT origin FROM tenants WHERE id = $1 AND deleted_at IS NULL", tenant_id
        )
    return origin == "demo"


async def auto_approve_if_demo(job: ClaimedIngestion, embedder: Embedder) -> BatchApproval | None:
    """Si la ingesta es de una demo, aprueba todo su lote sin revisor y lo deja `unconfirmed`.

    Los tenants cliente nunca se auto-aprueban: su lote espera la revisión de un super_admin.
    Es idempotente: solo toca lo que sigue pendiente."""
    if not await tenant_is_demo(job.tenant_id):
        return None
    async with tenant_scope(job.tenant_id) as conn:
        submissions = await list_ingestion_submissions(conn, job.tenant_id, job.id)
    result = await approve_submissions_batch(
        tenant_id=job.tenant_id,
        submission_ids=[s.id for s in submissions if s.status == "pending_review"],
        reviewed_by=None,
        review_note=DEMO_REVIEW_NOTE,
        confirmation="unconfirmed",
        embedder=embedder,
    )
    logger.info(
        "demo_ingestion_auto_approved",
        extra={
            "tenant_id": str(job.tenant_id),
            "ingestion_id": str(job.id),
            "approved": len(result.approved),
            "failed": len(result.failures),
        },
    )
    return result
