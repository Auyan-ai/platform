"""Tests del schema `AgentDecisionTool` — validación del tool output de Claude."""

from __future__ import annotations

import pytest
from apps.api.agents.schemas import AgentDecisionTool
from pydantic import ValidationError


class TestRespondDecision:
    def test_happy_path(self) -> None:
        tool = AgentDecisionTool.model_validate(
            {
                "decision": "respond",
                "confidence": 0.92,
                "response_text": "Los envíos a Argentina tardan 3-5 días.",
            }
        )
        assert tool.decision == "respond"
        assert tool.response_text is not None
        assert tool.escalation_reason is None

    def test_requires_response_text(self) -> None:
        with pytest.raises(ValidationError, match="response_text"):
            AgentDecisionTool.model_validate(
                {"decision": "respond", "confidence": 0.9}
            )

    def test_rejects_empty_response_text(self) -> None:
        with pytest.raises(ValidationError, match="response_text"):
            AgentDecisionTool.model_validate(
                {"decision": "respond", "confidence": 0.9, "response_text": "   "}
            )


class TestEscalateDecision:
    def test_happy_path(self) -> None:
        tool = AgentDecisionTool.model_validate(
            {
                "decision": "escalate",
                "confidence": 0.4,
                "response_text": "Te paso con un agente humano que te ayudará.",
                "escalation_reason": "customer_requested_human",
            }
        )
        assert tool.decision == "escalate"
        assert tool.escalation_reason == "customer_requested_human"
        assert tool.response_text.startswith("Te paso")

    def test_requires_escalation_reason(self) -> None:
        with pytest.raises(ValidationError, match="escalation_reason"):
            AgentDecisionTool.model_validate(
                {
                    "decision": "escalate",
                    "confidence": 0.5,
                    "response_text": "Te paso con un agente.",
                }
            )

    def test_requires_response_text_on_escalate(self) -> None:
        with pytest.raises(ValidationError, match="response_text"):
            AgentDecisionTool.model_validate(
                {
                    "decision": "escalate",
                    "confidence": 0.5,
                    "escalation_reason": "customer_requested_human",
                }
            )


class TestConfidenceBounds:
    def test_rejects_negative_confidence(self) -> None:
        with pytest.raises(ValidationError):
            AgentDecisionTool.model_validate(
                {
                    "decision": "respond",
                    "confidence": -0.1,
                    "response_text": "x",
                }
            )

    def test_rejects_confidence_above_one(self) -> None:
        with pytest.raises(ValidationError):
            AgentDecisionTool.model_validate(
                {
                    "decision": "respond",
                    "confidence": 1.5,
                    "response_text": "x",
                }
            )

    @pytest.mark.parametrize("v", [0.0, 0.5, 1.0])
    def test_accepts_boundaries(self, v: float) -> None:
        tool = AgentDecisionTool.model_validate(
            {"decision": "respond", "confidence": v, "response_text": "x"}
        )
        assert tool.confidence == v


class TestRejectsExtraFields:
    def test_extra_field_fails(self) -> None:
        # extra='forbid' en el ConfigDict del schema
        with pytest.raises(ValidationError):
            AgentDecisionTool.model_validate(
                {
                    "decision": "respond",
                    "confidence": 0.9,
                    "response_text": "x",
                    "some_extra_field": "should_fail",
                }
            )
