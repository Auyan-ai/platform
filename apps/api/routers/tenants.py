"""Endpoints de tenant — perfil y configuración del tenant autenticado."""

from __future__ import annotations

import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from apps.api.core.config import get_settings
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id, require_role
from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.models import ChannelType
from apps.api.db.queries import (
    approve_tenant_knowledge_submission_with_document,
    approve_weekly_report,
    create_or_refresh_weekly_report_draft,
    create_tenant_knowledge_submission,
    get_tenant_configuration,
    get_tenant_facts,
    get_tenant_knowledge_submission,
    get_tenant_onboarding,
    get_tenant_playbook,
    get_tenant_usage_range,
    get_weekly_report,
    list_all_tenants,
    list_tenant_knowledge_submissions,
    list_weekly_reports,
    mark_weekly_report_send_failed,
    mark_weekly_report_sent,
    reject_tenant_knowledge_submission,
    submit_tenant_onboarding,
    submit_weekly_report_for_review,
    update_tenant_lifecycle_state,
    update_weekly_report_draft,
    upsert_tenant_facts,
    upsert_tenant_onboarding,
    upsert_tenant_playbook,
)
from apps.api.services.knowledge_ingestion import chunk_text_for_kb, embed_kb_chunks
from apps.api.services.tenants import (
    get_tenant,
    get_tenant_config,
    get_tenant_insights,
    get_tenant_metrics,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class TenantConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    agent_model: str
    escalation_threshold: float
    active_channels: list[ChannelType]
    branding: dict
    extra: dict


class ConversationStatusCounts(BaseModel):
    open: int
    pending: int
    escalated: int
    resolved: int
    closed: int


class TenantMetricsResponse(BaseModel):
    total: int
    by_status: ConversationStatusCounts
    resolution_rate: float
    escalation_rate: float


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


class TenantLifecycleUpdate(BaseModel):
    agent_lifecycle_state: str = Field(
        pattern="^(initial|discovery|building|shadow|ramping|active|paused|churned)$"
    )


KnowledgeSourceType = Literal["text", "url", "file"]
KnowledgeSubmissionStatus = Literal["pending_review", "approved", "rejected"]


class TenantKnowledgeSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    title: str
    source_type: KnowledgeSourceType
    source_url: str | None = None
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
    return TenantConfigResponse.model_validate(config)


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


@router.post(
    "/me/onboarding/submit",
    response_model=TenantOnboardingResponse,
    summary="Confirma onboarding inicial y mueve el agente a Building",
    dependencies=[Depends(require_role("tenant_admin", "super_admin"))],
)
async def submit_my_tenant_onboarding(
    request: Request,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> TenantOnboardingResponse:
    async with tenant_scope(tenant_id) as conn:
        tenant = await get_tenant(conn, tenant_id)
        onboarding = await submit_tenant_onboarding(
            conn,
            tenant_id=tenant_id,
            edited_by=auth.user_id,
        )

    email_sender = getattr(request.app.state, "email_sender", None)
    if email_sender is not None:
        email_sender.send_email(
            to=auth.email,
            subject=f"Auyan recibió el onboarding de {tenant.name}",
            text_body=(
                f"Recibimos el onboarding de {tenant.name}.\n\n"
                "El agente pasa a fase Building. El siguiente paso de Auyan es revisar "
                "la información, preparar el playbook y configurar los primeros AOPs."
            ),
            tag="tenant-onboarding-submitted",
        )

    return TenantOnboardingResponse.model_validate(onboarding)


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
    async with tenant_scope(tenant_id) as conn:
        submission = await get_tenant_knowledge_submission(conn, tenant_id, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission no encontrado")
    if submission.status != "pending_review":
        raise HTTPException(status_code=409, detail="Submission ya revisado")
    if not submission.content.strip():
        raise HTTPException(status_code=400, detail="Submission sin contenido indexable")

    chunks = chunk_text_for_kb(submission.content)
    if not chunks:
        raise HTTPException(status_code=400, detail="Submission sin contenido indexable")

    deps = getattr(request.app.state, "agent_deps", None)
    openai_client = getattr(deps, "openai", None)
    if openai_client is None:
        raise HTTPException(status_code=503, detail="Cliente OpenAI no inicializado")

    embedded_chunks = await embed_kb_chunks(
        openai_client,
        chunks,
        settings=settings,
    )
    async with tenant_scope(tenant_id) as conn:
        approved = await approve_tenant_knowledge_submission_with_document(
            conn,
            tenant_id,
            submission_id,
            reviewed_by=auth.user_id,
            review_note=body.review_note,
            chunks=embedded_chunks,
        )
    if approved is None:
        raise HTTPException(status_code=409, detail="Submission ya revisado")
    return TenantKnowledgeSubmissionResponse.model_validate(approved)


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
