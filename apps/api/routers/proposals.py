"""Endpoints de mejoras propuestas por el slow agent.

GET  /proposals               — lista propuestas del tenant (filtrable por status)
GET  /proposals/{id}          — detalle de una propuesta
POST /proposals/{id}/approve  — aprueba y pre-llena el editor de AOPs
POST /proposals/{id}/reject   — rechaza con comentario opcional

El flujo de approve (opción B — pre-fill editor):
  1. Verifica que la propuesta exista y esté pending.
  2. Para proposal_type='aop_edit': carga el AOP por slug, crea una nueva
     versión con el diff_markdown aplicado al body (append al final).
  3. Retorna aop_id + workspace para que el frontend abra el editor.
  4. Marca la propuesta como 'approved'.

El humano luego edita la nueva versión y la promueve a production manualmente.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id, require_role
from apps.api.db.client import tenant_scope
from apps.api.db.models import ImprovementProposal
from apps.api.db.queries import (
    create_aop,
    get_aop_by_slug,
    get_improvement_proposal,
    get_proposals_metrics,
    list_improvement_proposals,
    save_aop_version,
    update_proposal_status,
)
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proposals", tags=["proposals"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]
AdminDep = Depends(require_role("tenant_admin", "super_admin"))


# ─── Response schemas ─────────────────────────────────────────────────────────


class ProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    run_id: UUID
    proposal_type: str
    aop_slug: str | None
    diff_markdown: str
    rationale: str
    evidence_conversations: list[UUID]
    judge_model_used: str
    judge_confidence: float
    requires_eval_pass: bool
    status: str
    reviewed_by: UUID | None
    reviewed_at: str | None
    review_comment: str | None
    applied_version: int | None

    @classmethod
    def from_model(cls, p: ImprovementProposal) -> ProposalResponse:
        return cls(
            id=p.id,
            tenant_id=p.tenant_id,
            run_id=p.run_id,
            proposal_type=p.proposal_type,
            aop_slug=p.aop_slug,
            diff_markdown=p.diff_markdown,
            rationale=p.rationale,
            evidence_conversations=p.evidence_conversations,
            judge_model_used=p.judge_model_used,
            judge_confidence=float(p.judge_confidence),
            requires_eval_pass=p.requires_eval_pass,
            status=p.status,
            reviewed_by=p.reviewed_by,
            reviewed_at=p.reviewed_at.isoformat() if p.reviewed_at else None,
            review_comment=p.review_comment,
            applied_version=p.applied_version,
        )


class ApproveProposalResponse(BaseModel):
    proposal_id: UUID
    aop_id: UUID
    aop_version: int
    workspace: str
    redirect_to: str


class RejectRequest(BaseModel):
    comment: str | None = Field(None, description="Razón del rechazo (opcional)")


class ProposalMetricsResponse(BaseModel):
    total: int
    pending: int
    approved: int
    rejected: int
    applied: int
    acceptance_rate: float | None
    cost_usd_total: float
    cost_per_accepted_proposal: float | None
    sonnet_tokens_total: int
    opus_tokens_total: int


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[ProposalResponse],
    summary="Lista propuestas de mejora del tenant",
)
async def list_proposals(
    tenant_id: TenantIdDep,
    proposal_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ProposalResponse]:
    async with tenant_scope(tenant_id) as conn:
        proposals = await list_improvement_proposals(
            conn, tenant_id, status=proposal_status, limit=limit, offset=offset
        )
    return [ProposalResponse.from_model(p) for p in proposals]


@router.get(
    "/metrics",
    response_model=ProposalMetricsResponse,
    summary="Métricas del slow agent: tasa de aceptación y costo",
)
async def get_metrics(
    tenant_id: TenantIdDep,
) -> ProposalMetricsResponse:
    async with tenant_scope(tenant_id) as conn:
        data = await get_proposals_metrics(conn, tenant_id)
    return ProposalMetricsResponse(
        total=data["total"],
        pending=data["pending"],
        approved=data["approved"],
        rejected=data["rejected"],
        applied=data["applied"],
        acceptance_rate=(
            float(data["acceptance_rate"]) if data["acceptance_rate"] is not None else None
        ),
        cost_usd_total=float(data["cost_usd_total"]),
        cost_per_accepted_proposal=(
            float(data["cost_per_accepted_proposal"])
            if data["cost_per_accepted_proposal"] is not None
            else None
        ),
        sonnet_tokens_total=data["sonnet_tokens_total"],
        opus_tokens_total=data["opus_tokens_total"],
    )


@router.get(
    "/{proposal_id}",
    response_model=ProposalResponse,
    summary="Detalle de una propuesta de mejora",
)
async def get_proposal(
    proposal_id: UUID,
    tenant_id: TenantIdDep,
) -> ProposalResponse:
    async with tenant_scope(tenant_id) as conn:
        proposal = await get_improvement_proposal(conn, tenant_id, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="proposal_not_found")
    return ProposalResponse.from_model(proposal)


@router.post(
    "/{proposal_id}/approve",
    response_model=ApproveProposalResponse,
    summary="Aprueba propuesta y pre-llena el editor de AOPs",
    dependencies=[AdminDep],
)
async def approve_proposal(
    proposal_id: UUID,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> ApproveProposalResponse:
    async with tenant_scope(tenant_id) as conn:
        proposal = await get_improvement_proposal(conn, tenant_id, proposal_id)
        if proposal is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="proposal_not_found")
        if proposal.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La propuesta ya tiene status '{proposal.status}', no se puede aprobar.",
            )

        if proposal.proposal_type == "aop_edit" and proposal.aop_slug:
            existing_aop = await get_aop_by_slug(conn, tenant_id, proposal.aop_slug)
            if existing_aop is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"AOP '{proposal.aop_slug}' no encontrado para pre-fill.",
                )
            # Aplica el diff al body del AOP (append como sección nueva)
            new_body = (
                existing_aop.body_markdown.rstrip()
                + "\n\n---\n\n## Propuesta de mejora (revisar y editar)\n\n"
                + proposal.diff_markdown
            )
            new_raw = (
                "---\n"
                + _dict_to_yaml_frontmatter(existing_aop.yaml_frontmatter)
                + "\n---\n\n"
                + new_body
            )
            version = await save_aop_version(
                conn,
                tenant_id=tenant_id,
                aop_id=existing_aop.id,
                yaml_frontmatter=existing_aop.yaml_frontmatter,
                body_markdown=new_body,
                raw_source=new_raw,
                created_by=auth.user_id,
            )
            aop_id = existing_aop.id
            aop_version = version.version
            workspace = str(existing_aop.workspace)

        elif proposal.proposal_type == "new_aop":
            # Para new_aop, crea un borrador en staging con el diff como body
            import yaml as _yaml

            placeholder_slug = f"propuesta_{str(proposal_id)[:8]}"
            frontmatter: dict = {
                "slug": placeholder_slug,
                "name": f"Propuesta {str(proposal_id)[:8]} (editar)",
                "triggers": {"keywords": [], "description": proposal.diff_markdown[:100]},
                "allowed_skills": [],
                "confidence_threshold": 0.75,
                "escalation_triggers": [],
            }
            raw_source = (
                "---\n"
                + _yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False)
                + "---\n\n"
                + proposal.diff_markdown
            )
            # parse properly
            parts = raw_source.strip().split("---", 2)
            fm_parsed = _yaml.safe_load(parts[1]) or {}
            body_md = parts[2].strip()

            new_aop = await create_aop(
                conn,
                tenant_id=tenant_id,
                slug=placeholder_slug,
                workspace="staging",
                yaml_frontmatter=fm_parsed,
                body_markdown=body_md,
                raw_source=raw_source,
                created_by=auth.user_id,
            )
            aop_id = new_aop.id
            aop_version = new_aop.current_version
            workspace = "staging"

        else:
            # skill_request y guardrail_addition no tocan el AOP editor directamente
            # Marcar como aprobado sin pre-fill
            await update_proposal_status(
                conn, tenant_id, proposal_id,
                status="approved",
                reviewed_by=auth.user_id,
                review_comment="Aprobado para seguimiento manual",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Propuestas de tipo '{proposal.proposal_type}' no generan un AOP "
                    "automáticamente. Revísalas manualmente y márcalas como aplicadas."
                ),
            )

        await update_proposal_status(
            conn, tenant_id, proposal_id,
            status="approved",
            reviewed_by=auth.user_id,
            applied_version=aop_version,
        )

    logger.info(
        "proposal.approved tenant=%s proposal=%s aop=%s version=%d",
        tenant_id, proposal_id, aop_id, aop_version,
    )

    return ApproveProposalResponse(
        proposal_id=proposal_id,
        aop_id=aop_id,
        aop_version=aop_version,
        workspace=workspace,
        redirect_to=f"/tenants/{tenant_id}/aops/{aop_id}",
    )


@router.post(
    "/{proposal_id}/reject",
    status_code=status.HTTP_200_OK,
    response_model=ProposalResponse,
    summary="Rechaza una propuesta de mejora",
    dependencies=[AdminDep],
)
async def reject_proposal(
    proposal_id: UUID,
    body: RejectRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> ProposalResponse:
    async with tenant_scope(tenant_id) as conn:
        proposal = await get_improvement_proposal(conn, tenant_id, proposal_id)
        if proposal is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="proposal_not_found")
        if proposal.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La propuesta ya tiene status '{proposal.status}'.",
            )
        updated = await update_proposal_status(
            conn, tenant_id, proposal_id,
            status="rejected",
            reviewed_by=auth.user_id,
            review_comment=body.comment,
        )

    logger.info("proposal.rejected tenant=%s proposal=%s", tenant_id, proposal_id)
    assert updated is not None
    return ProposalResponse.from_model(updated)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _dict_to_yaml_frontmatter(d: dict) -> str:
    import yaml
    return yaml.dump(d, allow_unicode=True, default_flow_style=False).rstrip()
