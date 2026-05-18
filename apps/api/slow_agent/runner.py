"""Orquestador del slow agent.

Flujo por tenant:
  1. Crea un slow_agent_run en DB.
  2. Carga conversaciones candidatas (últimos since_days días).
  3. Filtra con la estrategia de sampling (escaladas + ~10% resueltas).
  4. Para cada conversación:
     a. Carga mensajes + skill_audit_log + AOP activo del estado de la conv.
     b. Construye transcript.
     c. Llama al judge.
     d. Si hay propuesta, persiste en improvement_proposals.
     e. Registra judgment.
  5. Actualiza el run con stats finales.

Caps duros para no quemar presupuesto:
  - max_conversations_per_run (default 50)
  - costos estimados basados en pricing Sonnet/Opus (aproximación)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from anthropic import AsyncAnthropic
from apps.api.aops.compiler import compile_aop
from apps.api.db.client import tenant_scope
from apps.api.db.models import Conversation
from apps.api.db.queries import (
    get_aop_by_slug,
    get_last_intent_for_conversation,
    get_messages_for_conversation,
    get_open_escalation_for_conversation,
    get_tenant_configuration,
    get_tenant_pii_salt,
    insert_conversation_judgment,
    insert_improvement_proposal,
    insert_slow_agent_run,
    list_conversations,
    list_judged_conversation_ids,
    list_skill_audit_log,
    update_slow_agent_run,
)
from apps.api.slow_agent.judge import judge_conversation
from apps.api.slow_agent.sampling import filter_candidates
from apps.api.slow_agent.transcript import build_transcript

logger = logging.getLogger(__name__)

# Pricing aproximado (USD por 1M tokens, mayo 2026)
_SONNET_INPUT_COST_PER_M = 3.0
_SONNET_OUTPUT_COST_PER_M = 15.0
_OPUS_INPUT_COST_PER_M = 15.0
_OPUS_OUTPUT_COST_PER_M = 75.0


def _estimate_cost(
    sonnet_in: int,
    sonnet_out: int,
    opus_in: int,
    opus_out: int,
) -> float:
    return (
        sonnet_in * _SONNET_INPUT_COST_PER_M / 1_000_000
        + sonnet_out * _SONNET_OUTPUT_COST_PER_M / 1_000_000
        + opus_in * _OPUS_INPUT_COST_PER_M / 1_000_000
        + opus_out * _OPUS_OUTPUT_COST_PER_M / 1_000_000
    )


@dataclass
class RunStats:
    conversations_evaluated: int = 0
    proposals_generated: int = 0
    sonnet_input_tokens: int = 0
    sonnet_output_tokens: int = 0
    opus_input_tokens: int = 0
    opus_output_tokens: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def sonnet_tokens(self) -> int:
        return self.sonnet_input_tokens + self.sonnet_output_tokens

    @property
    def opus_tokens(self) -> int:
        return self.opus_input_tokens + self.opus_output_tokens

    @property
    def cost_usd(self) -> float:
        return _estimate_cost(
            self.sonnet_input_tokens,
            self.sonnet_output_tokens,
            self.opus_input_tokens,
            self.opus_output_tokens,
        )


async def run_slow_agent_for_tenant(
    anthropic: AsyncAnthropic,
    tenant_id: UUID,
    since_days: int = 7,
    max_conversations: int = 50,
    triggered_by: UUID | None = None,
) -> RunStats:
    """Ejecuta el slow agent para un tenant. Retorna las estadísticas del run."""
    stats = RunStats()

    async with tenant_scope(tenant_id) as conn:
        run = await insert_slow_agent_run(conn, tenant_id, triggered_by)
        run_id = run.id
        logger.info(
            "slow_agent_run_started tenant=%s run=%s since_days=%d max=%d",
            tenant_id, run_id, since_days, max_conversations,
        )

    try:
        async with tenant_scope(tenant_id) as conn:
            already_judged = await list_judged_conversation_ids(conn, tenant_id, since_days)
            all_convs = await list_conversations(conn, tenant_id, limit=500)
            pii_salt = await get_tenant_pii_salt(conn, tenant_id)
            tenant_config = await get_tenant_configuration(conn, tenant_id)

        cutoff = datetime.now(tz=UTC) - timedelta(days=since_days)
        recent_convs = [
            c for c in all_convs
            if c.created_at and c.created_at.replace(tzinfo=UTC) >= cutoff
        ]

        candidates = filter_candidates(recent_convs, already_judged, max_conversations)
        logger.info(
            "slow_agent_candidates tenant=%s total=%d candidates=%d",
            tenant_id, len(recent_convs), len(candidates),
        )

        for conv in candidates:
            try:
                await _judge_one(
                    anthropic=anthropic,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    conv=conv,
                    pii_salt=pii_salt,
                    tenant_config=tenant_config,
                    stats=stats,
                )
            except Exception:
                logger.exception(
                    "slow_agent_conv_error tenant=%s conv=%s", tenant_id, conv.id
                )
                stats.errors.append(str(conv.id))

        error_str = "; ".join(stats.errors) if stats.errors else None
        async with tenant_scope(tenant_id) as conn:
            await update_slow_agent_run(
                conn, run_id, tenant_id,
                status="completed",
                conversations_evaluated=stats.conversations_evaluated,
                proposals_generated=stats.proposals_generated,
                sonnet_tokens=stats.sonnet_tokens,
                opus_tokens=stats.opus_tokens,
                cost_usd=stats.cost_usd,
                error=error_str,
            )

        logger.info(
            "slow_agent_run_completed tenant=%s run=%s convs=%d proposals=%d cost=%.4f",
            tenant_id, run_id,
            stats.conversations_evaluated, stats.proposals_generated, stats.cost_usd,
        )

    except Exception as exc:
        logger.exception("slow_agent_run_failed tenant=%s run=%s", tenant_id, run_id)
        async with tenant_scope(tenant_id) as conn:
            await update_slow_agent_run(
                conn, run_id, tenant_id,
                status="failed",
                conversations_evaluated=stats.conversations_evaluated,
                proposals_generated=stats.proposals_generated,
                sonnet_tokens=stats.sonnet_tokens,
                opus_tokens=stats.opus_tokens,
                cost_usd=stats.cost_usd,
                error=str(exc),
            )
        raise

    return stats


async def _judge_one(
    anthropic: AsyncAnthropic,
    tenant_id: UUID,
    run_id: UUID,
    conv: Conversation,
    pii_salt: str,
    tenant_config: object,
    stats: RunStats,
) -> None:
    async with tenant_scope(tenant_id) as conn:
        messages = await get_messages_for_conversation(conn, tenant_id, conv.id)
        audit_entries = await list_skill_audit_log(conn, tenant_id, conv.id)

        # Intenta cargar el AOP activo del último intent classifier run
        aop = None
        aop_prompt: str | None = None
        try:
            slug = await get_last_intent_for_conversation(conn, tenant_id, conv.id)
            if slug:
                aop = await get_aop_by_slug(conn, tenant_id, slug)
                if aop:
                    compiled = compile_aop(aop, tenant_config)  # type: ignore[arg-type]
                    aop_prompt = compiled.system_prompt
        except Exception:
            pass  # AOP no disponible — el judge trabajará sin él

        escalation_reason: str | None = None
        if conv.status == "escalated":
            try:
                esc = await get_open_escalation_for_conversation(conn, tenant_id, conv.id)
                if esc:
                    escalation_reason = esc.reason
            except Exception:
                pass

    transcript = build_transcript(
        conv, messages, audit_entries, aop, aop_prompt, pii_salt, escalation_reason
    )

    verdict = await judge_conversation(anthropic, transcript)
    stats.conversations_evaluated += 1

    # Acumula tokens por modelo
    from apps.api.slow_agent.judge import SONNET_JUDGE_MODEL
    if verdict.model_used == SONNET_JUDGE_MODEL:
        stats.sonnet_input_tokens += verdict.input_tokens
        stats.sonnet_output_tokens += verdict.output_tokens
    else:
        stats.opus_input_tokens += verdict.input_tokens
        stats.opus_output_tokens += verdict.output_tokens

    proposal_id: UUID | None = None
    if verdict.should_propose and verdict.proposal_type:
        async with tenant_scope(tenant_id) as conn:
            proposal = await insert_improvement_proposal(
                conn,
                tenant_id=tenant_id,
                run_id=run_id,
                proposal_type=verdict.proposal_type,
                diff_markdown=verdict.diff_markdown,
                rationale=verdict.rationale,
                evidence_conversations=[conv.id],
                judge_model_used=verdict.model_used,
                judge_confidence=verdict.confidence,
                aop_slug=verdict.aop_slug,
            )
            proposal_id = proposal.id
            stats.proposals_generated += 1
            logger.info(
                "slow_agent_proposal_created tenant=%s conv=%s type=%s slug=%s",
                tenant_id, conv.id, verdict.proposal_type, verdict.aop_slug,
            )

    async with tenant_scope(tenant_id) as conn:
        await insert_conversation_judgment(
            conn,
            tenant_id=tenant_id,
            run_id=run_id,
            conversation_id=conv.id,
            verdict_summary=f"should_propose={verdict.should_propose} confidence={verdict.confidence:.2f}",
            proposal_id=proposal_id,
        )
