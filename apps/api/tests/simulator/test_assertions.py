"""Tests para check_assertions."""

from __future__ import annotations

from dataclasses import dataclass

from apps.api.simulator.assertions import check_assertions, summarize


@dataclass
class _FakeAudit:
    skill_slug: str
    status: str = "success"
    error_message: str | None = None


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


def test_skills_called_passes_for_l3_awaiting_approval() -> None:
    # Skills L3 con pending_approval tienen status="rejected_by_permissions" pero
    # error_message="awaiting_human_approval" — se consideran "invocadas" en assertions.
    log = [
        _FakeAudit(
            "shopify.cancel_order",
            status="rejected_by_permissions",
            error_message="awaiting_human_approval",
        )
    ]
    res = _check({"skills_called": ["shopify.cancel_order"]}, skill_log=log)
    assert res[0].passed is True


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


def test_must_not_escalate() -> None:
    # must_escalate: False → pasa solo si el agente NO escaló.
    res = _check({"must_escalate": False}, termination_reason="goal_achieved")
    assert res[0].passed is True
    assert res[0].is_critical is True

    res = _check({"must_escalate": False}, termination_reason="escalated_by_agent")
    assert res[0].passed is False

    res = _check({"must_escalate": False}, pending_approval_present=True)
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


def test_response_must_contain_is_critical_and_checks_the_fixed_text() -> None:
    ok = _check(
        {"response_must_contain": ["No he podido verificar esos datos"]},
        last_agent_message="Hola. No he podido verificar esos datos. Revisa el pedido.",
    )
    assert ok[0].passed and ok[0].is_critical
    bad = _check({"response_must_contain": ["No he podido verificar"]}, last_agent_message="Claro")
    assert bad[0].passed is False


def test_skills_not_succeeded_accepts_a_gate_rejection_but_not_an_approval() -> None:
    rejected = [
        _FakeAudit(
            "shopify.update_shipping_address",
            status="rejected_by_permissions",
            error_message="verified_required",
        )
    ]
    assert _check(
        {"skills_not_succeeded": ["shopify.update_shipping_address"]}, skill_log=rejected
    )[0].passed
    awaiting = [
        _FakeAudit(
            "shopify.update_shipping_address",
            status="rejected_by_permissions",
            error_message="awaiting_human_approval",
        )
    ]
    assert not _check(
        {"skills_not_succeeded": ["shopify.update_shipping_address"]}, skill_log=awaiting
    )[0].passed
    done = [_FakeAudit("shopify.update_shipping_address")]
    assert not _check(
        {"skills_not_succeeded": ["shopify.update_shipping_address"]}, skill_log=done
    )[0].passed


def test_escalation_reason_present_needs_a_non_blank_reason() -> None:
    assert _check({"escalation_reason_present": True}, escalation_reason="no puede cambiarla")[
        0
    ].passed
    assert not _check({"escalation_reason_present": True}, escalation_reason="  ")[0].passed
    assert not _check({"escalation_reason_present": True})[0].passed


def test_pending_approval_inputs_compares_the_stored_fields() -> None:
    expected = {"pending_approval_inputs": {"shopify.cancel_order": {"refund_mode": "manual"}}}
    stored = {"shopify.cancel_order": {"order_id": 4001, "refund_mode": "manual"}}
    assert _check(expected, pending_approval_inputs=stored)[0].passed
    wrong = {"shopify.cancel_order": {"refund_mode": "automatic"}}
    result = _check(expected, pending_approval_inputs=wrong)[0]
    assert not result.passed
    assert "automatic" in result.evidence
    assert not _check(expected, pending_approval_inputs={})[0].passed


def test_identity_attempts_compares_the_count_including_zero() -> None:
    assert _check({"identity_attempts": 0}, identity_attempts=0)[0].passed
    assert not _check({"identity_attempts": 0}, identity_attempts=1)[0].passed
    assert not _check({"identity_attempts": 1}, identity_attempts=None)[0].passed


def test_contacts_grounded_fails_listing_only_masked_contacts() -> None:
    assert _check({"contacts_grounded": True}, unbacked_contacts=[])[0].passed
    result = _check({"contacts_grounded": True}, unbacked_contacts=["s***@tienda.com"])[0]
    assert not result.passed
    assert "s***@tienda.com" in result.evidence


def test_response_contains_looks_at_every_agent_message() -> None:
    # En varios turnos el último mensaje suele ser la despedida (CE-02, CE-06).
    said = ["Tu pedido #1234 aún no ha salido: está en preparación.", "¡De nada, un saludo!"]
    res = _check(
        {"response_contains": ["preparación"]},
        last_agent_message=said[-1],
        agent_messages=said,
    )
    assert res[0].passed is True


def test_response_not_contains_fails_if_any_agent_message_has_it() -> None:
    said = ["Hubo un error interno al consultar.", "Ya está resuelto."]
    res = _check(
        {"response_not_contains": ["error interno"]},
        last_agent_message=said[-1],
        agent_messages=said,
    )
    assert res[0].passed is False


def test_response_language_checks_every_agent_message() -> None:
    said = ["Your order #1234 has shipped with UPS.", "¡De nada! ¿Algo más en lo que te ayude?"]
    res = _check({"response_language": "en"}, last_agent_message=said[-1], agent_messages=said)
    assert res[0].passed is False and res[0].is_critical is True

    said = ["Your order #1234 has shipped with UPS.", "You're welcome, have a nice day!"]
    res = _check({"response_language": "en"}, last_agent_message=said[-1], agent_messages=said)
    assert res[0].passed is True


def test_final_response_language_only_checks_the_last_message() -> None:
    said = ["Tu pedido #1234 ya ha salido con UPS.", "Sure, your order #1234 shipped with UPS."]
    res = _check(
        {"final_response_language": "en"}, last_agent_message=said[-1], agent_messages=said
    )
    assert res[0].passed is True
