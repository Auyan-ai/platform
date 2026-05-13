"""Tests del routing condicional post-`reason`."""

from __future__ import annotations

from apps.api.agents.graph import route_after_reason


class TestRouteAfterReason:
    def test_error_routes_to_handle_error(self) -> None:
        state = {"error": "something_broke", "decision": "respond"}
        assert route_after_reason(state) == "handle_error"  # type: ignore[arg-type]

    def test_respond_decision(self) -> None:
        state = {"decision": "respond", "agent_response": "hola"}
        assert route_after_reason(state) == "respond"  # type: ignore[arg-type]

    def test_escalate_decision(self) -> None:
        state = {"decision": "escalate", "escalation_reason": "x"}
        assert route_after_reason(state) == "escalate"  # type: ignore[arg-type]

    def test_missing_decision_falls_back_to_handle_error(self) -> None:
        """Defense-in-depth: si llegamos sin decisión válida, escalamos via error."""
        state: dict = {}
        assert route_after_reason(state) == "handle_error"  # type: ignore[arg-type]

    def test_unknown_decision_falls_back_to_handle_error(self) -> None:
        state = {"decision": "weird_value"}
        assert route_after_reason(state) == "handle_error"  # type: ignore[arg-type]

    def test_error_takes_priority_over_decision(self) -> None:
        """Si hubo error en algún paso, descartamos cualquier decision parcial."""
        state = {"error": "load_failed", "decision": "respond"}
        assert route_after_reason(state) == "handle_error"  # type: ignore[arg-type]
