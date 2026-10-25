from __future__ import annotations

import datetime
import logging
from typing import Annotated, Any
from uuid import UUID

from apps.api.core.config import get_settings
from apps.api.core.errors import ConflictError, NotFoundError, ValidationFailed
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id, require_role
from apps.api.db.client import tenant_scope
from apps.api.db.queries import reject_tenant_knowledge_submission
from apps.api.db.site_ingestions import (
    SiteIngestion,
    enqueue_site_ingestion,
    get_active_site_ingestion,
    get_latest_site_ingestion,
    get_site_ingestion,
    list_ingestion_submissions,
)
from apps.api.integrations.demo_catalog import normalize_domain
from apps.api.services.kb_approval import approve_submissions_batch
from apps.api.services.knowledge_ingestion import make_embedder
from apps.api.services.site_ingestion.models import IngestionStatus, Platform
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/me/site-ingestions", tags=["site-ingestions"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]


class SiteIngestionCreate(BaseModel):
    url: str


class SiteIngestionAccepted(BaseModel):
    id: UUID
    status: IngestionStatus
    root_url: str


class SiteIngestionOut(BaseModel):
    id: UUID
    root_url: str
    platform: Platform | None
    status: IngestionStatus
    attempts: int
    failure_reason: str | None
    stats: dict[str, Any]
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    finished_at: datetime.datetime | None


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SiteIngestionAccepted,
    summary="Encola la ingesta de la web de la tienda",
    dependencies=[Depends(require_role("super_admin"))],
)
async def create_site_ingestion(
    body: SiteIngestionCreate, tenant_id: TenantIdDep, auth: AuthDep, request: Request
) -> SiteIngestionAccepted:
    try:
        root_url = f"https://{normalize_domain(body.url)}"
    except ValueError as exc:
        raise ValidationFailed(
            "La URL de la tienda no es válida.", code="invalid_store_url"
        ) from exc
    async with tenant_scope(tenant_id) as conn:
        ingestion_id = await enqueue_site_ingestion(
            conn, tenant_id=tenant_id, root_url=root_url, requested_by=auth.user_id
        )
        active = None if ingestion_id else await get_active_site_ingestion(conn, tenant_id)
    if ingestion_id is None:
        running = f" ({active.id}, {active.status.value})" if active else ""
        raise ConflictError(
            f"El tenant ya tiene una ingesta en curso{running}.",
            code="site_ingestion_running",
        )
    worker = getattr(request.app.state, "site_ingestion_worker", None)
    if worker is not None:
        worker.notify()
    logger.info(
        "site_ingestion_queued",
        extra={"tenant_id": str(tenant_id), "ingestion_id": str(ingestion_id), "url": root_url},
    )
    return SiteIngestionAccepted(id=ingestion_id, status=IngestionStatus.QUEUED, root_url=root_url)


def _ingestion_out(ingestion: SiteIngestion) -> SiteIngestionOut:
    return SiteIngestionOut(
        id=ingestion.id,
        root_url=ingestion.root_url,
        platform=ingestion.platform,
        status=ingestion.status,
        attempts=ingestion.attempts,
        failure_reason=ingestion.failure_reason,
        stats=ingestion.stats,
        created_at=ingestion.created_at,
        started_at=ingestion.started_at,
        finished_at=ingestion.finished_at,
    )


@router.get(
    "/latest",
    response_model=SiteIngestionOut | None,
    summary="La ingesta más reciente del tenant, o null si no hay ninguna",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def read_latest_site_ingestion(tenant_id: TenantIdDep) -> SiteIngestionOut | None:
    async with tenant_scope(tenant_id) as conn:
        ingestion = await get_latest_site_ingestion(conn, tenant_id)
    return _ingestion_out(ingestion) if ingestion else None


@router.get(
    "/{ingestion_id}",
    response_model=SiteIngestionOut,
    summary="Estado y estadísticas de una ingesta",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def read_site_ingestion(ingestion_id: UUID, tenant_id: TenantIdDep) -> SiteIngestionOut:
    async with tenant_scope(tenant_id) as conn:
        ingestion = await get_site_ingestion(conn, tenant_id, ingestion_id)
    if ingestion is None:
        raise NotFoundError("Ingesta no encontrada.")
    return _ingestion_out(ingestion)


class IngestionSubmissionOut(BaseModel):
    id: UUID
    title: str
    source_url: str | None
    source_key: str | None
    status: str
    kind: str | None
    priority: str | None
    source: str | None
    words: int | None
    duplicate_of: str | None = None
    duplicate_kind: str | None = None
    review_note: str | None


class IngestionApprove(BaseModel):
    exclude_submission_ids: list[UUID] = Field(default_factory=list, max_length=1_000)
    review_note: str | None = Field(default=None, max_length=5_000)


class BatchCounts(BaseModel):
    approved: int
    rejected: int
    skipped: int


class BatchFailure(BaseModel):
    submission_id: UUID
    code: str
    detail: str


class IngestionApproveOut(BaseModel):
    counts: BatchCounts
    failures: list[BatchFailure]


@router.get(
    "/{ingestion_id}/submissions",
    response_model=list[IngestionSubmissionOut],
    summary="Fuentes que leyó una ingesta, con su estado de revisión",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def list_site_ingestion_submissions(
    ingestion_id: UUID, tenant_id: TenantIdDep
) -> list[IngestionSubmissionOut]:
    async with tenant_scope(tenant_id) as conn:
        if await get_site_ingestion(conn, tenant_id, ingestion_id) is None:
            raise NotFoundError("Ingesta no encontrada.")
        rows = await list_ingestion_submissions(conn, tenant_id, ingestion_id)
    return [
        IngestionSubmissionOut(
            id=row.id,
            title=row.title,
            source_url=row.source_url,
            source_key=row.source_key,
            status=row.status,
            kind=row.metadata.get("kind"),
            priority=row.metadata.get("priority"),
            source=row.metadata.get("source"),
            words=row.metadata.get("words"),
            duplicate_of=row.metadata.get("duplicate_of"),
            duplicate_kind=row.metadata.get("duplicate_kind"),
            review_note=row.review_note,
        )
        for row in rows
    ]


@router.post(
    "/{ingestion_id}/approve",
    response_model=IngestionApproveOut,
    summary="Aprueba el lote de una ingesta, menos las fuentes excluidas",
    dependencies=[Depends(require_role("super_admin"))],
)
async def approve_site_ingestion(
    ingestion_id: UUID,
    body: IngestionApprove,
    request: Request,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> IngestionApproveOut:
    deps = getattr(request.app.state, "agent_deps", None)
    openai_client = getattr(deps, "openai", None)
    if openai_client is None:
        raise HTTPException(status_code=503, detail="Cliente OpenAI no inicializado")
    async with tenant_scope(tenant_id) as conn:
        ingestion = await get_site_ingestion(conn, tenant_id, ingestion_id)
        if ingestion is None:
            raise NotFoundError("Ingesta no encontrada.")
        submissions = await list_ingestion_submissions(conn, tenant_id, ingestion_id)
    if ingestion.status is not IngestionStatus.READY:
        raise ConflictError(
            f"La ingesta está en {ingestion.status.value}: espera a que termine.",
            code="site_ingestion_not_ready",
        )
    known = {s.id for s in submissions}
    unknown = set(body.exclude_submission_ids) - known
    if unknown:
        raise ValidationFailed(
            "Hay fuentes excluidas que no son de esta ingesta.", code="unknown_submission"
        )

    excluded = set(body.exclude_submission_ids)
    pending = [s for s in submissions if s.status == "pending_review"]
    to_reject = [s.id for s in pending if s.id in excluded]
    to_approve = [s.id for s in pending if s.id not in excluded]

    rejected = 0
    for submission_id in to_reject:
        async with tenant_scope(tenant_id) as conn:
            done = await reject_tenant_knowledge_submission(
                conn,
                tenant_id,
                submission_id,
                reviewed_by=auth.user_id,
                review_note=body.review_note,
            )
        rejected += done is not None

    result = await approve_submissions_batch(
        tenant_id=tenant_id,
        submission_ids=to_approve,
        reviewed_by=auth.user_id,
        review_note=body.review_note,
        confirmation="confirmed",
        embedder=make_embedder(openai_client, settings=get_settings()),
    )
    skipped = len(submissions) - len(pending) + len(result.skipped) + (len(to_reject) - rejected)
    logger.info(
        "site_ingestion_batch_reviewed",
        extra={
            "tenant_id": str(tenant_id),
            "ingestion_id": str(ingestion_id),
            "approved": len(result.approved),
            "rejected": rejected,
            "failed": len(result.failures),
        },
    )
    return IngestionApproveOut(
        counts=BatchCounts(approved=len(result.approved), rejected=rejected, skipped=skipped),
        failures=[
            BatchFailure(submission_id=f.submission_id, code=f.code.value, detail=f.detail)
            for f in result.failures
        ],
    )
