"""Judge del slow agent — analiza una conversación y propone mejoras al AOP.

Flujo two-step:
  1. Sonnet analiza el transcript.
  2. Si confidence < 0.7 o flag_for_opus=True → Opus hace el análisis final.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from typing import Literal

from anthropic import AsyncAnthropic
from apps.api.core.config import get_models
from apps.api.integrations.anthropic_client import call_claude_text
from apps.api.integrations.pricing import LLMUsage, compute_llm_cost
from apps.api.slow_agent.prompts import JUDGE_SYSTEM_PROMPT
from apps.api.slow_agent.transcript import ConversationTranscript, format_for_judge

logger = logging.getLogger(__name__)

OPUS_CONFIDENCE_THRESHOLD = 0.7
JUDGE_MAX_TOKENS = 2048


@dataclass(frozen=True)
class JudgeVerdict:
    should_propose: bool
    proposal_type: str | None
    aop_slug: str | None
    diff_markdown: str
    rationale: str
    confidence: float
    flag_for_opus: bool
    model_used: str
    usage: LLMUsage
    # El veredicto de Sonnet que se descartó al escalar a Opus: su llamada también se paga.
    escalated_from: JudgeVerdict | None = None

    @property
    def input_tokens(self) -> int:
        return self.usage.prompt_tokens

    @property
    def output_tokens(self) -> int:
        return self.usage.output_tokens

    @property
    def cost_usd(self) -> float:
        return compute_llm_cost(self.model_used, self.usage)

    @property
    def calls(self) -> list[JudgeVerdict]:
        """Cada llamada al LLM que produjo este veredicto, en orden."""
        earlier = self.escalated_from.calls if self.escalated_from else []
        return [*earlier, self]


JudgeRole = Literal["slow_agent_model", "judge_opus_model"]


async def _call_judge(
    anthropic: AsyncAnthropic,
    transcript: ConversationTranscript,
    role: JudgeRole,
) -> JudgeVerdict:
    formatted = format_for_judge(transcript)
    model: str = getattr(get_models(), role)
    reply = await call_claude_text(
        client=anthropic,
        model=model,
        role=role,
        max_tokens=JUDGE_MAX_TOKENS,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": formatted}],
    )
    raw = reply.text.strip()
    usage = reply.usage

    try:
        data: dict = json.loads(raw)
    except json.JSONDecodeError:
        # Si el modelo no devuelve JSON limpio, extraemos el bloque JSON del texto
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
        else:
            logger.warning(
                "judge_json_parse_failed model=%s conv=%s",
                model,
                transcript.conversation.id,
            )
            return JudgeVerdict(
                should_propose=False,
                proposal_type=None,
                aop_slug=None,
                diff_markdown="",
                rationale="",
                confidence=0.0,
                flag_for_opus=False,
                model_used=model,
                usage=usage,
            )

    return JudgeVerdict(
        should_propose=bool(data.get("should_propose", False)),
        proposal_type=data.get("proposal_type"),
        aop_slug=data.get("aop_slug"),
        diff_markdown=data.get("diff_markdown", ""),
        rationale=data.get("rationale", ""),
        confidence=float(data.get("confidence", 0.0)),
        flag_for_opus=bool(data.get("flag_for_opus", False)),
        model_used=model,
        usage=usage,
    )


async def judge_conversation(
    anthropic: AsyncAnthropic,
    transcript: ConversationTranscript,
) -> JudgeVerdict:
    """Analiza el transcript. Escalona a Opus si Sonnet duda."""
    sonnet_verdict = await _call_judge(anthropic, transcript, "slow_agent_model")

    if sonnet_verdict.confidence < OPUS_CONFIDENCE_THRESHOLD or sonnet_verdict.flag_for_opus:
        logger.info(
            "slow_agent_escalating_to_opus conv=%s sonnet_confidence=%.2f flag=%s",
            transcript.conversation.id,
            sonnet_verdict.confidence,
            sonnet_verdict.flag_for_opus,
        )
        opus_verdict = await _call_judge(anthropic, transcript, "judge_opus_model")
        return replace(opus_verdict, escalated_from=sonnet_verdict)

    return sonnet_verdict
