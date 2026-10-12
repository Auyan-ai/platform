"""Tests del runner del simulador."""

from __future__ import annotations

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
