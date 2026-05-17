"""Tests del routing condicional del grafo: `route_after_reason` y `route_after_execute_skill`."""

from __future__ import annotations

from apps.api.agents.graph import route_after_execute_skill, route_after_reason


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

    def test_pending_tool_call_routes_to_execute_skill(self) -> None:
        """Si reason emitió un pending_tool_call, vamos al loop ReAct."""
        state = {"pending_tool_call": {"id": "toolu_x", "slug": "shopify.get_order", "input": {}}}
        assert route_after_reason(state) == "execute_skill"  # type: ignore[arg-type]

    def test_pending_tool_call_takes_priority_over_decision(self) -> None:
        """En el caso teórico de tener ambos, pending_tool_call gana (estaríamos en loop)."""
        state = {
            "pending_tool_call": {"id": "toolu_x", "slug": "x.y", "input": {}},
            "decision": "respond",
        }
        assert route_after_reason(state) == "execute_skill"  # type: ignore[arg-type]

    def test_error_beats_pending_tool_call(self) -> None:
        state = {
            "error": "boom",
            "pending_tool_call": {"id": "toolu_x", "slug": "x.y", "input": {}},
        }
        assert route_after_reason(state) == "handle_error"  # type: ignore[arg-type]


class TestRouteAfterExecuteSkill:
    def test_default_routes_back_to_reason(self) -> None:
        """Sin haber alcanzado max_iter, el loop continúa."""
        state = {"tool_iterations": 1, "max_tool_iterations": 5}
        assert route_after_execute_skill(state) == "reason"  # type: ignore[arg-type]

    def test_max_iterations_escalates(self) -> None:
        """Llegamos al límite del loop ReAct → escalate."""
        state = {"tool_iterations": 5, "max_tool_iterations": 5}
        assert route_after_execute_skill(state) == "escalate"  # type: ignore[arg-type]

    def test_above_max_iterations_escalates(self) -> None:
        state = {"tool_iterations": 7, "max_tool_iterations": 5}
        assert route_after_execute_skill(state) == "escalate"  # type: ignore[arg-type]

    def test_error_routes_to_handle_error(self) -> None:
        state = {"error": "unexpected", "tool_iterations": 1, "max_tool_iterations": 5}
        assert route_after_execute_skill(state) == "handle_error"  # type: ignore[arg-type]

    def test_uses_default_max_when_missing(self) -> None:
        """Si max_tool_iterations no está en state, default a 5."""
        state = {"tool_iterations": 4}
        assert route_after_execute_skill(state) == "reason"  # type: ignore[arg-type]
        state2 = {"tool_iterations": 5}
        assert route_after_execute_skill(state2) == "escalate"  # type: ignore[arg-type]
