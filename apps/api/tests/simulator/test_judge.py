"""Tests del judge.py — sin llamadas reales al LLM."""

from __future__ import annotations

import pytest
from apps.api.core.config import get_models
from apps.api.integrations.pricing import LLMUsage
from apps.api.simulator.judge import (
    SimulatorJudgeVerdict,
    _fallback_verdict,
    _parse_verdict,
    normalize_judge_model,
    verdict_to_dict,
)

SONNET = get_models().judge_sonnet_model
OPUS = get_models().judge_opus_model


class TestParseVerdict:
    def test_valid_json(self):
        raw = """{
            "reasoning_score": 8,
            "knowledge_score": 7,
            "tools_score": 9,
            "brand_voice_score": 8,
            "overall_score": 8.0,
            "verdict": "pass",
            "reasoning_explanation": "Bien",
            "knowledge_explanation": "Correcto",
            "tools_explanation": "OK",
            "brand_voice_explanation": "Adecuado",
            "judge_goal_achieved": true,
            "judge_goal_explanation": "Goal logrado",
            "suggestions": "Nada que cambiar"
        }"""
        v = _parse_verdict(raw, LLMUsage(input_tokens=500, output_tokens=100), model_used=SONNET)
        assert v.reasoning_score == 8
        assert v.verdict == "pass"
        assert v.judge_goal_achieved
        assert v.model_used == SONNET
        assert v.input_tokens == 500
        assert v.output_tokens == 100

    def test_verdict_clamped_to_fail_on_invalid(self):
        raw = '{"reasoning_score": 5, "knowledge_score": 5, "tools_score": 5, "brand_voice_score": 5, "overall_score": 5.0, "verdict": "INVALID", "reasoning_explanation": "", "knowledge_explanation": "", "tools_explanation": "", "brand_voice_explanation": "", "judge_goal_achieved": false, "judge_goal_explanation": "", "suggestions": ""}'
        v = _parse_verdict(raw, LLMUsage(), model_used=SONNET)
        assert v.verdict == "fail"

    def test_fallback_on_bad_json(self):
        v = _parse_verdict("not json", LLMUsage(input_tokens=10, output_tokens=5), model_used=SONNET)
        assert v.verdict == "fail"
        assert v.overall_score == 0.0
        assert v.reasoning_explanation == "parse_error"

    def test_json_embedded_in_text(self):
        raw = 'Sure, here it is: {"reasoning_score": 7, "knowledge_score": 7, "tools_score": 7, "brand_voice_score": 7, "overall_score": 7.0, "verdict": "pass", "reasoning_explanation": "x", "knowledge_explanation": "x", "tools_explanation": "x", "brand_voice_explanation": "x", "judge_goal_achieved": true, "judge_goal_explanation": "x", "suggestions": "x"}'
        v = _parse_verdict(raw, LLMUsage(), model_used=SONNET)
        assert v.verdict == "pass"


class TestVerdictCost:
    def test_opus_judge_charges_opus_4_7_rates_with_cache_read(self):
        usage = LLMUsage(input_tokens=2000, cache_read_tokens=10_000, output_tokens=400)
        v = _parse_verdict("not json", usage, model_used=OPUS)
        # 2000*$5 + 10_000*$0.50 + 400*$25 = $0.025
        assert v.cost_usd == pytest.approx(0.025)
        assert v.input_tokens == 12_000


class TestFallbackVerdict:
    def test_returns_zeroed_fail_verdict(self):
        v = _fallback_verdict(LLMUsage(input_tokens=100, output_tokens=50), model_used=SONNET)
        assert v.verdict == "fail"
        assert v.overall_score == 0.0
        assert v.input_tokens == 100
        assert v.output_tokens == 50
        assert v.reasoning_explanation == "parse_error"


class TestNormalizeJudgeModel:
    def test_defaults_to_sonnet(self):
        assert normalize_judge_model(None) == SONNET
        assert normalize_judge_model("sonnet") == SONNET

    def test_allows_opus_explicitly(self):
        assert normalize_judge_model("opus") == OPUS
        assert normalize_judge_model(OPUS) == OPUS

    def test_rejects_unknown_model(self):
        try:
            normalize_judge_model("claude-future-99")
        except ValueError as exc:
            assert "unsupported_simulator_judge_model" in str(exc)
        else:
            raise AssertionError("expected ValueError")


class TestVerdictToDict:
    def test_serializes_all_fields(self):
        v = SimulatorJudgeVerdict(
            reasoning_score=8,
            knowledge_score=7,
            tools_score=9,
            brand_voice_score=8,
            overall_score=8.0,
            verdict="pass",
            reasoning_explanation="ok",
            knowledge_explanation="ok",
            tools_explanation="ok",
            brand_voice_explanation="ok",
            judge_goal_achieved=True,
            judge_goal_explanation="logrado",
            suggestions="ninguna",
            model_used=SONNET,
            usage=LLMUsage(input_tokens=100, output_tokens=50),
        )
        d = verdict_to_dict(v)
        assert d["verdict"] == "pass"
        assert d["overall_score"] == 8.0
        assert d["judge_goal_achieved"] is True
        assert d["model_used"] == SONNET
