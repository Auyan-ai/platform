"""Endpoints de tenant — perfil y configuración del tenant autenticado."""

from __future__ import annotations

import datetime
import json
import logging
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from apps.api.core.config import get_settings
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id, require_role
from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.models import IntegrationGroup, OnboardingChecklist
from apps.api.db.queries import (
    approve_weekly_report,
    compute_onboarding_checklist,
    create_or_refresh_weekly_report_draft,
    create_outbound_email_template,
    create_tenant_knowledge_submission,
    enqueue_outbound_email_job,
    get_internal_user_by_auth_id,
    get_outbound_email_job,
    get_outbound_email_template,
    get_tenant_configuration,
    get_tenant_facts,
    get_tenant_onboarding,
    get_tenant_playbook,
    get_tenant_usage_range,
    get_weekly_report,
    list_admin_review_queue,
    list_all_tenants,
    list_integrations_for_tenant,
    list_knowledge_documents,
    list_outbound_email_jobs,
    list_outbound_email_templates,
    list_tenant_knowledge_submissions,
    list_weekly_reports,
    mark_weekly_report_send_failed,
    mark_weekly_report_sent,
    merge_tenant_facts,
    merge_tenant_playbook,
    reject_tenant_knowledge_submission,
    soft_delete_knowledge_document,
    submit_tenant_onboarding,
    submit_weekly_report_for_review,
    update_outbound_email_template,
    update_tenant_lifecycle_state,
    update_weekly_report_draft,
    upsert_integration,
    upsert_tenant_facts,
    upsert_tenant_onboarding,
    upsert_tenant_playbook,
)
from apps.api.integrations.chatwoot import ChatwootClient
from apps.api.integrations.shopify import (
    ShopifyClient,
    exchange_client_credentials,
)
from apps.api.services.demo_tenants import (
    DemoSlugExhaustedError,
    create_demo_tenant,
    start_demo_ingestion,
)
from apps.api.services.doctor import DoctorReport, TenantNotFoundError, run_tenant_doctor
from apps.api.services.integrations_crypto import (
    encrypt_credentials,
    get_integration_crypto_key,
)
from apps.api.services.kb_approval import FailureCode, approve_submissions_batch
from apps.api.services.knowledge_ingestion import make_embedder
from apps.api.services.tenant_provisioning import (
    ProvisionRequest,
    SlugTakenError,
    SupabaseAdminError,
    provision_tenant,
)
from apps.api.services.tenants import (
    evaluate_and_advance_lifecycle,
    get_tenant,
    get_tenant_config,
    get_tenant_insights,
    get_tenant_metrics,
    list_tenant_integration_groups,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants", tags=["tenants"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]
SettingsDep = Annotated[object, Depends(get_settings)]


# ----------------------------------------------------------------
# Response schemas
# ----------------------------------------------------------------


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    status: str
    agent_lifecycle_state: str = "initial"
    plan_tier: Literal["founding", "standard", "trial"] = "founding"
    origin: Literal["client", "demo"] = "client"
    demo_expires_at: datetime.datetime | None = None
    demo_source_url: str | None = None


class CreateDemoRequest(BaseModel):
    url: str = Field(..., min_length=3, max_length=2048)


class CreateTenantRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., pattern=r"^[a-z][a-z0-9-]{1,49}$")
    plan_tier: Literal["founding", "standard", "trial"] = "founding"
    tenant_admin_email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
    tenant_admin_name: str = Field(..., min_length=1, max_length=200)


class CreateTenantResponse(BaseModel):
    tenant: TenantResponse
    tenant_admin_user_id: UUID
    invite_sent: bool


class AdminReviewQueueItem(BaseModel):
    tenant_id: UUID
    tenant_name: str
    tenant_status: str
    agent_lifecycle_state: str
    kb_pending: int
    weekly_reports_pending: int
    approvals_pending: int
    proposals_pending: int
    total_pending: int


class TenantConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    agent_model: str
    escalation_threshold: float
    integrations: list[IntegrationGroup]
    branding: dict
    extra: dict


class ConversationStatusCounts(BaseModel):
    open: int
    pending: int
    escalated: int
    resolved: int
    closed: int


class TenantResolutionSeriesPoint(BaseModel):
    bucket: str
    conversations: int
    resolved: int
    escalated: int
    resolution_rate: float
    escalation_rate: float


class TenantResolutionWindow(BaseModel):
    key: Literal["30d", "7d", "24h"]
    label: str
    granularity: Literal["day", "hour"]
    total: int
    resolved: int
    escalated: int
    resolution_rate: float
    escalation_rate: float
    points: list[TenantResolutionSeriesPoint]


class TenantMetricsResponse(BaseModel):
    total: int
    by_status: ConversationStatusCounts
    resolution_rate: float
    escalation_rate: float
    resolution_windows: list[TenantResolutionWindow]


class TenantInsightTimelinePoint(BaseModel):
    date: str
    conversations: int


class TenantInsightBreakdownItem(BaseModel):
    label: str
    count: int


class TenantInsightsResponse(BaseModel):
    days: int
    timeline: list[TenantInsightTimelinePoint]
    top_intents: list[TenantInsightBreakdownItem]
    by_channel: list[TenantInsightBreakdownItem]
    by_status: list[TenantInsightBreakdownItem]


class DailyUsage(BaseModel):
    date: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    request_count: int


class TenantUsageResponse(BaseModel):
    today: DailyUsage | None
    budget_usd_daily: float
    budget_used_pct: float
    days: int
    history: list[DailyUsage]


class TenantPlaybookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    brand_voice: str = ""
    product_overview: str = ""
    policies: str = ""
    escalation_notes: str = ""
    agent_instructions: str = ""
    version: int = 1
    last_edited_by: UUID | None = None
    updated_at: datetime.datetime | None = None


class TenantPlaybookUpdate(BaseModel):
    brand_voice: str = Field(default="", max_length=20_000)
    product_overview: str = Field(default="", max_length=20_000)
    policies: str = Field(default="", max_length=20_000)
    escalation_notes: str = Field(default="", max_length=20_000)
    agent_instructions: str = Field(default="", max_length=20_000)


class TenantFactsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    data: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    last_edited_by: UUID | None = None
    updated_at: datetime.datetime | None = None


class TenantFactsUpdate(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class TenantOnboardingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    current_step: int = 1
    completed_steps: list[int] = Field(default_factory=list)
    step_data: dict[str, Any] = Field(default_factory=dict)
    submitted_at: datetime.datetime | None = None
    completed_at: datetime.datetime | None = None
    last_edited_by: UUID | None = None
    updated_at: datetime.datetime | None = None


class TenantOnboardingUpdate(BaseModel):
    current_step: int = Field(default=1, ge=1, le=9)
    completed_steps: list[int] = Field(default_factory=list)
    step_data: dict[str, Any] = Field(default_factory=dict)


class OnboardingChecklistResponse(BaseModel):
    onboarding_submitted: bool
    has_commerce_integration: bool
    has_helpdesk_integration: bool
    has_knowledge: bool
    complete: bool
    agent_lifecycle_state: str


class IntegrationStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    provider: str
    is_active: bool
    is_primary_for_kind: bool
    config: dict[str, Any] = Field(default_factory=dict)
    enabled_at: datetime.datetime | None = None


class IntegrationsOverviewResponse(BaseModel):
    integrations: list[IntegrationStatusResponse]
    checklist: OnboardingChecklistResponse


class ConnectShopifyRequest(BaseModel):
    """Credentials del Custom App creado en Shopify Dev Dashboard.

    Shopify deprecó los Custom Apps legacy con `shpat_` permanente el 1-ene-2026.
    El flow nuevo: merchant crea app en Dev Dashboard, instala en su tienda, y
    copia Client ID + Client Secret. Auyan los intercambia por access_token de 24h.
    """

    domain: str = Field(min_length=1, max_length=255)
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str = Field(min_length=1, max_length=255)


class ConnectChatwootRequest(BaseModel):
    base_url: str = Field(min_length=1, max_length=255)
    account_id: str = Field(min_length=1, max_length=64)
    api_access_token: str = Field(min_length=1, max_length=255)
    escalation_team_id: str | None = Field(default=None, max_length=64)


class ConnectIntegrationResponse(BaseModel):
    integration: IntegrationStatusResponse
    checklist: OnboardingChecklistResponse
    webhook_registered: bool | None = None


class TenantLifecycleUpdate(BaseModel):
    agent_lifecycle_state: str = Field(
        pattern="^(initial|discovery|building|shadow|ramping|active|paused|churned)$"
    )


KnowledgeSourceType = Literal["text", "url", "file"]
KnowledgeSubmissionStatus = Literal["pending_review", "approved", "rejected", "superseded"]


class TenantKnowledgeSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    title: str
    source_type: KnowledgeSourceType
    source_url: str | None = None
    source_key: str | None = None
    original_filename: str | None = None
    content: str = ""
    notes: str | None = None
    status: KnowledgeSubmissionStatus
    metadata: dict[str, Any] = Field(default_factory=dict)
    submitted_by: UUID | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime.datetime | None = None
    review_note: str | None = None
    processed_document_id: UUID | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class TenantKnowledgeSubmissionCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    source_type: KnowledgeSourceType = "text"
    source_url: str | None = Field(default=None, max_length=2_000)
    original_filename: str | None = Field(default=None, max_length=500)
    content: str = Field(default="", max_length=200_000)
    notes: str | None = Field(default=None, max_length=5_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_content_or_url(self) -> TenantKnowledgeSubmissionCreate:
        if not self.content.strip() and not self.source_url:
            raise ValueError("Debes enviar contenido o una URL de origen.")
        return self


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    source: str | None = None
    source_key: str | None = None
    created_at: datetime.datetime
    chunk_count: int


class TenantKnowledgeSubmissionReview(BaseModel):
    review_note: str | None = Field(default=None, max_length=5_000)


KnowledgeStatusQuery = Annotated[
    KnowledgeSubmissionStatus | None,
    Query(alias="status"),
]

WeeklyReportStatus = Literal["draft", "pending_review", "approved", "sent"]


class WeeklyReportResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    week_start: str
    week_end: str
    status: WeeklyReportStatus
    subject: str
    recipient_email: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    narrative: str = ""
    created_by: UUID | None = None
    approved_by: UUID | None = None
    approved_at: datetime.datetime | None = None
    sent_by: UUID | None = None
    sent_at: datetime.datetime | None = None
    postmark_message_id: str | None = None
    send_error: str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class WeeklyReportGenerateRequest(BaseModel):
    week_start: datetime.date
    week_end: datetime.date
    recipient_email: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def _valid_range(self) -> WeeklyReportGenerateRequest:
        if self.week_end < self.week_start:
            raise ValueError("week_end debe ser mayor o igual a week_start.")
        return self


class WeeklyReportUpdateRequest(BaseModel):
    subject: str = Field(min_length=3, max_length=240)
    narrative: str = Field(min_length=1, max_length=50_000)
    recipient_email: str | None = Field(default=None, max_length=320)


WeeklyReportStatusQuery = Annotated[
    WeeklyReportStatus | None,
    Query(alias="status"),
]

OutboundEmailJobStatus = Literal["queued", "sending", "sent", "failed", "canceled"]


class OutboundEmailTemplateResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    key: str
    name: str
    subject_template: str
    text_body_template: str
    html_body_template: str | None = None
    variables: list[str] = Field(default_factory=list)
    is_active: bool = True
    version: int
    created_by: UUID | None = None
    updated_by: UUID | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class OutboundEmailTemplateCreateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    name: str = Field(min_length=2, max_length=160)
    subject_template: str = Field(min_length=1, max_length=240)
    text_body_template: str = Field(min_length=1, max_length=50_000)
    html_body_template: str | None = Field(default=None, max_length=100_000)
    variables: list[str] = Field(default_factory=list, max_length=50)
    is_active: bool = True


class OutboundEmailTemplateUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    subject_template: str = Field(min_length=1, max_length=240)
    text_body_template: str = Field(min_length=1, max_length=50_000)
    html_body_template: str | None = Field(default=None, max_length=100_000)
    variables: list[str] = Field(default_factory=list, max_length=50)
    is_active: bool = True


class OutboundEmailJobResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    template_id: UUID | None = None
    recipient_email: str
    subject: str
    text_body: str
    html_body: str | None = None
    tag: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: OutboundEmailJobStatus
    attempts: int
    max_attempts: int
    next_attempt_at: datetime.datetime | None = None
    last_attempt_at: datetime.datetime | None = None
    sent_at: datetime.datetime | None = None
    postmark_message_id: str | None = None
    error: str | None = None
    requested_by: UUID | None = None
    idempotency_key: str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class OutboundEmailJobCreateRequest(BaseModel):
    template_id: UUID | None = None
    recipient_email: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=240)
    text_body: str = Field(min_length=1, max_length=50_000)
    html_body: str | None = Field(default=None, max_length=100_000)
    tag: str | None = Field(default=None, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=160)
    max_attempts: int = Field(default=3, ge=1, le=10)


OutboundEmailJobStatusQuery = Annotated[
    OutboundEmailJobStatus | None,
    Query(alias="status"),
]


# ----------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------


@router.get(
    "/admin/list",
    response_model=list[TenantResponse],
    summary="Listar todos los tenants — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def list_tenants_admin() -> list[TenantResponse]:
    async with bootstrap_connection() as conn:
        tenants = await list_all_tenants(conn)
    return [TenantResponse.model_validate(t) for t in tenants]


@router.post(
    "",
    response_model=CreateTenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear nuevo tenant + tenant_admin con invite — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def create_tenant(
    payload: CreateTenantRequest,
    auth: AuthDep,
    settings: SettingsDep,
) -> CreateTenantResponse:
    async with bootstrap_connection() as conn:
        internal_user = await get_internal_user_by_auth_id(conn, auth.user_id)
        if internal_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="super_admin sin registro en internal_users — no puede asignarse como AIDE",
            )
        async with httpx.AsyncClient() as http:
            try:
                result = await provision_tenant(
                    conn,
                    settings=settings,
                    http=http,
                    request=ProvisionRequest(
                        company_name=payload.company_name,
                        slug=payload.slug,
                        plan_tier=payload.plan_tier,
                        tenant_admin_email=payload.tenant_admin_email,
                        tenant_admin_name=payload.tenant_admin_name,
                        creator_internal_user_id=internal_user.id,
                    ),
                )
            except SlugTakenError:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"slug '{payload.slug}' ya está en uso",
                ) from None
            except SupabaseAdminError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Supabase Admin: {exc}",
                ) from exc

    return CreateTenantResponse(
        tenant=TenantResponse.model_validate(result.tenant),
        tenant_admin_user_id=result.tenant_admin_user_id,
        invite_sent=result.invite_sent,
    )


@router.post(
    "/demos",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una demo desde la URL de una tienda — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def create_demo(
    payload: CreateDemoRequest, settings: SettingsDep, auth: AuthDep, request: Request
) -> TenantResponse:
    async with bootstrap_connection() as conn:
        try:
            tenant = await create_demo_tenant(conn, settings=settings, url=payload.url)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"url_invalida: {payload.url!r} no es el dominio de una tienda",
            ) from exc
        except DemoSlugExhaustedError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="demo_slug_agotado: reintenta en unos segundos",
            ) from exc
        await start_demo_ingestion(conn, tenant, requested_by=auth.user_id)
    worker = getattr(request.app.state, "site_ingestion_worker", None)
    if worker is not None:
        worker.notify()
    return TenantResponse.model_validate(tenant)


@router.get(
    "/admin/review-queue",
    response_model=list[AdminReviewQueueItem],
    summary="Review Queue cross-tenant — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def get_admin_review_queue() -> list[AdminReviewQueueItem]:
    async with bootstrap_connection() as conn:
        rows = await list_admin_review_queue(conn)
    return [AdminReviewQueueItem.model_validate(row) for row in rows]


@router.get(
    "/me",
    response_model=TenantResponse,
    summary="Perfil del tenant del caller",
)
async def get_my_tenant(tenant_id: TenantIdDep) -> TenantResponse:
    async with tenant_scope(tenant_id) as conn:
        tenant = await get_tenant(conn, tenant_id)
    return TenantResponse.model_validate(tenant)


@router.get(
    "/me/config",
    response_model=TenantConfigResponse,
    summary="Configuración del tenant del caller",
)
async def get_my_tenant_config(tenant_id: TenantIdDep) -> TenantConfigResponse:
    async with tenant_scope(tenant_id) as conn:
        config = await get_tenant_config(conn, tenant_id)
        integrations = await list_tenant_integration_groups(conn, tenant_id)
    return TenantConfigResponse(
        tenant_id=config.tenant_id,
        agent_model=config.agent_model,
        escalation_threshold=config.escalation_threshold,
        integrations=integrations,
        branding=config.branding,
        extra=config.extra,
    )


@router.get(
    "/me/metrics",
    response_model=TenantMetricsResponse,
    summary="Métricas agregadas del tenant — conteos y tasas",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_tenant_metrics(tenant_id: TenantIdDep) -> TenantMetricsResponse:
    async with tenant_scope(tenant_id) as conn:
        data = await get_tenant_metrics(conn, tenant_id)
    return TenantMetricsResponse(
        total=data["total"],  # type: ignore[arg-type]
        by_status=ConversationStatusCounts(**data["by_status"]),  # type: ignore[arg-type]
        resolution_rate=data["resolution_rate"],  # type: ignore[arg-type]
        escalation_rate=data["escalation_rate"],  # type: ignore[arg-type]
        resolution_windows=data["resolution_windows"],  # type: ignore[arg-type]
    )


@router.get(
    "/me/insights",
    response_model=TenantInsightsResponse,
    summary="Insights agregados del tenant para dashboard cliente",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_tenant_insights(
    tenant_id: TenantIdDep,
    days: int = Query(default=14, ge=1, le=90, description="Días de historial a retornar"),
) -> TenantInsightsResponse:
    async with tenant_scope(tenant_id) as conn:
        data = await get_tenant_insights(conn, tenant_id, days=days)
    return TenantInsightsResponse.model_validate(data)


@router.get(
    "/me/usage",
    response_model=TenantUsageResponse,
    summary="Consumo de tokens y costo LLM del tenant — hoy y últimos N días",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_tenant_usage(
    tenant_id: TenantIdDep,
    settings: SettingsDep,
    days: int = Query(default=7, ge=1, le=90, description="Días de historial a retornar"),
) -> TenantUsageResponse:
    async with bootstrap_connection() as conn:
        tenant_config = await get_tenant_configuration(conn, tenant_id)

    async with tenant_scope(tenant_id) as conn:
        rows = await get_tenant_usage_range(conn, tenant_id=tenant_id, days=days)

    budget: float = settings.budget_usd_daily
    if tenant_config is not None:
        override = tenant_config.extra.get("budget_usd_daily")
        if isinstance(override, int | float) and override > 0:
            budget = float(override)

    history = [
        DailyUsage(
            date=row.date,
            tokens_in=row.tokens_in,
            tokens_out=row.tokens_out,
            cost_usd=float(row.cost_usd),
            request_count=row.request_count,
        )
        for row in rows
    ]

    today_str = datetime.date.today().isoformat()
    today = next((h for h in history if h.date == today_str), None)
    budget_used_pct = round(today.cost_usd / budget * 100, 1) if today and budget > 0 else 0.0

    return TenantUsageResponse(
        today=today,
        budget_usd_daily=budget,
        budget_used_pct=budget_used_pct,
        days=days,
        history=history,
    )


@router.get(
    "/me/weekly-reports",
    response_model=list[WeeklyReportResponse],
    summary="Lista reportes semanales del tenant",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def list_my_weekly_reports(
    tenant_id: TenantIdDep,
    status_filter: WeeklyReportStatusQuery = None,
) -> list[WeeklyReportResponse]:
    async with tenant_scope(tenant_id) as conn:
        reports = await list_weekly_reports(conn, tenant_id, status=status_filter)
    return [WeeklyReportResponse.model_validate(report) for report in reports]


@router.post(
    "/me/weekly-reports/generate",
    response_model=WeeklyReportResponse,
    summary="Genera o refresca borrador de reporte semanal — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def generate_my_weekly_report(
    body: WeeklyReportGenerateRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> WeeklyReportResponse:
    async with tenant_scope(tenant_id) as conn:
        report = await create_or_refresh_weekly_report_draft(
            conn,
            tenant_id,
            week_start=body.week_start.isoformat(),
            week_end=body.week_end.isoformat(),
            recipient_email=body.recipient_email,
            created_by=auth.user_id,
        )
    return WeeklyReportResponse.model_validate(report)


@router.get(
    "/me/weekly-reports/{report_id}",
    response_model=WeeklyReportResponse,
    summary="Detalle de un reporte semanal",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_weekly_report(
    report_id: UUID,
    tenant_id: TenantIdDep,
) -> WeeklyReportResponse:
    async with tenant_scope(tenant_id) as conn:
        report = await get_weekly_report(conn, tenant_id, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Reporte semanal no encontrado")
    return WeeklyReportResponse.model_validate(report)


@router.patch(
    "/me/weekly-reports/{report_id}",
    response_model=WeeklyReportResponse,
    summary="Edita asunto, destinatario y narrativa del borrador — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def update_my_weekly_report(
    report_id: UUID,
    body: WeeklyReportUpdateRequest,
    tenant_id: TenantIdDep,
) -> WeeklyReportResponse:
    async with tenant_scope(tenant_id) as conn:
        current = await get_weekly_report(conn, tenant_id, report_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Reporte semanal no encontrado")
        if current.status != "draft":
            raise HTTPException(status_code=409, detail="Sólo se pueden editar borradores")
        report = await update_weekly_report_draft(
            conn,
            tenant_id,
            report_id,
            subject=body.subject.strip(),
            narrative=body.narrative.strip(),
            recipient_email=body.recipient_email.strip() if body.recipient_email else None,
        )
    if report is None:
        raise HTTPException(status_code=409, detail="El reporte ya no está en borrador")
    return WeeklyReportResponse.model_validate(report)


@router.post(
    "/me/weekly-reports/{report_id}/submit",
    response_model=WeeklyReportResponse,
    summary="Mueve un borrador a cola de revisión interna — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def submit_my_weekly_report(
    report_id: UUID,
    tenant_id: TenantIdDep,
) -> WeeklyReportResponse:
    async with tenant_scope(tenant_id) as conn:
        current = await get_weekly_report(conn, tenant_id, report_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Reporte semanal no encontrado")
        if current.status != "draft":
            raise HTTPException(status_code=409, detail="Sólo borradores pasan a revisión")
        report = await submit_weekly_report_for_review(conn, tenant_id, report_id)
    if report is None:
        raise HTTPException(status_code=409, detail="El reporte ya no está en borrador")
    return WeeklyReportResponse.model_validate(report)


@router.post(
    "/me/weekly-reports/{report_id}/approve",
    response_model=WeeklyReportResponse,
    summary="Aprueba un reporte semanal para envío — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def approve_my_weekly_report(
    report_id: UUID,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> WeeklyReportResponse:
    async with tenant_scope(tenant_id) as conn:
        current = await get_weekly_report(conn, tenant_id, report_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Reporte semanal no encontrado")
        if current.status != "pending_review":
            raise HTTPException(status_code=409, detail="Sólo reportes en revisión se aprueban")
        report = await approve_weekly_report(
            conn,
            tenant_id,
            report_id,
            approved_by=auth.user_id,
        )
    if report is None:
        raise HTTPException(status_code=409, detail="El reporte ya no está en revisión")
    return WeeklyReportResponse.model_validate(report)


@router.post(
    "/me/weekly-reports/{report_id}/send",
    response_model=WeeklyReportResponse,
    summary="Envía un reporte aprobado por Postmark — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def send_my_weekly_report(
    report_id: UUID,
    request: Request,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> WeeklyReportResponse:
    async with tenant_scope(tenant_id) as conn:
        current = await get_weekly_report(conn, tenant_id, report_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Reporte semanal no encontrado")
    if current.status != "approved":
        raise HTTPException(status_code=409, detail="Sólo reportes aprobados se envían")
    if not current.recipient_email:
        raise HTTPException(status_code=400, detail="Reporte sin recipient_email")

    email_sender = getattr(request.app.state, "email_sender", None)
    if email_sender is None:
        async with tenant_scope(tenant_id) as conn:
            await mark_weekly_report_send_failed(
                conn,
                tenant_id,
                report_id,
                send_error="email_sender_not_configured",
            )
        raise HTTPException(status_code=503, detail="Email sender no configurado")

    from apps.api.services.email_templates import weekly_report

    subject, text_body, html_body = weekly_report.render(
        subject=current.subject,
        week_start=current.week_start,
        week_end=current.week_end,
        metrics=current.metrics,
        narrative=current.narrative,
    )
    try:
        result = await email_sender.send_email_now(
            to=current.recipient_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            tag="weekly-report",
        )
    except Exception as exc:
        async with tenant_scope(tenant_id) as conn:
            await mark_weekly_report_send_failed(
                conn,
                tenant_id,
                report_id,
                send_error=str(exc),
            )
        raise HTTPException(status_code=503, detail="Postmark no pudo enviar el reporte") from exc

    message_id = result.get("MessageID") or result.get("MessageId")
    async with tenant_scope(tenant_id) as conn:
        report = await mark_weekly_report_sent(
            conn,
            tenant_id,
            report_id,
            sent_by=auth.user_id,
            postmark_message_id=str(message_id) if message_id else None,
        )
    if report is None:
        raise HTTPException(status_code=409, detail="El reporte ya no está aprobado")
    return WeeklyReportResponse.model_validate(report)


@router.get(
    "/me/outbound-email/templates",
    response_model=list[OutboundEmailTemplateResponse],
    summary="Lista templates de email outbound — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def list_my_outbound_email_templates(
    tenant_id: TenantIdDep,
    include_inactive: bool = Query(default=False),
) -> list[OutboundEmailTemplateResponse]:
    async with tenant_scope(tenant_id) as conn:
        templates = await list_outbound_email_templates(
            conn,
            tenant_id,
            include_inactive=include_inactive,
        )
    return [OutboundEmailTemplateResponse.model_validate(template) for template in templates]


@router.post(
    "/me/outbound-email/templates",
    response_model=OutboundEmailTemplateResponse,
    summary="Crea template de email outbound — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def create_my_outbound_email_template(
    body: OutboundEmailTemplateCreateRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> OutboundEmailTemplateResponse:
    async with tenant_scope(tenant_id) as conn:
        template = await create_outbound_email_template(
            conn,
            tenant_id,
            key=body.key.strip(),
            name=body.name.strip(),
            subject_template=body.subject_template.strip(),
            text_body_template=body.text_body_template.strip(),
            html_body_template=body.html_body_template.strip() if body.html_body_template else None,
            variables=body.variables,
            is_active=body.is_active,
            created_by=auth.user_id,
        )
    return OutboundEmailTemplateResponse.model_validate(template)


@router.patch(
    "/me/outbound-email/templates/{template_id}",
    response_model=OutboundEmailTemplateResponse,
    summary="Actualiza template de email outbound — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def update_my_outbound_email_template(
    template_id: UUID,
    body: OutboundEmailTemplateUpdateRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> OutboundEmailTemplateResponse:
    async with tenant_scope(tenant_id) as conn:
        current = await get_outbound_email_template(conn, tenant_id, template_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Template de email no encontrado")
        template = await update_outbound_email_template(
            conn,
            tenant_id,
            template_id,
            name=body.name.strip(),
            subject_template=body.subject_template.strip(),
            text_body_template=body.text_body_template.strip(),
            html_body_template=body.html_body_template.strip() if body.html_body_template else None,
            variables=body.variables,
            is_active=body.is_active,
            updated_by=auth.user_id,
        )
    if template is None:
        raise HTTPException(status_code=404, detail="Template de email no encontrado")
    return OutboundEmailTemplateResponse.model_validate(template)


@router.get(
    "/me/outbound-email/jobs",
    response_model=list[OutboundEmailJobResponse],
    summary="Lista jobs de email outbound — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def list_my_outbound_email_jobs(
    tenant_id: TenantIdDep,
    status_filter: OutboundEmailJobStatusQuery = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[OutboundEmailJobResponse]:
    async with tenant_scope(tenant_id) as conn:
        jobs = await list_outbound_email_jobs(
            conn,
            tenant_id,
            status=status_filter,
            limit=limit,
        )
    return [OutboundEmailJobResponse.model_validate(job) for job in jobs]


@router.get(
    "/me/outbound-email/jobs/{job_id}",
    response_model=OutboundEmailJobResponse,
    summary="Detalle de job de email outbound — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def get_my_outbound_email_job(
    job_id: UUID,
    tenant_id: TenantIdDep,
) -> OutboundEmailJobResponse:
    async with tenant_scope(tenant_id) as conn:
        job = await get_outbound_email_job(conn, tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job de email no encontrado")
    return OutboundEmailJobResponse.model_validate(job)


@router.post(
    "/me/outbound-email/jobs",
    response_model=OutboundEmailJobResponse,
    summary="Encola job de email outbound — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def enqueue_my_outbound_email_job(
    body: OutboundEmailJobCreateRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> OutboundEmailJobResponse:
    async with tenant_scope(tenant_id) as conn:
        if body.template_id is not None:
            template = await get_outbound_email_template(conn, tenant_id, body.template_id)
            if template is None:
                raise HTTPException(status_code=404, detail="Template de email no encontrado")
        job = await enqueue_outbound_email_job(
            conn,
            tenant_id,
            template_id=body.template_id,
            recipient_email=body.recipient_email.strip(),
            subject=body.subject.strip(),
            text_body=body.text_body.strip(),
            html_body=body.html_body.strip() if body.html_body else None,
            tag=body.tag.strip() if body.tag else None,
            payload=body.payload,
            idempotency_key=body.idempotency_key.strip() if body.idempotency_key else None,
            max_attempts=body.max_attempts,
            requested_by=auth.user_id,
        )
    return OutboundEmailJobResponse.model_validate(job)


@router.get(
    "/me/playbook",
    response_model=TenantPlaybookResponse,
    summary="Playbook operativo del tenant — lectura cliente, edición Auyan",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_tenant_playbook(tenant_id: TenantIdDep) -> TenantPlaybookResponse:
    async with tenant_scope(tenant_id) as conn:
        playbook = await get_tenant_playbook(conn, tenant_id)
    if playbook is None:
        return TenantPlaybookResponse(tenant_id=tenant_id)
    return TenantPlaybookResponse.model_validate(playbook)


@router.put(
    "/me/playbook",
    response_model=TenantPlaybookResponse,
    summary="Actualiza el playbook operativo del tenant — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def update_my_tenant_playbook(
    body: TenantPlaybookUpdate,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> TenantPlaybookResponse:
    async with tenant_scope(tenant_id) as conn:
        playbook = await upsert_tenant_playbook(
            conn,
            tenant_id=tenant_id,
            brand_voice=body.brand_voice,
            product_overview=body.product_overview,
            policies=body.policies,
            escalation_notes=body.escalation_notes,
            agent_instructions=body.agent_instructions,
            edited_by=auth.user_id,
        )
    return TenantPlaybookResponse.model_validate(playbook)


@router.get(
    "/me/facts",
    response_model=TenantFactsResponse,
    summary="Datos factuales del tenant — usados como contexto estructurado del agente",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_tenant_facts(tenant_id: TenantIdDep) -> TenantFactsResponse:
    async with tenant_scope(tenant_id) as conn:
        facts = await get_tenant_facts(conn, tenant_id)
    if facts is None:
        return TenantFactsResponse(tenant_id=tenant_id)
    return TenantFactsResponse.model_validate(facts)


@router.put(
    "/me/facts",
    response_model=TenantFactsResponse,
    summary="Actualiza datos factuales del tenant",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def update_my_tenant_facts(
    body: TenantFactsUpdate,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> TenantFactsResponse:
    async with tenant_scope(tenant_id) as conn:
        facts = await upsert_tenant_facts(
            conn,
            tenant_id=tenant_id,
            data=body.data,
            edited_by=auth.user_id,
        )
    return TenantFactsResponse.model_validate(facts)


@router.get(
    "/me/onboarding",
    response_model=TenantOnboardingResponse,
    summary="Estado del wizard de onboarding del tenant",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_tenant_onboarding(tenant_id: TenantIdDep) -> TenantOnboardingResponse:
    async with tenant_scope(tenant_id) as conn:
        onboarding = await get_tenant_onboarding(conn, tenant_id)
    if onboarding is None:
        return TenantOnboardingResponse(tenant_id=tenant_id)
    return TenantOnboardingResponse.model_validate(onboarding)


@router.put(
    "/me/onboarding",
    response_model=TenantOnboardingResponse,
    summary="Guarda progreso del wizard de onboarding",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def update_my_tenant_onboarding(
    body: TenantOnboardingUpdate,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> TenantOnboardingResponse:
    completed_steps = sorted({step for step in body.completed_steps if 1 <= step <= 9})
    async with tenant_scope(tenant_id) as conn:
        onboarding = await upsert_tenant_onboarding(
            conn,
            tenant_id=tenant_id,
            current_step=body.current_step,
            completed_steps=completed_steps,
            step_data=body.step_data,
            edited_by=auth.user_id,
        )
    return TenantOnboardingResponse.model_validate(onboarding)


@router.get(
    "/me/onboarding/checklist",
    response_model=OnboardingChecklistResponse,
    summary="Estado del checklist que gatea discovery → building",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_onboarding_checklist(
    tenant_id: TenantIdDep,
) -> OnboardingChecklistResponse:
    async with tenant_scope(tenant_id) as conn:
        checklist = await compute_onboarding_checklist(conn, tenant_id)
        tenant = await get_tenant(conn, tenant_id)
    return _checklist_response(checklist, tenant.agent_lifecycle_state)


@router.post(
    "/me/onboarding/submit",
    response_model=TenantOnboardingResponse,
    summary="Confirma onboarding inicial; pasa a Building si el checklist está completo",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def submit_my_tenant_onboarding(
    request: Request,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> TenantOnboardingResponse:
    async with tenant_scope(tenant_id) as conn:
        onboarding = await submit_tenant_onboarding(
            conn,
            tenant_id=tenant_id,
            edited_by=auth.user_id,
        )
        tenant, checklist = await evaluate_and_advance_lifecycle(conn, tenant_id)

        # step_data tiene estructura {"1": {...step1...}, "2": {...step2...}, ...}
        sd = onboarding.step_data
        step1 = sd.get("1") or {}
        step2 = sd.get("2") or {}
        step3 = sd.get("3") or {}
        step9 = sd.get("9") or {}
        # Fusiona (no reemplaza): el wizard no borra lo ya ingerido de la web ni lo editado.
        await merge_tenant_playbook(
            conn,
            tenant_id=tenant_id,
            brand_voice=str(step2.get("voice_traits") or ""),
            escalation_notes=str(step2.get("forbidden_phrases") or ""),
            agent_instructions=str(step9.get("launch_notes") or ""),
            edited_by=auth.user_id,
        )
        _facts_candidates = {
            "company_name": step1.get("company_name"),
            "website_url": step1.get("website_url"),
            "primary_contact": step1.get("primary_contact"),
            "business_hours": step3.get("business_hours"),
            "support_email": step3.get("support_email"),
            "support_phone": step3.get("support_phone"),
        }
        facts_data = {k: v for k, v in _facts_candidates.items() if v is not None}
        if facts_data:
            await merge_tenant_facts(
                conn,
                tenant_id=tenant_id,
                data=facts_data,
                edited_by=auth.user_id,
            )

    advanced = tenant.agent_lifecycle_state == "building"
    email_sender = getattr(request.app.state, "email_sender", None)
    if email_sender is not None:
        if advanced:
            body = (
                f"Recibimos el onboarding de {tenant.name}.\n\n"
                "El agente pasa a fase Building. El siguiente paso de Auyan es revisar "
                "la información, preparar el playbook y configurar los primeros AOPs."
            )
        else:
            faltan = []
            if not checklist.has_commerce_integration:
                faltan.append("conectar tu tienda (Shopify)")
            if not checklist.has_helpdesk_integration:
                faltan.append("conectar tu helpdesk")
            if not checklist.has_knowledge:
                faltan.append("aportar al menos un documento o URL de conocimiento")
            body = (
                f"Recibimos el onboarding de {tenant.name}.\n\n"
                "Para que el agente pase a fase Building todavía falta: "
                + "; ".join(faltan)
                + ".\n\nPuedes completarlo desde el portal cuando quieras."
            )
        email_sender.send_email(
            to=auth.email,
            subject=f"Auyan recibió el onboarding de {tenant.name}",
            text_body=body,
            tag="tenant-onboarding-submitted",
        )

    return TenantOnboardingResponse.model_validate(onboarding)


# ----------------------------------------------------------------
# Integraciones del tenant (el cliente las conecta durante el onboarding guiado)
# ----------------------------------------------------------------

# El handler entrante sólo procesa message_created + incoming, así que ese es
# el único evento que necesitamos suscribir en Chatwoot.
_CHATWOOT_WEBHOOK_SUBSCRIPTIONS = ["message_created"]


def _checklist_response(
    checklist: OnboardingChecklist, agent_lifecycle_state: str
) -> OnboardingChecklistResponse:
    return OnboardingChecklistResponse(
        onboarding_submitted=checklist.onboarding_submitted,
        has_commerce_integration=checklist.has_commerce_integration,
        has_helpdesk_integration=checklist.has_helpdesk_integration,
        has_knowledge=checklist.has_knowledge,
        complete=checklist.complete,
        agent_lifecycle_state=agent_lifecycle_state,
    )


def _normalize_shopify_domain(raw: str) -> str:
    """Quita esquema y barras para dejar el myshopify domain limpio."""
    domain = raw.strip().removeprefix("https://").removeprefix("http://")
    return domain.strip("/")


def _crypto_key(settings: SettingsDep) -> bytes:
    try:
        return get_integration_crypto_key(settings)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail="Cifrado de integraciones no configurado"
        ) from exc


@router.get(
    "/me/integrations",
    response_model=IntegrationsOverviewResponse,
    summary="Estado de las integraciones del tenant + checklist de onboarding",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def get_my_integrations(tenant_id: TenantIdDep) -> IntegrationsOverviewResponse:
    async with tenant_scope(tenant_id) as conn:
        rows = await list_integrations_for_tenant(conn, tenant_id=tenant_id)
        checklist = await compute_onboarding_checklist(conn, tenant_id)
        tenant = await get_tenant(conn, tenant_id)
    return IntegrationsOverviewResponse(
        integrations=[IntegrationStatusResponse.model_validate(r) for r in rows],
        checklist=_checklist_response(checklist, tenant.agent_lifecycle_state),
    )


@router.get(
    "/me/doctor",
    response_model=DoctorReport,
    summary="Doctor del tenant: migraciones, helpdesk, triggers, webhooks y WhatsApp en vivo",
    dependencies=[Depends(require_role("super_admin"))],
)
async def get_my_tenant_doctor(tenant_id: TenantIdDep, settings: SettingsDep) -> DoctorReport:
    """Solo lecturas (catálogo de Postgres + APIs de terceros). Tarda unos segundos."""
    try:
        return await run_tenant_doctor(
            tenant_id,
            crypto_key=_crypto_key(settings),
            api_base_url=getattr(settings, "api_base_url", None),
        )
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Tenant no encontrado") from exc


@router.post(
    "/me/integrations/shopify",
    response_model=ConnectIntegrationResponse,
    summary="Conecta la tienda Shopify del tenant (valida, cifra y guarda)",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def connect_shopify(
    body: ConnectShopifyRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
    settings: SettingsDep,
) -> ConnectIntegrationResponse:
    """Valida client_id + client_secret vía OAuth Client Credentials Grant, persiste.

    Shopify 2026: el merchant crea una app en Dev Dashboard, la instala, copia
    Client ID + Client Secret. Aquí los intercambiamos por un access_token de 24h.
    Guardamos client_id + client_secret cifrados (long-lived), y el access_token
    en config (short-lived, refrescado on-demand por `ensure_shopify_access_token`).
    """
    domain = _normalize_shopify_domain(body.domain)

    # 1) Validar credentials con Shopify (OAuth Client Credentials Grant).
    try:
        access_token, _expires_in = await exchange_client_credentials(
            shop_domain=domain,
            client_id=body.client_id,
            client_secret=body.client_secret,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "No pudimos validar las credenciales de Shopify "
                "(Client ID o Client Secret inválidos)"
            ),
        ) from exc

    # 2) Llamada de verificación para obtener shop name/email + asegurar que el
    # access_token funciona contra Admin API.
    try:
        shop = await ShopifyClient(domain, access_token).validate()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=422,
            detail="Credentials válidas pero el access_token no tiene permisos sobre la tienda",
        ) from exc

    now = datetime.datetime.now(datetime.UTC)

    key = _crypto_key(settings)
    encrypted = encrypt_credentials(
        json.dumps(
            {
                "domain": domain,
                "client_id": body.client_id,
                "client_secret": body.client_secret,
            }
        ).encode(),
        key,
    )
    # NO cacheamos el access_token aquí: es una credencial viva y guardarla en config
    # (claro) rompía el cifrado en reposo. El access_token corto se resuelve on-demand
    # con cache en memoria (ensure_shopify_access_token). En DB sólo van los secretos
    # durables, cifrados en credentials_encrypted.
    config: dict[str, Any] = {
        "shop_name": shop.get("name"),
        "shop_email": shop.get("email"),
        "verified_at": now.isoformat(),
    }

    async with tenant_scope(tenant_id) as conn:
        integration = await upsert_integration(
            conn,
            tenant_id=tenant_id,
            kind="commerce",
            provider="shopify",
            credentials_encrypted=encrypted,
            config=config,
            is_active=True,
            is_primary_for_kind=True,
            enabled_by=auth.user_id,
        )
        tenant, checklist = await evaluate_and_advance_lifecycle(conn, tenant_id)

    return ConnectIntegrationResponse(
        integration=IntegrationStatusResponse.model_validate(integration),
        checklist=_checklist_response(checklist, tenant.agent_lifecycle_state),
    )


@router.post(
    "/me/integrations/chatwoot",
    response_model=ConnectIntegrationResponse,
    summary="Conecta el helpdesk Chatwoot del tenant (valida, registra webhook, cifra y guarda)",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def connect_chatwoot(
    body: ConnectChatwootRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
    settings: SettingsDep,
) -> ConnectIntegrationResponse:
    base_url = body.base_url.strip().rstrip("/")
    try:
        account_id = int(body.account_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="account_id de Chatwoot debe ser numérico"
        ) from exc

    client = ChatwootClient(
        base_url=base_url, api_access_token=body.api_access_token, account_id=account_id
    )
    try:
        account = await client.validate()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=422,
            detail="No pudimos validar las credenciales de Chatwoot (token o account inválidos)",
        ) from exc

    webhook_registered = await _ensure_chatwoot_webhook(client, settings)

    key = _crypto_key(settings)
    encrypted = encrypt_credentials(
        json.dumps({"api_access_token": body.api_access_token}).encode(), key
    )
    config: dict[str, Any] = {
        "base_url": base_url,
        "account_id": body.account_id,
        "account_name": account.get("name"),
        "webhook_registered": webhook_registered,
        "verified_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    if body.escalation_team_id:
        config["escalation_team_id"] = body.escalation_team_id

    async with tenant_scope(tenant_id) as conn:
        integration = await upsert_integration(
            conn,
            tenant_id=tenant_id,
            kind="helpdesk",
            provider="chatwoot",
            credentials_encrypted=encrypted,
            config=config,
            is_active=True,
            is_primary_for_kind=True,
            enabled_by=auth.user_id,
        )
        tenant, checklist = await evaluate_and_advance_lifecycle(conn, tenant_id)

    return ConnectIntegrationResponse(
        integration=IntegrationStatusResponse.model_validate(integration),
        checklist=_checklist_response(checklist, tenant.agent_lifecycle_state),
        webhook_registered=webhook_registered,
    )


async def _ensure_chatwoot_webhook(client: ChatwootClient, settings: SettingsDep) -> bool:
    """Registra el webhook entrante de Auyan en Chatwoot, sin duplicar.

    Devuelve False (sin fallar la conexión) si no hay api_base_url configurado
    o si Chatwoot rechaza el alta — el cliente puede pegar la URL a mano luego.
    """
    api_base = getattr(settings, "api_base_url", None)
    if not api_base:
        return False
    target = f"{api_base.rstrip('/')}/webhooks/chatwoot"
    try:
        existing = await client.list_webhooks()
        if any(hook.get("url") == target for hook in existing):
            return True
        await client.create_webhook(target, _CHATWOOT_WEBHOOK_SUBSCRIPTIONS)
        return True
    except httpx.HTTPStatusError:
        logger.warning("No se pudo registrar el webhook de Chatwoot automáticamente")
        return False


@router.put(
    "/me/lifecycle",
    response_model=TenantResponse,
    summary="Actualiza lifecycle del agente — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def update_my_tenant_lifecycle(
    body: TenantLifecycleUpdate,
    tenant_id: TenantIdDep,
) -> TenantResponse:
    async with tenant_scope(tenant_id) as conn:
        tenant = await update_tenant_lifecycle_state(
            conn,
            tenant_id,
            body.agent_lifecycle_state,
        )
    return TenantResponse.model_validate(tenant)


@router.get(
    "/me/kb-submissions",
    response_model=list[TenantKnowledgeSubmissionResponse],
    summary="Lista submissions de conocimiento del tenant",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def list_my_kb_submissions(
    tenant_id: TenantIdDep,
    status_filter: KnowledgeStatusQuery = None,
) -> list[TenantKnowledgeSubmissionResponse]:
    async with tenant_scope(tenant_id) as conn:
        rows = await list_tenant_knowledge_submissions(
            conn,
            tenant_id,
            status=status_filter,
        )
    return [TenantKnowledgeSubmissionResponse.model_validate(row) for row in rows]


@router.post(
    "/me/kb-submissions",
    response_model=TenantKnowledgeSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea un submission de conocimiento para revisión de Auyan",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def create_my_kb_submission(
    body: TenantKnowledgeSubmissionCreate,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> TenantKnowledgeSubmissionResponse:
    async with tenant_scope(tenant_id) as conn:
        submission = await create_tenant_knowledge_submission(
            conn,
            tenant_id,
            title=body.title.strip(),
            source_type=body.source_type,
            source_url=body.source_url.strip() if body.source_url else None,
            original_filename=body.original_filename,
            content=body.content.strip(),
            notes=body.notes,
            metadata=body.metadata,
            submitted_by=auth.user_id,
        )
        # Reevaluar el checklist — añadir KB puede completar el último gate
        # discovery→building. Ignoramos el resultado: la UI re-fetchea
        # /me/onboarding/checklist o /me/integrations para refrescar el estado.
        await evaluate_and_advance_lifecycle(conn, tenant_id)
    return TenantKnowledgeSubmissionResponse.model_validate(submission)


@router.post(
    "/me/kb-submissions/{submission_id}/approve",
    response_model=TenantKnowledgeSubmissionResponse,
    summary="Aprueba un submission y lo indexa en la KB — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def approve_my_kb_submission(
    submission_id: UUID,
    body: TenantKnowledgeSubmissionReview,
    request: Request,
    tenant_id: TenantIdDep,
    auth: AuthDep,
    settings: SettingsDep,
) -> TenantKnowledgeSubmissionResponse:
    deps = getattr(request.app.state, "agent_deps", None)
    openai_client = getattr(deps, "openai", None)
    if openai_client is None:
        raise HTTPException(status_code=503, detail="Cliente OpenAI no inicializado")

    result = await approve_submissions_batch(
        tenant_id=tenant_id,
        submission_ids=[submission_id],
        reviewed_by=auth.user_id,
        review_note=body.review_note,
        confirmation="confirmed",
        embedder=make_embedder(openai_client, settings=settings),
    )
    if result.approved:
        return TenantKnowledgeSubmissionResponse.model_validate(result.approved[0])
    if result.failures:
        failure = result.failures[0]
        status_code = {
            FailureCode.NOT_FOUND: 404,
            FailureCode.NO_CONTENT: 400,
            FailureCode.EMBEDDING_FAILED: 502,
        }.get(failure.code, 500)
        raise HTTPException(status_code=status_code, detail=failure.detail)
    raise HTTPException(status_code=409, detail="Submission ya revisado")


@router.get(
    "/me/kb-documents",
    response_model=list[KnowledgeDocumentResponse],
    summary="Lista los documentos indexados en la KB del tenant — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def list_my_kb_documents(tenant_id: TenantIdDep) -> list[KnowledgeDocumentResponse]:
    async with tenant_scope(tenant_id) as conn:
        rows = await list_knowledge_documents(conn, tenant_id)
    return [KnowledgeDocumentResponse.model_validate(row) for row in rows]


@router.delete(
    "/me/kb-documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Borra en blando un documento de la KB y sus chunks — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def delete_my_kb_document(document_id: UUID, tenant_id: TenantIdDep) -> None:
    async with tenant_scope(tenant_id) as conn:
        deleted = await soft_delete_knowledge_document(conn, tenant_id, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Documento no encontrado")


@router.post(
    "/me/kb-submissions/{submission_id}/reject",
    response_model=TenantKnowledgeSubmissionResponse,
    summary="Rechaza un submission de conocimiento — sólo super_admin",
    dependencies=[Depends(require_role("super_admin"))],
)
async def reject_my_kb_submission(
    submission_id: UUID,
    body: TenantKnowledgeSubmissionReview,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> TenantKnowledgeSubmissionResponse:
    async with tenant_scope(tenant_id) as conn:
        rejected = await reject_tenant_knowledge_submission(
            conn,
            tenant_id,
            submission_id,
            reviewed_by=auth.user_id,
            review_note=body.review_note,
        )
    if rejected is None:
        raise HTTPException(status_code=409, detail="Submission no encontrado o ya revisado")
    return TenantKnowledgeSubmissionResponse.model_validate(rejected)
