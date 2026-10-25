from __future__ import annotations

import datetime
import logging
from typing import Annotated, Any
from uuid import UUID

from apps.api.core.errors import ConflictError, NotFoundError, ValidationFailed
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id, require_role
from apps.api.db.client import tenant_scope
from apps.api.db.site_ingestions import (
    enqueue_site_ingestion,
    get_active_site_ingestion,
    get_site_ingestion,
)
from apps.api.integrations.demo_catalog import normalize_domain
from apps.api.services.site_ingestion.models import IngestionStatus, Platform
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

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
