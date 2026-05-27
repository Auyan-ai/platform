"""Modelos Pydantic que reflejan filas de Supabase.

Sólo incluyen los campos que el código de la API y el grafo realmente usan.
Si más adelante hace falta un campo, se agrega aquí — no expongas columnas
"por las dudas".
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Enums espejados desde supabase/migrations/20260513000000_initial_schema.sql
MessageRole = Literal["customer", "agent_ai", "agent_human", "system"]
MessageDirection = Literal["inbound", "outbound"]
ConversationStatus = Literal[
    "open", "pending", "resolved", "escalated", "closed", "closed_abandoned"
]
EscalationStatus = Literal["pending", "claimed", "resolved"]
ChannelType = Literal[
    "email", "chat", "widget", "whatsapp", "instagram", "zendesk", "intercom", "chatwoot"
]
UserRole = Literal["super_admin", "tenant_admin"]
AgentLifecycleState = Literal[
    "initial", "discovery", "building", "shadow", "ramping", "active", "paused", "churned"
]


class _BaseModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Tenant(_BaseModel):
    id: UUID
    slug: str
    name: str
    status: str
    agent_lifecycle_state: AgentLifecycleState = "initial"


class TenantConfiguration(_BaseModel):
    tenant_id: UUID
    agent_model: str
    escalation_threshold: float
    active_channels: list[ChannelType] = Field(default_factory=list)
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
    is_simulation: bool = False
    created_at: datetime | None = None


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
    created_at: datetime | None = None


# ─── Pending Approvals (Sprint 10) ───────────────────────────────────────────

PendingApprovalStatus = Literal["pending", "approved", "rejected"]


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
    """Estado del wizard self-serve del cliente.
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
    started_at: datetime | None = None
    completed_at: datetime | None = None
