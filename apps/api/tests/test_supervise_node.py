"""Tests para el nodo supervise y las funciones de routing del supervisor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ──────────────────────────────────────────────────────────
# needs_supervision
# ──────────────────────────────────────────────────────────


class TestNeedsSupervision:
    def _fn(self, state: dict) -> bool:
        from apps.api.agents.nodes.supervise import needs_supervision

        return needs_supervision(state)

    def test_false_without_pending_tool_or_flag(self):
        assert not self._fn({"tenant_config": {"extra": {}}})

    def test_aop_require_supervision_supervises_response_after_tools(self):
        # require_supervision + el turno usó herramientas → supervisa la respuesta.
        assert self._fn({
            "tenant_config": {"extra": {}},
            "aop_require_supervision": True,
            "tool_results": [{"slug": "shopify.get_order_status", "is_error": False}],
        })

    def test_aop_require_supervision_skips_plain_response(self):
        # require_supervision PERO respuesta de cortesía sin herramientas → no supervisa.
        assert not self._fn({
            "tenant_config": {"extra": {}},
            "aop_require_supervision": True,
            "tool_results": [],
        })

    def test_aop_require_supervision_false_does_not_force(self):
        assert not self._fn({"tenant_config": {"extra": {}}, "aop_require_supervision": False})

    def test_false_for_l1_tool(self):
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L1Skill(Skill):
            slug = "test.l1_supervise"
            description = "test"
            tier = "L1"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.7

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l1_supervise"] = _L1Skill
        try:
            assert not self._fn({
                "tenant_config": {"extra": {}},
                "pending_tool_call": {"slug": "test.l1_supervise", "input": {}},
            })
        finally:
            del SkillRegistry._by_slug["test.l1_supervise"]

    def test_true_for_l2_tool(self):
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L2Skill(Skill):
            slug = "test.l2_supervise"
            description = "test"
            tier = "L2"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.85

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l2_supervise"] = _L2Skill
        try:
            assert self._fn({
                "tenant_config": {"extra": {}},
                "pending_tool_call": {"slug": "test.l2_supervise", "input": {}},
            })
        finally:
            del SkillRegistry._by_slug["test.l2_supervise"]

    def test_true_for_l3_tool(self):
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L3Skill(Skill):
            slug = "test.l3_supervise"
            description = "test"
            tier = "L3"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.95

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l3_supervise"] = _L3Skill
        try:
            assert self._fn({
                "tenant_config": {"extra": {}},
                "pending_tool_call": {"slug": "test.l3_supervise", "input": {}},
            })
        finally:
            del SkillRegistry._by_slug["test.l3_supervise"]

    def test_require_supervision_flag_supervises_after_tools(self):
        assert self._fn({
            "tenant_config": {"extra": {"require_supervision": True}},
            "tool_results": [{"slug": "x", "is_error": False}],
        })

    def test_require_supervision_flag_skips_plain_response(self):
        assert not self._fn({
            "tenant_config": {"extra": {"require_supervision": True}},
            "tool_results": [],
        })

    def test_l3_pending_supervised_even_without_tool_results(self):
        """Una acción L3 pendiente se supervisa siempre, aunque no haya tool_results."""
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L3Skill(Skill):
            slug = "test.l3_always"
            description = "test"
            tier = "L3"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.95

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l3_always"] = _L3Skill
        try:
            assert self._fn({
                "tenant_config": {"extra": {}},
                "pending_tool_call": {"slug": "test.l3_always", "input": {}},
                "tool_results": [],
            })
        finally:
            del SkillRegistry._by_slug["test.l3_always"]

    def test_still_supervises_response_after_retry(self):
        """supervisor_retried NO apaga la supervisión del turno: la respuesta
        corregida tras un reject tactical se re-supervisa (el anti-loop vive en
        el nodo supervise: segundo reject → escalation_reason → escalate)."""
        assert self._fn({
            "tenant_config": {"extra": {"require_supervision": True}},
            "supervisor_retried": True,
            "tool_results": [{"slug": "x", "is_error": False}],
        })

    def test_still_supervises_l2_tool_after_retry(self):
        """Una L2 nueva pedida DESPUÉS de un retry del supervisor se supervisa
        igual — supervisor_retried es por-turno y no debe ser un kill-switch."""
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L2Skill(Skill):
            slug = "test.l2_after_retry"
            description = "test"
            tier = "L2"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.85

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l2_after_retry"] = _L2Skill
        try:
            assert self._fn({
                "tenant_config": {"extra": {}},
                "pending_tool_call": {"slug": "test.l2_after_retry", "input": {}},
                "supervisor_retried": True,
            })
        finally:
            del SkillRegistry._by_slug["test.l2_after_retry"]


# ──────────────────────────────────────────────────────────
# Nodo supervise
# ──────────────────────────────────────────────────────────


def _make_supervisor_response(verdict: str, reject_kind: str = "n/a", reason: str = "ok"):
    response = MagicMock()
    response.content = [
        MagicMock(
            type="tool_use",
            name="supervisor_verdict",
            id="sup_001",
            input={
                "verdict": verdict,
                "reject_kind": reject_kind,
                "reason": reason,
                "guardrails_violated": [],
            },
        )
    ]
    response.usage = MagicMock(input_tokens=200, output_tokens=80)
    return response


class TestSuperviseNode:
    def _base_state(self) -> dict:
        return {
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "conversation_id": "22222222-2222-2222-2222-222222222222",
            "system_prompt": "eres un agente de soporte\n## Reglas NO negociables\n- no inventes",
            "tenant_config": {"extra": {}, "escalation_threshold": 0.70},
            "conversation_history": [{"role": "user", "content": "quiero cancelar"}],
            "decision": "respond",
            "agent_response": "ok, te ayudo",
            "tool_results": [],
            "cost_usd": 0.01,
            "aop_slug": "cancelacion",
        }

    @pytest.mark.asyncio
    async def test_approve_sets_verdict(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response("approve", reason="todo correcto")
        )

        node = make_supervise_node(fake_deps)
        result = await node(self._base_state())

        assert result["supervisor_verdict"] == "approve"
        assert result["supervisor_reject_kind"] == "n/a"
        assert result["supervisor_reason"] == "todo correcto"

    @pytest.mark.asyncio
    async def test_reject_tactical_sets_retried_and_injects_feedback(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response(
                "reject", reject_kind="tactical", reason="no verificaste el estado"
            )
        )

        state = {**self._base_state(), "supervisor_retried": False}
        node = make_supervise_node(fake_deps)
        result = await node(state)

        assert result["supervisor_verdict"] == "reject"
        assert result["supervisor_reject_kind"] == "tactical"
        assert result.get("supervisor_retried") is True
        # El feedback se inyecta en system_prompt
        assert "Feedback del supervisor" in result.get("system_prompt", "")

    @pytest.mark.asyncio
    async def test_reject_tactical_after_retry_escalates(self, fake_deps: Any) -> None:
        """Segundo rechazo (tactical con supervisor_retried=True ya seteado) →
        no hay segundo retry: el nodo pone escalation_reason y el grafo escala."""
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response(
                "reject", reject_kind="tactical", reason="sigue mal"
            )
        )

        state = {**self._base_state(), "supervisor_retried": True}
        node = make_supervise_node(fake_deps)
        result = await node(state)

        assert "supervisor_rejected" in result.get("escalation_reason", "")
        assert "supervisor_retried" not in result  # no re-arma otro retry

    @pytest.mark.asyncio
    async def test_reject_structural_sets_escalation_reason(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response(
                "reject", reject_kind="structural", reason="AOP incorrecto"
            )
        )

        node = make_supervise_node(fake_deps)
        result = await node(self._base_state())

        assert result["supervisor_verdict"] == "reject"
        assert "supervisor_rejected" in result.get("escalation_reason", "")

    @pytest.mark.asyncio
    async def test_uses_opus_for_l3_tool(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L3Skill(Skill):
            slug = "test.l3_supervisor_model"
            description = "test"
            tier = "L3"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.95

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l3_supervisor_model"] = _L3Skill
        try:
            fake_deps.anthropic.messages.create = AsyncMock(
                return_value=_make_supervisor_response("approve")
            )
            state = {
                **self._base_state(),
                "pending_tool_call": {"slug": "test.l3_supervisor_model", "input": {}},
            }
            node = make_supervise_node(fake_deps)
            await node(state)

            call_args = fake_deps.anthropic.messages.create.call_args
            assert call_args.kwargs["model"] == "claude-opus-4-7"
        finally:
            del SkillRegistry._by_slug["test.l3_supervisor_model"]

    @pytest.mark.asyncio
    async def test_uses_sonnet_for_l1_l2(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response("approve")
        )

        node = make_supervise_node(fake_deps)
        await node(self._base_state())

        call_args = fake_deps.anthropic.messages.create.call_args
        assert call_args.kwargs["model"] == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_accumulates_tokens(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response("approve")
        )

        state = {**self._base_state(), "supervisor_tokens_in": 100, "supervisor_tokens_out": 40}
        node = make_supervise_node(fake_deps)
        result = await node(state)

        assert result["supervisor_tokens_in"] == 300   # 100 prev + 200 mock
        assert result["supervisor_tokens_out"] == 120  # 40 prev + 80 mock

    @pytest.mark.asyncio
    async def test_emits_reasoning_events(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response("approve")
        )

        node = make_supervise_node(fake_deps)
        await node(self._base_state())

        events = fake_deps.reasoning_tracker.events
        supervisor_events = [e for e in events if e["phase"] == "supervisor"]
        assert len(supervisor_events) >= 2  # pending + done


# ──────────────────────────────────────────────────────────
# route_after_supervise
# ──────────────────────────────────────────────────────────


class TestRouteAfterSupervise:
    def _route(self, state: dict) -> str:
        from apps.api.agents.graph import route_after_supervise

        return route_after_supervise(state)

    def test_approve_with_pending_tool_goes_to_execute_skill(self):
        assert self._route({
            "supervisor_verdict": "approve",
            "pending_tool_call": {"slug": "s", "input": {}},
        }) == "execute_skill"

    def test_approve_respond_goes_to_respond(self):
        assert self._route({
            "supervisor_verdict": "approve",
            "decision": "respond",
        }) == "respond"

    def test_approve_escalate_goes_to_escalate(self):
        assert self._route({
            "supervisor_verdict": "approve",
            "decision": "escalate",
        }) == "escalate"

    def test_reject_tactical_first_time_goes_to_reason(self):
        # Primer rechazo tactical: nodo setó supervisor_retried=True pero NO escalation_reason
        assert self._route({
            "supervisor_verdict": "reject",
            "supervisor_reject_kind": "tactical",
            "supervisor_retried": True,
            # sin escalation_reason → va a reason
        }) == "reason"

    def test_reject_tactical_second_time_goes_to_escalate(self):
        # Segundo rechazo: el nodo ve supervisor_retried=True y pone
        # escalation_reason (aunque el reject sea tactical) → ruta a escalate.
        assert self._route({
            "supervisor_verdict": "reject",
            "supervisor_reject_kind": "tactical",
            "supervisor_retried": True,
            "escalation_reason": "supervisor_rejected (tactical): sigue mal",
        }) == "escalate"

    def test_reject_structural_goes_to_escalate(self):
        # Rechazo structural: el nodo pone escalation_reason → ruta a escalate
        assert self._route({
            "supervisor_verdict": "reject",
            "supervisor_reject_kind": "structural",
            "escalation_reason": "supervisor_rejected (structural): AOP incorrecto",
        }) == "escalate"

    def test_error_goes_to_handle_error(self):
        assert self._route({"error": "something_failed"}) == "handle_error"
