"""Tests del runner del simulador."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from apps.api.simulator.judge import DEFAULT_JUDGE_MODEL, OPUS_JUDGE_MODEL
from apps.api.simulator.runner import _compute_status, _estimate_cost_cents, _RunAccumulator


def _acc(*, judge_model: str) -> _RunAccumulator:
    return _RunAccumulator(
        run_id=uuid4(),
        conversation_id=uuid4(),
        end_customer_id=uuid4(),
        transcript=cast(Any, None),
        judge_model=judge_model,
    )


class TestEstimateCostCents:
    def test_uses_sonnet_rates_for_default_judge(self) -> None:
        acc = _acc(judge_model=DEFAULT_JUDGE_MODEL)
        acc.tokens_judge_in = 1000
        acc.tokens_judge_out = 1000

        assert _estimate_cost_cents(acc) == 1.8

    def test_uses_opus_rates_for_explicit_opus_judge(self) -> None:
        acc = _acc(judge_model=OPUS_JUDGE_MODEL)
        acc.tokens_judge_in = 1000
        acc.tokens_judge_out = 1000

        assert _estimate_cost_cents(acc) == 9.0


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
