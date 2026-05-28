"""Tests del judge.py — sin llamadas reales al LLM."""

from __future__ import annotations

from apps.api.simulator.judge import (
    DEFAULT_JUDGE_MODEL,
    OPUS_JUDGE_MODEL,
    SONNET_JUDGE_MODEL,
    SimulatorJudgeVerdict,
    _fallback_verdict,
    _parse_verdict,
    normalize_judge_model,
    verdict_to_dict,
)


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
        v = _parse_verdict(raw, 500, 100)
        assert v.reasoning_score == 8
        assert v.verdict == "pass"
        assert v.judge_goal_achieved
        assert v.model_used == DEFAULT_JUDGE_MODEL
        assert v.input_tokens == 500
        assert v.output_tokens == 100

    def test_verdict_clamped_to_fail_on_invalid(self):
        raw = '{"reasoning_score": 5, "knowledge_score": 5, "tools_score": 5, "brand_voice_score": 5, "overall_score": 5.0, "verdict": "INVALID", "reasoning_explanation": "", "knowledge_explanation": "", "tools_explanation": "", "brand_voice_explanation": "", "judge_goal_achieved": false, "judge_goal_explanation": "", "suggestions": ""}'
        v = _parse_verdict(raw, 0, 0)
        assert v.verdict == "fail"

    def test_fallback_on_bad_json(self):
        v = _parse_verdict("not json", 10, 5)
        assert v.verdict == "fail"
        assert v.overall_score == 0.0
        assert v.reasoning_explanation == "parse_error"

    def test_json_embedded_in_text(self):
        raw = 'Sure, here it is: {"reasoning_score": 7, "knowledge_score": 7, "tools_score": 7, "brand_voice_score": 7, "overall_score": 7.0, "verdict": "pass", "reasoning_explanation": "x", "knowledge_explanation": "x", "tools_explanation": "x", "brand_voice_explanation": "x", "judge_goal_achieved": true, "judge_goal_explanation": "x", "suggestions": "x"}'
        v = _parse_verdict(raw, 0, 0)
        assert v.verdict == "pass"


class TestFallbackVerdict:
    def test_returns_zeroed_fail_verdict(self):
        v = _fallback_verdict(100, 50)
        assert v.verdict == "fail"
        assert v.overall_score == 0.0
        assert v.input_tokens == 100
        assert v.output_tokens == 50
        assert v.reasoning_explanation == "parse_error"


class TestNormalizeJudgeModel:
    def test_defaults_to_sonnet(self):
        assert normalize_judge_model(None) == SONNET_JUDGE_MODEL
        assert normalize_judge_model("sonnet") == SONNET_JUDGE_MODEL

    def test_allows_opus_explicitly(self):
        assert normalize_judge_model("opus") == OPUS_JUDGE_MODEL
        assert normalize_judge_model(OPUS_JUDGE_MODEL) == OPUS_JUDGE_MODEL

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
            model_used=DEFAULT_JUDGE_MODEL,
            input_tokens=100,
            output_tokens=50,
        )
        d = verdict_to_dict(v)
        assert d["verdict"] == "pass"
        assert d["overall_score"] == 8.0
        assert d["judge_goal_achieved"] is True
        assert d["model_used"] == DEFAULT_JUDGE_MODEL
