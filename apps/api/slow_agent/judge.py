"""Judge del slow agent — analiza una conversación y propone mejoras al AOP.

Flujo two-step:
  1. Sonnet analiza el transcript.
  2. Si confidence < 0.7 o flag_for_opus=True → Opus hace el análisis final.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from apps.api.slow_agent.prompts import JUDGE_SYSTEM_PROMPT
from apps.api.slow_agent.transcript import ConversationTranscript, format_for_judge

logger = logging.getLogger(__name__)

SONNET_JUDGE_MODEL = "claude-sonnet-4-6"
OPUS_JUDGE_MODEL = "claude-opus-4-7"
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
    input_tokens: int
    output_tokens: int


async def _call_judge(
    anthropic: AsyncAnthropic,
    transcript: ConversationTranscript,
    model: str,
) -> JudgeVerdict:
    formatted = format_for_judge(transcript)
    response = await anthropic.messages.create(
        model=model,
        max_tokens=JUDGE_MAX_TOKENS,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": formatted}],
    )
    raw = response.content[0].text.strip()

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
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
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
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


async def judge_conversation(
    anthropic: AsyncAnthropic,
    transcript: ConversationTranscript,
) -> JudgeVerdict:
    """Analiza el transcript. Escalona a Opus si Sonnet duda."""
    sonnet_verdict = await _call_judge(anthropic, transcript, SONNET_JUDGE_MODEL)

    if sonnet_verdict.confidence < OPUS_CONFIDENCE_THRESHOLD or sonnet_verdict.flag_for_opus:
        logger.info(
            "slow_agent_escalating_to_opus conv=%s sonnet_confidence=%.2f flag=%s",
            transcript.conversation.id,
            sonnet_verdict.confidence,
            sonnet_verdict.flag_for_opus,
        )
        return await _call_judge(anthropic, transcript, OPUS_JUDGE_MODEL)

    return sonnet_verdict
