"""Tests para check_assertions."""

from __future__ import annotations

from dataclasses import dataclass

from apps.api.simulator.assertions import check_assertions, summarize


@dataclass
class _FakeAudit:
    skill_slug: str
    status: str = "success"


def _check(assertions: dict, **kwargs):
    defaults = dict(
        skill_log=[],
        last_agent_message="",
        termination_reason=None,
        turns_count=1,
        pending_approval_present=False,
    )
    defaults.update(kwargs)
    return check_assertions(assertions=assertions, **defaults)


def test_skills_called_pass_and_fail() -> None:
    log = [_FakeAudit("shopify.get_order_status")]
    res = _check({"skills_called": ["shopify.get_order_status"]}, skill_log=log)
    assert res[0].passed is True

    res = _check({"skills_called": ["shopify.refund_partial"]}, skill_log=log)
    assert res[0].passed is False
    assert res[0].is_critical is True


def test_skills_called_requires_success_status() -> None:
    log = [_FakeAudit("shopify.get_order_status", status="failed")]
    res = _check({"skills_called": ["shopify.get_order_status"]}, skill_log=log)
    assert res[0].passed is False


def test_skills_not_called() -> None:
    log = [_FakeAudit("shopify.cancel_order")]
    res = _check({"skills_not_called": ["shopify.cancel_order"]}, skill_log=log)
    assert res[0].passed is False


def test_response_contains_case_insensitive() -> None:
    res = _check(
        {"response_contains": ["TRACKING"]},
        last_agent_message="Aquí está tu tracking number 1Z999",
    )
    assert res[0].passed is True
    assert res[0].is_critical is False


def test_response_not_contains_critical() -> None:
    res = _check(
        {"response_not_contains": ["error interno"]},
        last_agent_message="Hubo un error interno",
    )
    assert res[0].passed is False
    assert res[0].is_critical is True


def test_outcome_is_mapping() -> None:
    res = _check({"outcome_is": "resolved"}, termination_reason="goal_achieved")
    assert res[0].passed is True
    res = _check({"outcome_is": "escalated"}, termination_reason="escalated_by_agent")
    assert res[0].passed is True
    res = _check({"outcome_is": "abandoned"}, termination_reason="max_turns")
    assert res[0].passed is True
    res = _check({"outcome_is": "resolved"}, termination_reason="give_up")
    assert res[0].passed is False


def test_max_turns() -> None:
    res = _check({"max_turns": 3}, turns_count=2)
    assert res[0].passed is True
    res = _check({"max_turns": 3}, turns_count=5)
    assert res[0].passed is False


def test_must_escalate_via_agent_or_pending_approval() -> None:
    res = _check({"must_escalate": True}, termination_reason="escalated_by_agent")
    assert res[0].passed is True
    res = _check({"must_escalate": True}, pending_approval_present=True)
    assert res[0].passed is True
    res = _check({"must_escalate": True}, termination_reason="goal_achieved")
    assert res[0].passed is False


def test_must_have_pending_approval() -> None:
    res = _check({"must_have_pending_approval": True}, pending_approval_present=True)
    assert res[0].passed is True
    res = _check({"must_have_pending_approval": True}, pending_approval_present=False)
    assert res[0].passed is False


def test_summarize_all_critical_passed() -> None:
    log = [_FakeAudit("shopify.get_order_status")]
    res = _check(
        {
            "skills_called": ["shopify.get_order_status"],
            "response_contains": ["nope"],  # no crítica, falla
        },
        skill_log=log,
        last_agent_message="vacío",
    )
    passed, total, all_critical = summarize(res)
    assert total == 2
    assert passed == 1
    assert all_critical is True  # la única crítica (skills_called) pasó
