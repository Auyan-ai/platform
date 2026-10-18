"""Política de devoluciones y cambios del tenant (ADR 0014 §1): qué acepta el validador."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from apps.api.services.returns_policy import ReturnsPolicy, parse_stored_policy
from pydantic import ValidationError


def _policy(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": 1,
        "window": {"days": 30, "starts_at": "delivery"},
        "reasons": [
            {
                "code": "defective",
                "label": "Llegó defectuoso",
                "fault": "store",
                "required_evidence": ["photo"],
                "shopify_reason": "damaged-or-defective",
            },
            {"code": "too_small", "label": "Talla pequeña", "fault": "customer"},
        ],
        "shipping": {
            "method": "store_label",
            "payer": {"store_fault": "store", "customer_fault": "customer"},
            "customer_fee": {"amount": "4.95", "currency": "EUR"},
        },
        "refund_days": 14,
        "excluded_product_tags": ["final-sale"],
        "exchanges": {"enabled": True, "kinds": ["variant"]},
        "returns_require_approval": True,
    }
    base.update(overrides)
    return base


def _errors(raw: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as exc:
        ReturnsPolicy.model_validate(raw)
    return [str(e["msg"]) for e in exc.value.errors()]


def test_a_complete_policy_parses_with_typed_values() -> None:
    policy = ReturnsPolicy.model_validate(_policy())

    assert policy.window.days == 30
    assert policy.reason("defective").required_evidence == frozenset({"photo"})
    assert policy.shipping.customer_fee is not None
    assert policy.shipping.customer_fee.amount == Decimal("4.95")
    assert policy.shipping.payer_for("customer") == "customer"
    assert policy.reason("missing") is None


def test_there_is_no_default_for_any_business_field() -> None:
    errors = _errors({"schema_version": 1})

    assert len(errors) == 7


def test_unknown_fields_are_rejected() -> None:
    assert _errors(_policy(free_returns=True)) == ["Extra inputs are not permitted"]


def test_reason_codes_are_unique() -> None:
    reasons = [
        {"code": "too_small", "label": "Pequeña", "fault": "customer"},
        {"code": "too_small", "label": "Otra", "fault": "store"},
    ]
    assert _errors(_policy(reasons=reasons)) == ["Value error, motivo repetido: too_small"]


def test_customer_ships_requires_a_return_address() -> None:
    shipping = {
        "method": "customer_ships",
        "payer": {"store_fault": "store", "customer_fault": "customer"},
    }
    assert _errors(_policy(shipping=shipping)) == [
        "Value error, customer_ships exige return_address"
    ]


def test_a_fee_only_applies_when_the_store_sends_the_label() -> None:
    shipping = {
        "method": "customer_ships",
        "return_address": "Calle Mayor 1, 28013 Madrid",
        "payer": {"store_fault": "store", "customer_fault": "customer"},
        "customer_fee": {"amount": "4.95", "currency": "EUR"},
    }
    assert _errors(_policy(shipping=shipping)) == [
        "Value error, customer_fee solo vale con store_label: con customer_ships el "
        "cliente paga el transporte directamente"
    ]


def test_store_label_paid_by_the_customer_needs_its_fee() -> None:
    shipping = {
        "method": "store_label",
        "payer": {"store_fault": "store", "customer_fault": "customer"},
    }
    assert _errors(_policy(shipping=shipping)) == [
        "Value error, store_label con el cliente pagando exige customer_fee"
    ]


def test_store_label_paid_by_the_store_takes_no_fee() -> None:
    shipping = {
        "method": "store_label",
        "payer": {"store_fault": "store", "customer_fault": "store"},
        "customer_fee": {"amount": "4.95", "currency": "EUR"},
    }
    assert _errors(_policy(shipping=shipping)) == [
        "Value error, customer_fee sobra: la tienda paga siempre el envío de vuelta"
    ]


def test_enabled_exchanges_name_at_least_one_kind() -> None:
    assert _errors(_policy(exchanges={"enabled": True, "kinds": []})) == [
        "Value error, exchanges.enabled exige al menos un tipo de cambio"
    ]


def test_money_is_an_iso_currency_with_cents() -> None:
    shipping = {
        "method": "store_label",
        "payer": {"store_fault": "store", "customer_fault": "customer"},
        "customer_fee": {"amount": "4.955", "currency": "eur"},
    }
    errors = _errors(_policy(shipping=shipping))

    assert len(errors) == 2


@pytest.mark.parametrize("days", [0, 366])
def test_window_days_are_bounded(days: int) -> None:
    assert len(_errors(_policy(window={"days": days, "starts_at": "delivery"}))) == 1


def test_stored_json_parses_back_and_an_unknown_schema_version_is_not_guessed() -> None:
    stored = ReturnsPolicy.model_validate(_policy()).model_dump(mode="json")

    assert parse_stored_policy(stored) == ReturnsPolicy.model_validate(_policy())
    assert parse_stored_policy({**stored, "schema_version": 2}) is None


def _system_text(state: dict[str, Any]) -> str:
    from apps.api.agents.nodes.reason import agent_system_blocks

    return "\n".join(b["text"] for b in agent_system_blocks({"system_prompt": "AOP", **state}))


def test_the_turn_lists_reason_codes_and_what_each_needs() -> None:
    from apps.api.services.returns_policy import ActivePolicy

    active = ActivePolicy(version=3, policy=ReturnsPolicy.model_validate(_policy()))

    text = _system_text({"returns_policy": active.to_state(), "allowed_skills": []})

    assert (
        "Política de devoluciones y cambios de la tienda (versión 3):\n"
        "- Plazo: 30 días desde la entrega.\n"
        "- Motivos (usa el código en `reason_code`):\n"
        "  - `defective`: Llegó defectuoso (exige foto del cliente)\n"
        "  - `too_small`: Talla pequeña\n"
        "- Cambios: sí, por otra talla o color del mismo producto.\n"
    ) in text


def test_without_policy_only_return_aops_hear_that_it_is_missing() -> None:
    returns_aop = _system_text({"allowed_skills": ["shopify.start_return"]})
    other_aop = _system_text({"allowed_skills": ["shopify.get_order_status"]})

    assert "la tienda no la ha configurado" in returns_aop
    assert "Política de devoluciones" not in other_aop
