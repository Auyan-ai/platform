"""Judge del simulador — evalúa 4 dimensiones con Sonnet por defecto.

Opus queda disponible para calibraciones explícitas, pero la corrida normal usa
Sonnet para mantener el batch bajo control de coste.

Prompt caching habilitado en el system prompt fijo.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from typing import Literal

from anthropic import AsyncAnthropic
from apps.api.core.config import get_models
from apps.api.db.models import SimulationScenario
from apps.api.integrations.anthropic_client import CallTrace, call_claude_text
from apps.api.integrations.pricing import LLMUsage, compute_llm_cost
from apps.api.simulator.prompts import SIM_JUDGE_SYSTEM_PROMPT
from apps.api.simulator.transcript import SimulatorTranscript, format_for_sim_judge

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_ALIAS: Literal["sonnet"] = "sonnet"
JudgeModelAlias = Literal["sonnet", "opus"]
JUDGE_MAX_TOKENS = 1024
JUDGE_TIMEOUT_SECONDS = 90  # tope por llamada analizando transcript

SimVerdict = Literal["pass", "partial", "fail"]


@dataclass(frozen=True)
class SimulatorJudgeVerdict:
    reasoning_score: int
    knowledge_score: int
    tools_score: int
    brand_voice_score: int
    overall_score: float
    verdict: SimVerdict
    reasoning_explanation: str
    knowledge_explanation: str
    tools_explanation: str
    brand_voice_explanation: str
    judge_goal_achieved: bool
    judge_goal_explanation: str
    suggestions: str
    model_used: str
    usage: LLMUsage
    # Con qué salió la llamada y cómo terminó (va al run de LangSmith).
    call: CallTrace | None = None

    @property
    def input_tokens(self) -> int:
        return self.usage.prompt_tokens

    @property
    def output_tokens(self) -> int:
        return self.usage.output_tokens

    @property
    def cost_usd(self) -> float:
        return compute_llm_cost(self.model_used, self.usage)


async def judge_simulation(
    anthropic: AsyncAnthropic,
    transcript: SimulatorTranscript,
    scenario: SimulationScenario,
    *,
    judge_model: JudgeModelAlias | str = DEFAULT_JUDGE_ALIAS,
) -> SimulatorJudgeVerdict:
    """Llama al judge y retorna el veredicto 4-dim."""
    formatted = format_for_sim_judge(transcript)
    model = normalize_judge_model(judge_model)

    reply = await call_claude_text(
        client=anthropic,
        model=model,
        role=(
            "judge_opus_model" if model == get_models().judge_opus_model else "judge_sonnet_model"
        ),
        max_tokens=JUDGE_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": SIM_JUDGE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": formatted}],
        timeout_seconds=JUDGE_TIMEOUT_SECONDS,
    )
    if reply.refusal_reason is not None:
        # Un refusal no es un JSON vacío: veredicto conservador con la razón explícita.
        verdict = _fallback_verdict(reply.usage, model_used=model, reason=reply.refusal_reason)
    else:
        verdict = _parse_verdict(reply.text.strip() or "{}", reply.usage, model_used=model)
    return replace(verdict, call=reply.call)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def normalize_judge_model(judge_model: JudgeModelAlias | str | None) -> str:
    """Normaliza alias CLI/API a IDs reales de Anthropic."""
    models = get_models()
    if judge_model in (None, "", "sonnet", models.judge_sonnet_model):
        return models.judge_sonnet_model
    if judge_model in ("opus", models.judge_opus_model):
        return models.judge_opus_model
    raise ValueError(f"unsupported_simulator_judge_model:{judge_model}")


def _parse_verdict(
    raw: str,
    usage: LLMUsage,
    *,
    model_used: str,
) -> SimulatorJudgeVerdict:
    """Parsea el JSON del judge. Retorna veredicto conservador en caso de error."""
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data: dict = json.loads(raw[start:end])
        else:
            data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("sim_judge_json_parse_failed raw=%s", raw[:200])
        return _fallback_verdict(usage, model_used=model_used)

    r = int(data.get("reasoning_score", 0))
    k = int(data.get("knowledge_score", 0))
    t = int(data.get("tools_score", 0))
    b = int(data.get("brand_voice_score", 0))
    overall = float(data.get("overall_score", (r + k + t + b) / 4))
    raw_verdict = str(data.get("verdict", "fail"))
    verdict: SimVerdict = raw_verdict if raw_verdict in ("pass", "partial", "fail") else "fail"  # type: ignore[assignment]

    return SimulatorJudgeVerdict(
        reasoning_score=r,
        knowledge_score=k,
        tools_score=t,
        brand_voice_score=b,
        overall_score=overall,
        verdict=verdict,
        reasoning_explanation=str(data.get("reasoning_explanation", "")),
        knowledge_explanation=str(data.get("knowledge_explanation", "")),
        tools_explanation=str(data.get("tools_explanation", "")),
        brand_voice_explanation=str(data.get("brand_voice_explanation", "")),
        judge_goal_achieved=bool(data.get("judge_goal_achieved", False)),
        judge_goal_explanation=str(data.get("judge_goal_explanation", "")),
        suggestions=str(data.get("suggestions", "")),
        model_used=model_used,
        usage=usage,
    )


def _fallback_verdict(
    usage: LLMUsage,
    *,
    model_used: str,
    reason: str = "parse_error",
) -> SimulatorJudgeVerdict:
    return SimulatorJudgeVerdict(
        reasoning_score=0,
        knowledge_score=0,
        tools_score=0,
        brand_voice_score=0,
        overall_score=0.0,
        verdict="fail",
        reasoning_explanation=reason,
        knowledge_explanation=reason,
        tools_explanation=reason,
        brand_voice_explanation=reason,
        judge_goal_achieved=False,
        judge_goal_explanation=reason,
        suggestions="",
        model_used=model_used,
        usage=usage,
    )


def verdict_to_dict(v: SimulatorJudgeVerdict) -> dict:
    """Serializa para persistir en JSONB."""
    return {
        "reasoning_score": v.reasoning_score,
        "knowledge_score": v.knowledge_score,
        "tools_score": v.tools_score,
        "brand_voice_score": v.brand_voice_score,
        "overall_score": v.overall_score,
        "verdict": v.verdict,
        "reasoning_explanation": v.reasoning_explanation,
        "knowledge_explanation": v.knowledge_explanation,
        "tools_explanation": v.tools_explanation,
        "brand_voice_explanation": v.brand_voice_explanation,
        "judge_goal_achieved": v.judge_goal_achieved,
        "judge_goal_explanation": v.judge_goal_explanation,
        "suggestions": v.suggestions,
        "model_used": v.model_used,
        "input_tokens": v.input_tokens,
        "output_tokens": v.output_tokens,
    }
