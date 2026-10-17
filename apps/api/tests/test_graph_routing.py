"""Tests del routing condicional del grafo: `route_after_reason` y `route_after_execute_skill`."""

from __future__ import annotations

from apps.api.agents.graph import route_after_execute_skill, route_after_reason


class TestRouteAfterReason:
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

class TestRouteAfterExecuteSkill:
    def test_default_routes_back_to_reason(self) -> None:
        """Sin haber alcanzado max_iter, el loop continúa."""
        state = {"tool_iterations": 1, "max_tool_iterations": 5}
        assert route_after_execute_skill(state) == "reason"  # type: ignore[arg-type]

    def test_max_iterations_goes_to_final_reason_turn(self) -> None:
        """Al límite del loop, `reason` hace un último turno forzado a decidir (no se
        escala en seco: el cliente se quedaba sin respuesta)."""
        state = {"tool_iterations": 5, "max_tool_iterations": 5}
        assert route_after_execute_skill(state) == "reason"  # type: ignore[arg-type]

    def test_pending_approval_escalates(self) -> None:
        state = {"pending_approval_id": "a-1", "tool_iterations": 1, "max_tool_iterations": 5}
        assert route_after_execute_skill(state) == "escalate"  # type: ignore[arg-type]

    def test_skill_refusal_escalates_without_reason(self) -> None:
        """Una skill que se niega por regla en código (pedido enviado) deja
        decision='escalate': no vuelve al LLM."""
        state = {"decision": "escalate", "tool_iterations": 1, "max_tool_iterations": 5}
        assert route_after_execute_skill(state) == "escalate"  # type: ignore[arg-type]
