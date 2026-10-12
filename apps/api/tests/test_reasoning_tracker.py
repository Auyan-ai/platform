"""Tests para ReasoningTracker y los endpoints de reasoning."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
CONV_ID = UUID("22222222-2222-2222-2222-222222222222")


# ──────────────────────────────────────────────────────────
# ReasoningTracker (unit)
# ──────────────────────────────────────────────────────────


class TestReasoningTracker:
    def _make_tracker(self):
        from apps.api.services.reasoning import ReasoningTracker

        return ReasoningTracker()

    def test_emit_does_not_raise_without_event_loop(self):
        """emit() no explota cuando no hay event loop (tests síncronos)."""
        tracker = self._make_tracker()
        # No debe lanzar nada — simplemente ignora
        tracker.emit(
            tenant_id=TENANT_ID,
            conversation_id=CONV_ID,
            phase="supervisor",
            event_type="check",
            label="test",
        )

    def test_emit_accepts_string_uuids(self):
        """emit() acepta str además de UUID para tenant_id y conversation_id."""
        tracker = self._make_tracker()
        tracker.emit(
            tenant_id=str(TENANT_ID),
            conversation_id=str(CONV_ID),
            phase="decision",
            event_type="tool_call",
            label="shopify.get_order",
        )

    def test_emit_accepts_all_phases(self):
        tracker = self._make_tracker()
        for phase in ("supervisor", "decision", "response"):
            tracker.emit(
                tenant_id=TENANT_ID,
                conversation_id=CONV_ID,
                phase=phase,  # type: ignore[arg-type]
                event_type="check",
                label=f"test {phase}",
            )

    def test_emit_accepts_all_event_types(self):
        tracker = self._make_tracker()
        for event_type in ("check", "tool_call", "tool_result", "choice"):
            tracker.emit(
                tenant_id=TENANT_ID,
                conversation_id=CONV_ID,
                phase="decision",
                event_type=event_type,  # type: ignore[arg-type]
                label=f"test {event_type}",
            )

    @pytest.mark.asyncio
    async def test_insert_logs_exception_on_db_failure(self):
        """_insert no propaga la excepción — la loguea y termina limpiamente."""
        tracker = self._make_tracker()
        with patch(
            "apps.api.services.reasoning.tenant_scope",
            side_effect=Exception("db down"),
        ):
            # No debe propagar — solo loguear
            await tracker._insert(
                tenant_id=TENANT_ID,
                conversation_id=CONV_ID,
                phase="supervisor",
                event_type="check",
                label="test",
                detail=None,
                status="done",
            )


# ──────────────────────────────────────────────────────────
# FakeReasoningTracker (en tests de nodos)
# ──────────────────────────────────────────────────────────


class TestFakeReasoningTrackerInNodes:
    """Verifica que los nodos llaman al tracker con los parámetros correctos."""

    @pytest.mark.asyncio
    async def test_reason_node_emits_decision_event(
        self, fake_deps: Any, initial_state: dict
    ) -> None:
        from apps.api.agents.nodes.reason import make_reason_node

        state = {
            **initial_state,
            "system_prompt": "eres un agente",
            "conversation_history": [
                {"role": "agent_ai", "content": "¿En qué te ayudo?"},
                {"role": "customer", "content": "hola"},
            ],
            "tenant_config": {"escalation_threshold": 0.70, "extra": {}},
            "model_used": "claude-sonnet-4-6",
            "allowed_skills": [],
            "tool_results": [],
        }

        from tests.conftest import FakeAnthropicResponse

        fake_response = FakeAnthropicResponse(
            tool_input={
                "decision": "respond",
                "confidence": 0.9,
                "response_text": "¡Claro que sí!",
                "escalation_reason": None,
            },
            tool_name="respond_or_escalate",
        )
        fake_deps.anthropic.messages.create = AsyncMock(return_value=fake_response)

        node = make_reason_node(fake_deps)
        result = await node(state)

        assert result.get("decision") == "respond"
        # El tracker debería haber recibido al menos un emit (la decisión final)
        tracker = fake_deps.reasoning_tracker
        assert any(e["phase"] == "response" for e in tracker.events)

    @pytest.mark.asyncio
    async def test_reason_node_emits_tool_call_event(
        self, fake_deps: Any, initial_state: dict
    ) -> None:
        from apps.api.agents.nodes.reason import make_reason_node
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            email: str

        class _FakeOutput(SkillOutput):
            pass

        class _FakeSkill(Skill):
            slug = "shopify.test_skill_emit"
            description = "test"
            tier = "L1"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.7

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["shopify.test_skill_emit"] = _FakeSkill

        state = {
            **initial_state,
            "system_prompt": "eres un agente",
            "conversation_history": [
                {"role": "agent_ai", "content": "Hola"},
                {"role": "customer", "content": "¿dónde está mi pedido?"},
            ],
            "tenant_config": {"escalation_threshold": 0.70, "extra": {}},
            "model_used": "claude-sonnet-4-6",
            "allowed_skills": ["shopify.test_skill_emit"],
            "tool_permissions": {"shopify.test_skill_emit": {"is_enabled": True}},
            "tool_results": [],
        }

        from tests.conftest import FakeAnthropicResponse

        fake_response = FakeAnthropicResponse(
            tool_input={"email": "test@example.com"},
            tool_name="shopify_test_skill_emit",
            tool_id="tool_002",
        )
        fake_deps.anthropic.messages.create = AsyncMock(return_value=fake_response)

        node = make_reason_node(fake_deps)
        result = await node(state)

        assert result.get("pending_tool_call") is not None
        tracker = fake_deps.reasoning_tracker
        tool_call_events = [e for e in tracker.events if e["event_type"] == "tool_call"]
        assert len(tool_call_events) >= 1
        assert tool_call_events[0]["label"] == "shopify.test_skill_emit"

        # Cleanup
        del SkillRegistry._by_slug["shopify.test_skill_emit"]
