"""Tests del runner del simulador."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from apps.api.simulator.runner import _compute_status


class TestComputeStatus:
    def test_no_judge_mode_uses_assertions_only(self) -> None:
        assert _compute_status(
            all_critical_passed=True,
            passed=3,
            total=3,
            judge_verdict=None,
            judge_required=False,
        ) == "passed"

    def test_missing_required_judge_is_errored(self) -> None:
        assert _compute_status(
            all_critical_passed=True,
            passed=3,
            total=3,
            judge_verdict=None,
        ) == "errored"


class TestRunnerEvidenceHelpers:
    def test_unbacked_contacts_masks_what_no_source_backs(self) -> None:
        from apps.api.simulator.runner import _unbacked_contacts

        state: Any = {
            "tenant_facts": {},
            "tenant_config": None,
            "system_prompt": "Eres el agente de la tienda.",
            "conversation_history": [{"role": "customer", "content": "Escribo a ayuda@tienda.com"}],
            "tool_results": [],
        }
        backed = _unbacked_contacts(state, "Escríbenos a ayuda@tienda.com")
        invented = _unbacked_contacts(state, "Escríbenos a soporte@tienda.com")
        assert backed == []
        assert invented == ["s***@tienda.com"]

    def test_mask_contacts_hides_emails_and_phones_for_the_pr_report(self) -> None:
        from apps.api.scripts.run_simulator import mask_contacts

        masked = mask_contacts("Escribe a lucia.vera@ejemplo.com o llama al +34 600 111 222")
        assert "lucia.vera" not in masked
        assert "600 111" not in masked
        assert "l***@e***.com" in masked

    async def test_behavior_evidence_only_reads_what_the_scenario_asks_for(
        self, monkeypatch: Any
    ) -> None:
        from unittest.mock import AsyncMock

        from apps.api.simulator import runner
        from apps.api.tests.conftest import make_fake_tenant_scope

        monkeypatch.setattr(runner, "tenant_scope", make_fake_tenant_scope())
        inputs = AsyncMock(return_value={"shopify.cancel_order": {"refund_mode": "manual"}})
        count = AsyncMock(return_value=2)
        cleanup = AsyncMock(return_value=2)
        monkeypatch.setattr(runner, "list_pending_approval_inputs", inputs)
        monkeypatch.setattr(runner, "count_conversation_attempts", count)
        monkeypatch.setattr(runner, "soft_delete_conversation_checks", cleanup)

        none_asked = await runner._behavior_evidence(uuid4(), uuid4(), {"must_escalate": True})
        assert none_asked == (None, None)
        assert inputs.await_count == 0 and count.await_count == 0
        assert cleanup.await_count == 1

        both = await runner._behavior_evidence(
            uuid4(),
            uuid4(),
            {"pending_approval_inputs": {"shopify.cancel_order": {}}, "identity_attempts": 2},
        )
        assert both == ({"shopify.cancel_order": {"refund_mode": "manual"}}, 2)


class TestSimulatedChatReply:
    """#350: el simulador registra lo que recibe el cliente del chat, nunca un texto vacío."""

    def test_low_confidence_escalation_gets_the_chat_ack(self) -> None:
        from apps.api.simulator.runner import simulated_chat_reply

        state: Any = {
            "decision": "escalate",
            "agent_response": None,
            "escalation_reason": "low_confidence: 0.50 < threshold 0.65",
        }
        assert simulated_chat_reply(state) == (
            "Le hemos pasado tu consulta a nuestro equipo. Te responderán por aquí lo antes posible."
        )

    def test_agent_text_is_the_reply(self) -> None:
        from apps.api.simulator.runner import simulated_chat_reply

        state: Any = {"decision": "respond", "agent_response": "Tu pedido sale hoy."}
        assert simulated_chat_reply(state) == "Tu pedido sale hoy."

    def test_errored_turn_has_no_reply_even_with_a_draft(self) -> None:
        from apps.api.simulator.runner import simulated_chat_reply

        state: Any = {"decision": "respond", "agent_response": "borrador", "error": "reason: boom"}
        assert simulated_chat_reply(state) == ""
