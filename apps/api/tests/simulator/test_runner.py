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
