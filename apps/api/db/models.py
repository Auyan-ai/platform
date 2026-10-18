"""Modelos Pydantic que reflejan filas de Supabase.

Sólo incluyen los campos que el código de la API y el grafo realmente usan.
Si más adelante hace falta un campo, se agrega aquí — no expongas columnas
"por las dudas".
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

# Enums espejados desde supabase/migrations/20260513000000_initial_schema.sql
MessageRole = Literal["customer", "agent_ai", "agent_human", "system"]
MessageDirection = Literal["inbound", "outbound"]
ConversationStatus = Literal[
    "open", "pending", "resolved", "escalated", "closed", "closed_abandoned"
]
EscalationStatus = Literal["pending", "claimed", "resolved"]
ChannelType = Literal[
    "email",
    "chat",
    "widget",
    "whatsapp",
    "instagram",
    "zendesk",
    "gorgias",
    "intercom",
    "chatwoot",
]
UserRole = Literal["super_admin", "tenant_admin"]
AgentLifecycleState = Literal[
    "initial", "discovery", "building", "shadow", "ramping", "active", "paused", "churned"
]
PlanTier = Literal["founding", "standard", "trial"]
TenantKnowledgeSourceType = Literal["text", "url", "file"]
TenantKnowledgeSubmissionStatus = Literal["pending_review", "approved", "rejected"]
WeeklyReportStatus = Literal["draft", "pending_review", "approved", "sent"]
OutboundEmailJobStatus = Literal["queued", "sending", "sent", "failed", "canceled"]


class _BaseModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Tenant(_BaseModel):
    id: UUID
    slug: str
    name: str
    status: str
    agent_lifecycle_state: AgentLifecycleState = "initial"
    plan_tier: PlanTier = "founding"


class TenantConfiguration(_BaseModel):
    tenant_id: UUID
    agent_model: str
    escalation_threshold: float
    branding: dict = Field(default_factory=dict)
    extra: dict = Field(default_factory=dict)


class EndCustomer(_BaseModel):
    id: UUID
    tenant_id: UUID
    email: str | None = None
    phone: str | None = None
    external_id: str | None = None
    full_name: str | None = None
    metadata: dict = Field(default_factory=dict)


class Conversation(_BaseModel):
    id: UUID
    tenant_id: UUID
    end_customer_id: UUID
    channel: ChannelType
    external_id: str | None = None
    subject: str | None = None
    status: ConversationStatus
    assigned_user_id: UUID | None = None
    last_message_at: datetime | None = None
    nudged_at: datetime | None = None
    resolved_at: datetime | None = None
    is_simulation: bool = False
    created_at: datetime | None = None


HandoffTarget = Literal["helpdesk", "device"]
HandoffStatus = Literal["active", "closed"]


class ConversationHandoff(_BaseModel):
    """Período en que un humano de la marca lleva la conversación y la IA calla."""

    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    target: HandoffTarget
    helpdesk_provider: str | None = None
    external_ticket_id: str | None = None
    status: HandoffStatus
    reason: str
    opened_at: datetime
    last_human_at: datetime | None = None
    expires_at: datetime | None = None
    closed_at: datetime | None = None
    closed_reason: str | None = None


class Message(_BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    role: MessageRole
    direction: MessageDirection
    author_user_id: UUID | None = None
    content: str
    attachments: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class Escalation(_BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    reason: str
    triggered_by_message_id: UUID | None = None
    status: EscalationStatus
    assigned_user_id: UUID | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class KnowledgeChunk(_BaseModel):
    """Resultado de búsqueda RAG. No mapea 1:1 a la tabla — incluye similitud + título del doc."""

    id: UUID
    document_id: UUID
    document_title: str
    content: str
    similarity: float  # 0.0 - 1.0 (1.0 = idéntico)


# ─── AOPs ────────────────────────────────────────────────────────────────────

AopWorkspace = Literal["production", "staging"]


class Aop(_BaseModel):
    id: UUID
    tenant_id: UUID
    slug: str
    workspace: AopWorkspace
    current_version: int
    is_active: bool
    created_at: datetime | None = None


class AopVersion(_BaseModel):
    id: UUID
    aop_id: UUID
    tenant_id: UUID
    version: int
    yaml_frontmatter: dict
    body_markdown: str
    raw_source: str
    created_by: UUID | None = None
    created_at: datetime


class AopWithContent(_BaseModel):
    """AOP + contenido de su versión actual — lo que el compiler y select_aop necesitan."""

    id: UUID
    tenant_id: UUID
    slug: str
    workspace: AopWorkspace
    current_version: int
    is_active: bool = True
    yaml_frontmatter: dict
    body_markdown: str
    raw_source: str


class IntentClassifierRun(_BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    turn_number: int
    primary_slug: str
    primary_confidence: float
    alternative_slug: str | None = None
    alternative_confidence: float | None = None
    ambiguity_detected: bool
    was_reclassification: bool
    human_correction: str | None = None
    created_at: datetime


# ─── Skill Audit Log (Sprint 9.3) ────────────────────────────────────────────

SkillAuditStatus = Literal[
    "success", "failed", "rejected_by_supervisor", "rejected_by_permissions"
]


class TenantSecret(_BaseModel):
    tenant_id: UUID
    pii_salt: str
    created_at: datetime


class SkillAuditLog(_BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    aop_slug: str
    aop_version: int
    skill_slug: str
    skill_tier: str
    idempotency_key: UUID | None = None
    inputs_redacted: dict
    outputs_redacted: dict | None = None
    inputs_hash: str
    confidence: float | None = None
    supervisor_verdict: str | None = None
    status: SkillAuditStatus
    error_message: str | None = None
    latency_ms: int | None = None
    langfuse_trace_id: str | None = None
    created_at: datetime


# ─── Idempotency (Sprint 9.1) ────────────────────────────────────────────────

IdempotencyStatus = Literal["pending", "done"]


class IdempotencyRecord(_BaseModel):
    id: UUID
    tenant_id: UUID
    key: str
    request_path: str
    status: IdempotencyStatus
    response_status: int | None = None
    response_body: dict | None = None
    created_at: datetime
    expires_at: datetime


# ─── Tenant Tool Permissions (Sprint 10) ─────────────────────────────────────


class TenantToolPermission(_BaseModel):
    id: UUID
    tenant_id: UUID
    skill_slug: str
    is_enabled: bool
    threshold_override: float | None = None
    human_approval_required: bool
    enabled_at: datetime | None = None
    enabled_by: UUID | None = None
    l3_autonomy_acknowledged_at: datetime | None = None
    l3_autonomy_acknowledged_by: UUID | None = None
    created_at: datetime | None = None


# ─── Pending Approvals (Sprint 10) ───────────────────────────────────────────

# pending → executing → approved | failed | pending, y pending → rejected (#376). Las
# transiciones las hacen los CAS de `db/queries.py`; ver la migración 20261018000003.
PendingApprovalStatus = Literal["pending", "executing", "approved", "rejected", "failed"]


class PendingApproval(_BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    skill_slug: str
    skill_tier: str
    inputs_raw: dict
    inputs_redacted: dict
    aop_slug: str
    aop_version: int
    langfuse_trace_id: str | None = None
    status: PendingApprovalStatus
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    created_at: datetime | None = None


# ─── Agent Reasoning Events (Sprint 8) ───────────────────────────────────────

ReasoningPhase = Literal["supervisor", "decision", "response"]
ReasoningEventType = Literal[
    "check", "tool_call", "tool_result", "choice", "step_entered", "step_completed"
]
ReasoningStatus = Literal["pending", "done", "error"]


class AgentReasoningEvent(_BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    phase: ReasoningPhase
    event_type: ReasoningEventType
    label: str
    detail: dict | None = None
    status: ReasoningStatus
    seq: int
    created_at: datetime


# ─── Slow Agent (Sprint 11) ───────────────────────────────────────────────────

SlowAgentRunStatus = Literal["running", "completed", "failed"]
ProposalType = Literal["aop_edit", "new_aop", "skill_request", "guardrail_addition"]
ProposalStatus = Literal["pending", "approved", "rejected", "applied"]


class SlowAgentRun(_BaseModel):
    id: UUID
    tenant_id: UUID
    status: SlowAgentRunStatus
    conversations_evaluated: int
    proposals_generated: int
    sonnet_tokens: int
    opus_tokens: int
    cost_usd: float | None = None
    triggered_by: UUID | None = None
    error: str | None = None
    run_started_at: datetime
    run_ended_at: datetime | None = None
    created_at: datetime


class ConversationJudgment(_BaseModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    conversation_id: UUID
    verdict_summary: str | None = None
    proposal_id: UUID | None = None
    created_at: datetime


class ImprovementProposal(_BaseModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    proposal_type: ProposalType
    aop_slug: str | None = None
    diff_markdown: str
    rationale: str
    evidence_conversations: list[UUID] = Field(default_factory=list)
    judge_model_used: str
    judge_confidence: float
    requires_eval_pass: bool
    status: ProposalStatus
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    applied_version: int | None = None
    created_at: datetime


# ─── Internal Users (Bloque 0, Sub-PR 0.8) ───────────────────────────────────

InternalRole = Literal["super_admin", "aide", "qa_km", "ops_manager", "cs_manager"]


class InternalUser(_BaseModel):
    id: UUID
    auth_user_id: UUID
    name: str
    email: str
    role: InternalRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class TenantAssignment(_BaseModel):
    id: UUID
    tenant_id: UUID
    internal_user_id: UUID
    role_in_tenant: str
    assigned_at: datetime
    assigned_by: UUID | None = None
    unassigned_at: datetime | None = None


class RolePermission(_BaseModel):
    role: InternalRole
    permission: str


# ─── Tenant Playbook + Facts (Bloque 1, Sub-PR 1.1 / 1.2) ───────────────────


class TenantPlaybook(_BaseModel):
    """Biblia del cliente. Mantenida por Auyan (qa_km / super_admin).
    Inyectada en el system prompt del agente — NO va al RAG."""

    tenant_id: UUID
    brand_voice: str = ""
    product_overview: str = ""
    policies: str = ""
    escalation_notes: str = ""
    agent_instructions: str = ""
    version: int = 1
    last_edited_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TenantFacts(_BaseModel):
    """Datos factuales del cliente editables por tenant_admin.
    Ejemplos: horarios, teléfono, devoluciones. Inyectados en el system prompt — NO van al RAG."""

    tenant_id: UUID
    data: dict = Field(default_factory=dict)
    version: int = 1
    last_edited_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ─── Tenant Onboarding (Bloque 1, Sub-PR 1.3) ────────────────────────────────


class TenantOnboarding(_BaseModel):
    """Estado del wizard de onboarding guiado del cliente.
    `step_data` agrupa las respuestas por número de paso ("1".."9")."""

    tenant_id: UUID
    current_step: int = 1
    completed_steps: list[int] = Field(default_factory=list)
    step_data: dict = Field(default_factory=dict)
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    last_edited_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OnboardingChecklist(_BaseModel):
    """Condiciones para la transición automática discovery → building.
    El agente pasa a Building sólo cuando las cuatro se cumplen."""

    onboarding_submitted: bool = False
    has_commerce_integration: bool = False
    has_helpdesk_integration: bool = False
    has_knowledge: bool = False

    @property
    def complete(self) -> bool:
        return (
            self.onboarding_submitted
            and self.has_commerce_integration
            and self.has_helpdesk_integration
            and self.has_knowledge
        )


# ─── Tenant Knowledge Submissions (Bloque 1, Sub-PR 1.4) ────────────────────


class TenantKnowledgeSubmission(_BaseModel):
    """Contenido aportado por cliente para revisión QA-KM antes de entrar al RAG."""

    id: UUID
    tenant_id: UUID
    title: str
    source_type: TenantKnowledgeSourceType
    source_url: str | None = None
    original_filename: str | None = None
    content: str = ""
    notes: str | None = None
    status: TenantKnowledgeSubmissionStatus
    metadata: dict = Field(default_factory=dict)
    submitted_by: UUID | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    processed_document_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


# ─── Weekly Reports (Bloque 1, Sub-PR 1.5) ──────────────────────────────────


class WeeklyReport(_BaseModel):
    """Reporte semanal por tenant, revisado por Auyan antes de enviarse al cliente."""

    id: UUID
    tenant_id: UUID
    week_start: str
    week_end: str
    status: WeeklyReportStatus
    subject: str
    recipient_email: str | None = None
    metrics: dict = Field(default_factory=dict)
    narrative: str = ""
    created_by: UUID | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    sent_by: UUID | None = None
    sent_at: datetime | None = None
    postmark_message_id: str | None = None
    send_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ─── Outbound Email (Bloque 1, Sub-PR 1.9) ──────────────────────────────────


class OutboundEmailTemplate(_BaseModel):
    """Template editable por Auyan para emails outbound operativos por tenant."""

    id: UUID
    tenant_id: UUID
    key: str
    name: str
    subject_template: str
    text_body_template: str
    html_body_template: str | None = None
    variables: list[str] = Field(default_factory=list)
    is_active: bool = True
    version: int = 1
    created_by: UUID | None = None
    updated_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OutboundEmailJob(_BaseModel):
    """Job persistente de email outbound listo para ser despachado por worker."""

    id: UUID
    tenant_id: UUID
    template_id: UUID | None = None
    recipient_email: str
    subject: str
    text_body: str
    html_body: str | None = None
    tag: str | None = None
    payload: dict = Field(default_factory=dict)
    status: OutboundEmailJobStatus
    attempts: int = 0
    max_attempts: int = 3
    next_attempt_at: datetime | None = None
    last_attempt_at: datetime | None = None
    sent_at: datetime | None = None
    postmark_message_id: str | None = None
    error: str | None = None
    requested_by: UUID | None = None
    idempotency_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ─── Tenant Integrations (Bloque 0, Sub-PR 0.2) ──────────────────────────────

IntegrationKind = Literal["helpdesk", "commerce", "channel", "llm"]


class TenantIntegration(_BaseModel):
    id: UUID
    tenant_id: UUID
    kind: IntegrationKind
    provider: str
    # credentials_encrypted no se expone en el modelo: se descifra antes de usar.
    config: dict = Field(default_factory=dict)
    is_active: bool
    is_primary_for_kind: bool
    enabled_at: datetime | None = None
    enabled_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


_CHANNEL_LABELS: dict[str, str] = {
    "whatsapp": "WhatsApp",
    "instagram": "Instagram",
    "messenger": "Messenger",
    "tiktok": "TikTok",
    "email": "Email",
    "chat": "Chat",
    "widget": "Widget",
}
# Proveedores que solo dan un canal; sirven de respaldo si la fila no lo guarda.
_PROVIDER_DEFAULT_CHANNEL: dict[str, str] = {"zernio": "whatsapp"}


def integration_label(kind: str, provider: str, channel: str | None = None) -> str:
    """Nombre visible de una integración. Canales: el canal (Zernio es solo el transporte)."""
    if kind == "channel":
        key = (channel or _PROVIDER_DEFAULT_CHANNEL.get(provider) or provider).lower()
        if key in _CHANNEL_LABELS:
            return _CHANNEL_LABELS[key]
        if key == "zernio":  # canal desconocido tras Zernio: nunca mostrar el proveedor
            return "Mensajería"
        return key.replace("_", " ").capitalize()
    return provider.replace("_", " ").capitalize()


class IntegrationSummary(_BaseModel):
    """Vista en lista blanca de una integración activa: nunca credenciales ni config."""

    kind: IntegrationKind
    provider: str
    is_primary: bool
    # Canal concreto (`config->>'channel'`, escalar en lista blanca). Hoy las filas de
    # Zernio no lo guardan: se asume WhatsApp, el único canal que Zernio da (ADR 0010).
    channel: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        """Nombre legible: en canales sale del canal, no del proveedor; el resto, del proveedor."""
        return integration_label(self.kind, self.provider, self.channel)


class IntegrationGroup(_BaseModel):
    """Integraciones activas del tenant agrupadas por kind (canal, helpdesk, tienda…)."""

    kind: IntegrationKind
    integrations: list[IntegrationSummary]


class TenantUsageDaily(_BaseModel):
    id: UUID
    tenant_id: UUID
    date: str  # ISO date string (date no tiene soporte nativo en Pydantic v2 con asyncpg)
    tokens_in: int
    tokens_out: int
    cost_usd: float
    request_count: int
    created_at: datetime
    updated_at: datetime


# ─── Simulator (Bloque 0, Sub-PR 0.10) ───────────────────────────────────────

SimulationRunStatus = Literal["running", "passed", "partial", "failed", "errored"]
TerminationReason = Literal[
    "goal_achieved",
    "max_turns",
    "give_up",
    "escalated_by_agent",
    "agent_loop_detected",
    "error",
]


class UserProfile(_BaseModel):
    """Persona del cliente sintético. Reusable entre scenarios."""

    id: UUID
    tenant_id: UUID
    name: str
    persona: dict = Field(default_factory=dict)  # tone, behavior, give_up_after
    goal: str
    initial_message: str
    language: str = "es"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


class SimulationScenario(_BaseModel):
    """AOP slug + perfil + expected_outcome + mocks + assertions."""

    id: UUID
    tenant_id: UUID
    name: str
    description: str | None = None
    aop_slug: str
    user_profile_id: UUID
    expected_outcome: str
    mock_fixtures: dict = Field(default_factory=dict)
    assertions: dict = Field(default_factory=dict)
    max_turns: int = 8
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


class SimulationRun(_BaseModel):
    """Resultado de correr un scenario. Append-only."""

    id: UUID
    tenant_id: UUID
    scenario_id: UUID | None = None
    aop_slug: str
    aop_version: int | None = None
    conversation_id: UUID | None = None
    batch_id: UUID | None = None
    status: SimulationRunStatus
    termination_reason: TerminationReason | None = None
    turns_count: int | None = None
    transcript: list[dict] | None = None
    judge_eval: dict | None = None
    assertions_results: list[dict] | None = None
    assertions_passed: int | None = None
    assertions_total: int | None = None
    triggered_by: UUID | None = None
    tokens_simulator: int = 0
    tokens_agent: int = 0
    tokens_judge: int = 0
    cost_cents: float | None = None
    langsmith_trace_id: UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


# ─── Billing por resolución (Bloque 2) ──────────────────────────────────────────
# Doc: docs/billing-engine.md. La unidad de cobro es la resolución (el
# agente cerró la conversación sin escalar).

BillingTier = Literal["starter", "growth", "scale", "founding"]


class ResolutionEvent(_BaseModel):
    """Una resolución cobrable (log append-only). `reverted_at` se anota si el cliente
    reabre el mismo thread; el conteo de billing decide si descuenta según la ventana
    de reapertura (docs/billing-engine.md §2.3) — la fila nunca se borra."""

    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    resolved_at: datetime
    reverted_at: datetime | None = None
    created_at: datetime | None = None


class BillingSubscription(_BaseModel):
    """Plan del tenant. floor/included/overage son un SNAPSHOT: cambiar el catálogo de
    tiers (services/billing.py) no altera contratos vigentes."""

    tenant_id: UUID
    tier: BillingTier
    floor_cents: int
    included_resolutions: int
    overage_cents: int
    currency: str = "EUR"
    reopen_window_days: int = 7
    period_anchor_day: int = 1
    status: str = "active"
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BillingUsage(_BaseModel):
    """Uso del periodo actual, calculado (no es fila de DB): resoluciones cobrables vs
    incluidas, overage y total estimado en céntimos. Lo consume el dashboard del cliente."""

    tenant_id: UUID
    tier: BillingTier
    period_start: datetime
    period_end: datetime
    billable_resolutions: int
    included_resolutions: int
    overage_resolutions: int
    floor_cents: int
    overage_cents_total: int
    total_cents: int
    currency: str
