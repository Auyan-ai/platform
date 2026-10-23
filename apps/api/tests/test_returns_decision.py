"""Decisión de una devolución o un cambio y su liquidación (ADR 0014 §4-§5), sin LLM."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.services.returns import (
    CalculatedLine,
    Eligible,
    Evidence,
    ExchangeVariant,
    PhotoRef,
    Refused,
    Rejected,
    RequestedExchange,
    RequestedItem,
    ReturnableLine,
    ReturnableOrder,
    ReturnCalculation,
    ReturnPlan,
    build_plan,
    customer_photos,
    evaluate_return,
)
from apps.api.services.returns_policy import ActivePolicy, ReturnsPolicy

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
SHIPPED = NOW - timedelta(days=20)
DELIVERED = NOW - timedelta(days=18)


def _policy(**overrides: Any) -> ActivePolicy:
    raw: dict[str, Any] = {
        "schema_version": 1,
        "window": {"days": 30, "starts_at": "delivery"},
        "reasons": [
            {
                "code": "defective",
                "label": "Defectuoso",
                "fault": "store",
                "required_evidence": ["photo"],
                "shopify_reason": "damaged-or-defective",
            },
            {
                "code": "too_small",
                "label": "Pequeña",
                "fault": "customer",
                "shopify_reason": "too-small",
                "required_evidence": [],
            },
        ],
        "shipping": {
            "method": "store_label",
            "payer": {"store_fault": "store", "customer_fault": "customer"},
            "customer_fee_mode": "fixed",
            "customer_fee": {"amount": "4.95", "currency": "EUR"},
        },
        "refund_days": 14,
        "refund_method": "original_payment",
        "restocking_fee_percent": {"store_fault": "0", "customer_fault": "0"},
        "excluded_product_tags": ["final-sale"],
        "exchanges": {
            "enabled": True,
            "kinds": ["variant"],
            "requires_approval": True,
            "higher_price": "customer_pays",
            "lower_price": "refund_difference",
            "ship_replacement": "after_receipt",
        },
        "returns_require_approval": False,
        "evidence_requires_approval": True,
    }
    raw.update(overrides)
    return ActivePolicy(version=7, policy=ReturnsPolicy.model_validate(raw))


def _line(**overrides: Any) -> ReturnableLine:
    base: dict[str, Any] = {
        "line_item_id": 501,
        "fulfillment_line_item_id": "gid://shopify/FulfillmentLineItem/9001",
        "title": "Blusa - Marino / S",
        "returnable_quantity": 2,
        "product_id": 77,
        "product_tags": frozenset({"blusas"}),
        "shipped_at": SHIPPED,
        "delivered_at": DELIVERED,
    }
    base.update(overrides)
    return ReturnableLine(**base)


def _order(*lines: ReturnableLine, **overrides: Any) -> ReturnableOrder:
    base: dict[str, Any] = {
        "order_id": 1001,
        "name": "#1042",
        "ordered_at": NOW - timedelta(days=22),
        "currency": "EUR",
        "taxes_included": True,
        "cancelled": False,
        "lines": lines or (_line(),),
    }
    base.update(overrides)
    return ReturnableOrder(**base)


PHOTO = PhotoRef(message_id="m-1", index=0)
NO_PHOTOS = Evidence(photos=(), readable=True)


def _evaluate(
    policy: ActivePolicy | None = None,
    order: ReturnableOrder | None = None,
    *,
    reason: str = "too_small",
    items: tuple[RequestedItem, ...] = (RequestedItem(line_item_id=501, quantity=1),),
    exchange: tuple[RequestedExchange, ...] = (),
    variants: tuple[ExchangeVariant, ...] = (),
    evidence: Evidence = NO_PHOTOS,
    now: datetime = NOW,
    use_default_policy: bool = True,
) -> Eligible | Refused | Rejected:
    return evaluate_return(
        policy if policy is not None or not use_default_policy else _policy(),
        order or _order(),
        reason_code=reason,
        items=items,
        exchange=exchange,
        variants=variants,
        evidence=evidence,
        now=now,
    )


def test_without_policy_the_code_refuses_and_names_why() -> None:
    result = _evaluate(None, use_default_policy=False)

    assert isinstance(result, Refused)
    assert result.code == "policy_missing"
    assert result.team_reason == (
        "La tienda no tiene configurada su política de devoluciones y cambios: el agente no "
        "abre ninguna. Revisad el caso y configurad la política en el panel."
    )


def test_a_cancelled_order_is_refused() -> None:
    result = _evaluate(order=_order(cancelled=True))

    assert isinstance(result, Refused)
    assert result.code == "order_cancelled"


def test_an_exchange_when_the_store_has_none_is_refused() -> None:
    policy = _policy(exchanges={"enabled": False, "kinds": []})

    result = _evaluate(policy, exchange=(RequestedExchange(variant_id=88, quantity=1),))

    assert isinstance(result, Refused)
    assert result.code == "exchanges_disabled"


def test_a_reason_outside_the_list_goes_back_to_the_llm_with_the_valid_codes() -> None:
    result = _evaluate(reason="changed_mind")

    assert result == Rejected(
        code="reason_not_in_policy",
        detail="Motivo 'changed_mind' fuera de la política. Códigos válidos: defective, too_small.",
    )


def test_an_item_that_is_not_returnable_lists_the_returnable_ones() -> None:
    result = _evaluate(items=(RequestedItem(line_item_id=999, quantity=1),))

    assert result == Rejected(
        code="item_not_returnable",
        detail=(
            "El artículo 999 no se puede devolver (sin enviar o ya devuelto). Devolvibles: "
            "501 'Blusa - Marino / S' (máx. 2)."
        ),
    )


def test_more_units_than_returnable_go_back_to_the_llm() -> None:
    result = _evaluate(items=(RequestedItem(line_item_id=501, quantity=3),))

    assert isinstance(result, Rejected)
    assert result.code == "quantity_exceeds_returnable"


def test_excluded_tag_refuses_and_unknown_product_too_when_there_are_exclusions() -> None:
    excluded = _evaluate(order=_order(_line(product_tags=frozenset({"final-sale"}))))
    unknown = _evaluate(order=_order(_line(product_id=None, product_tags=None)))
    no_exclusions = _evaluate(
        _policy(excluded_product_tags=[]),
        order=_order(_line(product_id=None, product_tags=None)),
    )

    assert isinstance(excluded, Refused) and excluded.code == "product_excluded"
    assert isinstance(unknown, Refused) and unknown.code == "product_unknown"
    assert isinstance(no_exclusions, Eligible)


def test_the_window_counts_from_the_event_the_store_chose() -> None:
    last_day = datetime(2026, 10, 30, 23, 59, 59, tzinfo=UTC)
    in_time = _evaluate(now=last_day)
    late = _evaluate(now=last_day + timedelta(seconds=1))
    by_shipment = _evaluate(
        _policy(window={"days": 30, "starts_at": "shipment"}),
        now=last_day,
    )

    assert isinstance(in_time, Eligible)
    assert isinstance(late, Refused)
    assert late.code == "outside_window"
    assert late.params == {"deadline": "2026-10-30"}
    assert isinstance(by_shipment, Refused) and by_shipment.code == "outside_window"


def test_the_last_day_ends_at_midnight_in_the_store_zone() -> None:
    from zoneinfo import ZoneInfo

    order = _order(_line(delivered_at=datetime(2026, 9, 30, 21, 0, tzinfo=UTC)))
    half_past_midnight_in_madrid = datetime(2026, 10, 30, 23, 30, tzinfo=UTC)

    def at(tz: Any) -> Eligible | Refused | Rejected:
        return evaluate_return(
            _policy(),
            order,
            reason_code="too_small",
            items=(RequestedItem(line_item_id=501, quantity=1),),
            exchange=(),
            variants=(),
            evidence=NO_PHOTOS,
            now=half_past_midnight_in_madrid,
            tz=tz,
        )

    madrid = at(ZoneInfo("Europe/Madrid"))
    assert isinstance(madrid, Refused) and madrid.params == {"deadline": "2026-10-30"}
    assert isinstance(at(UTC), Eligible)


def test_counting_from_delivery_without_a_delivery_date_refuses() -> None:
    result = _evaluate(order=_order(_line(delivered_at=None)))

    assert isinstance(result, Refused)
    assert result.code == "delivery_date_unknown"


def test_photo_reason_needs_a_photo_and_a_channel_that_brings_it() -> None:
    missing = _evaluate(reason="defective")
    unreadable = _evaluate(reason="defective", evidence=Evidence(photos=(), readable=False))
    present = _evaluate(reason="defective", evidence=Evidence(photos=(PHOTO,), readable=True))

    assert isinstance(missing, Rejected) and missing.code == "evidence_missing"
    assert isinstance(unreadable, Refused) and unreadable.code == "evidence_unreadable"
    assert isinstance(present, Eligible)
    assert present.evidence == (PHOTO,)


def test_variant_exchanges_must_stay_on_the_same_product_and_be_available() -> None:
    exchange = (RequestedExchange(variant_id=88, quantity=1),)
    other_product = ExchangeVariant(variant_id=88, product_id=12, title="Bolso", available=True)
    sold_out = ExchangeVariant(variant_id=88, product_id=77, title="Blusa - M", available=False)
    same = ExchangeVariant(variant_id=88, product_id=77, title="Blusa - M", available=True)

    kind = _evaluate(exchange=exchange, variants=(other_product,))
    stock = _evaluate(exchange=exchange, variants=(sold_out,))
    missing = _evaluate(exchange=exchange, variants=())
    ok = _evaluate(exchange=exchange, variants=(same,))
    any_product = _evaluate(
        _policy(
            exchanges={
                "enabled": True,
                "kinds": ["product"],
                "requires_approval": True,
                "higher_price": "customer_pays",
                "lower_price": "refund_difference",
                "ship_replacement": "after_receipt",
            }
        ),
        exchange=exchange,
        variants=(other_product,),
    )

    assert isinstance(kind, Rejected) and kind.code == "exchange_kind_not_allowed"
    assert isinstance(stock, Rejected) and stock.code == "exchange_variant_unavailable"
    assert isinstance(missing, Rejected) and missing.code == "exchange_variant_unavailable"
    assert isinstance(ok, Eligible)
    assert isinstance(any_product, Eligible)


def test_returns_follow_the_policy_flag_and_exchanges_always_need_approval() -> None:
    plain = _evaluate()
    strict = _evaluate(_policy(returns_require_approval=True))
    exchange = _evaluate(
        exchange=(RequestedExchange(variant_id=88, quantity=1),),
        variants=(
            ExchangeVariant(variant_id=88, product_id=77, title="Blusa - M", available=True),
        ),
    )

    assert isinstance(plain, Eligible) and plain.requires_approval is False
    assert isinstance(strict, Eligible) and strict.requires_approval is True
    assert isinstance(exchange, Eligible) and exchange.requires_approval is True


def test_shipping_payer_and_fee_follow_the_fault_of_the_reason() -> None:
    customer = _evaluate()
    store = _evaluate(reason="defective", evidence=Evidence(photos=(PHOTO,), readable=True))

    assert isinstance(customer, Eligible)
    assert customer.shipping_payer == "customer"
    assert customer.fee is not None and customer.fee.amount == Decimal("4.95")
    assert isinstance(store, Eligible)
    assert store.shipping_payer == "store"
    assert store.fee is None


def _built(*args: Any, **kwargs: Any) -> ReturnPlan:
    plan = build_plan(*args, **kwargs)
    assert isinstance(plan, ReturnPlan), plan
    return plan


def _calc(returned: str, tax: str, exchanged: str | None = None) -> ReturnCalculation:
    return ReturnCalculation(
        currency="EUR",
        returned=(
            CalculatedLine(
                key="gid://shopify/FulfillmentLineItem/9001",
                quantity=1,
                subtotal=Decimal(returned),
                tax=Decimal(tax),
            ),
        ),
        exchanged=(
            (
                CalculatedLine(
                    key="gid://shopify/ProductVariant/88",
                    quantity=1,
                    subtotal=Decimal(exchanged),
                    tax=Decimal("0"),
                ),
            )
            if exchanged
            else ()
        ),
    )


def test_settlement_nets_items_minus_fee_with_tax_included() -> None:
    eligible = _evaluate()
    assert isinstance(eligible, Eligible)

    plan = _built(eligible, _calc("-52.15", "-9.05"), requested_at=NOW)

    settlement = plan.settlement
    assert settlement.currency == "EUR"
    assert settlement.returned_total == Decimal("52.15")
    assert settlement.fee == Decimal("4.95")
    assert settlement.balance == Decimal("47.20")
    assert plan.policy_version == 7
    assert plan.requested_at == NOW
    assert plan.lines[0].fulfillment_line_item_id == "gid://shopify/FulfillmentLineItem/9001"


def test_settlement_adds_tax_when_prices_exclude_it() -> None:
    eligible = _evaluate(
        _policy(
            shipping={
                "method": "customer_ships",
                "return_address": "Calle Mayor 1, Madrid",
                "payer": {"store_fault": "store", "customer_fault": "customer"},
            }
        ),
        order=_order(taxes_included=False),
    )
    assert isinstance(eligible, Eligible)

    plan = _built(eligible, _calc("-50.00", "-10.50"), requested_at=NOW)

    assert plan.settlement.returned_total == Decimal("60.50")
    assert plan.settlement.fee == Decimal("0")
    assert plan.settlement.balance == Decimal("60.50")


def test_exchange_difference_is_negative_when_the_new_item_costs_more() -> None:
    eligible = _evaluate(
        exchange=(RequestedExchange(variant_id=88, quantity=1),),
        variants=(
            ExchangeVariant(variant_id=88, product_id=77, title="Blusa - M", available=True),
        ),
    )
    assert isinstance(eligible, Eligible)

    plan = _built(eligible, _calc("-52.15", "-9.05", exchanged="60.00"), requested_at=NOW)

    assert plan.settlement.exchanged_total == Decimal("60.00")
    assert plan.settlement.balance == Decimal("-12.80")


def test_a_fee_in_another_currency_is_left_to_the_team() -> None:
    eligible = _evaluate(order=_order(currency="USD"))
    assert isinstance(eligible, Eligible)

    plan = _built(
        eligible,
        ReturnCalculation(
            currency="USD",
            returned=(
                CalculatedLine(
                    key="gid://shopify/FulfillmentLineItem/9001",
                    quantity=1,
                    subtotal=Decimal("-76.95"),
                    tax=Decimal("0"),
                ),
            ),
            exchanged=(),
        ),
        requested_at=NOW,
    )

    assert plan.settlement.fee == Decimal("0")
    assert plan.settlement.fee_pending is not None
    assert plan.settlement.fee_pending.currency == "EUR"
    assert plan.settlement.balance is None
    assert plan.shopify_fee is None


def test_settlement_note_tells_the_team_what_to_refund() -> None:
    eligible = _evaluate()
    assert isinstance(eligible, Eligible)

    plan = _built(eligible, _calc("-52.15", "-9.05"), requested_at=NOW)

    assert plan.team_note() == (
        "Auyan · devolución #1042 (política v7)\n"
        "Motivo: Pequeña [too_small], culpa del cliente\n"
        "Devuelve: 1 x Blusa - Marino / S = 52.15 EUR\n"
        "Envío de vuelta: etiqueta de la tienda, paga el cliente; tarifa 4.95 EUR\n"
        "A devolver al recibir: 47.20 EUR, al método de pago original"
    )


@pytest.mark.parametrize("bad", [0, -1])
def test_requested_quantities_are_positive(bad: int) -> None:
    with pytest.raises(ValueError):
        RequestedItem(line_item_id=501, quantity=bad)


def test_customer_photos_are_the_images_the_customer_sent_indexed_like_the_inbox() -> None:
    history = [
        {
            "id": "m-1",
            "role": "customer",
            "attachments": [
                {"path": "t/c/m-1/0.ogg", "kind": "audio", "mime_type": "audio/ogg"},
                {"kind": "image"},
                {"path": "t/c/m-1/1.jpg", "kind": "image", "mime_type": "image/jpeg"},
            ],
        },
        {
            "id": "m-2",
            "role": "agent_ai",
            "attachments": [
                {"path": "t/c/m-2/0.jpg", "kind": "image"},
            ],
        },
        {
            "id": "m-3",
            "role": "customer",
            "attachments": [
                {"filename": "foto.png", "mime_type": "image/png"},
            ],
        },
    ]

    assert customer_photos(history) == (
        PhotoRef(message_id="m-1", index=1),
        PhotoRef(message_id="m-3", index=0),
    )


BLUSA_M = ExchangeVariant(variant_id=88, product_id=77, title="Blusa - M", available=True)
SWAP = (RequestedExchange(variant_id=88, quantity=1),)


def _exchange_policy(**terms: Any) -> ActivePolicy:
    base = {
        "enabled": True,
        "kinds": ["variant"],
        "requires_approval": True,
        "higher_price": "customer_pays",
        "lower_price": "refund_difference",
        "ship_replacement": "after_receipt",
    }
    return _policy(
        exchanges={**base, **terms},
        shipping={
            "method": "customer_ships",
            "return_address": "Calle Mayor 1, Madrid",
            "payer": {"store_fault": "store", "customer_fault": "customer"},
        },
    )


def _swap(policy: ActivePolicy, exchanged: str) -> ReturnPlan | Rejected:
    eligible = _evaluate(policy, exchange=SWAP, variants=(BLUSA_M,))
    assert isinstance(eligible, Eligible)
    return build_plan(eligible, _calc("-52.15", "-9.05", exchanged=exchanged), requested_at=NOW)


def test_exchange_approval_is_the_store_choice() -> None:
    free = _evaluate(_exchange_policy(requires_approval=False), exchange=SWAP, variants=(BLUSA_M,))

    assert isinstance(free, Eligible) and free.requires_approval is False


@pytest.mark.parametrize(
    ("higher", "balance", "rule"),
    [
        ("customer_pays", Decimal("-7.85"), "customer_pays"),
        ("store_absorbs", Decimal("0"), "store_absorbs"),
    ],
)
def test_a_dearer_exchange_follows_the_store_rule(higher: str, balance: Decimal, rule: str) -> None:
    plan = _swap(_exchange_policy(higher_price=higher), "60.00")

    assert isinstance(plan, ReturnPlan)
    assert plan.settlement.price_difference == Decimal("7.85")
    assert plan.settlement.price_rule == rule
    assert plan.settlement.balance == balance


def test_a_dearer_exchange_the_store_does_not_allow_goes_back_to_the_llm() -> None:
    result = _swap(_exchange_policy(higher_price="not_allowed"), "60.00")

    assert isinstance(result, Rejected) and result.code == "exchange_price_higher"


@pytest.mark.parametrize(
    ("lower", "balance", "refund_as"),
    [
        ("refund_difference", Decimal("12.15"), "original_payment"),
        ("store_credit", Decimal("12.15"), "store_credit"),
        ("no_refund", Decimal("0"), "original_payment"),
    ],
)
def test_a_cheaper_exchange_follows_the_store_rule(
    lower: str, balance: Decimal, refund_as: str
) -> None:
    plan = _swap(_exchange_policy(lower_price=lower), "40.00")

    assert isinstance(plan, ReturnPlan)
    assert plan.settlement.balance == balance
    assert plan.settlement.refund_as == refund_as
    assert plan.ship_replacement == "after_receipt"


def test_refund_method_is_the_store_choice_or_asked_to_the_customer() -> None:
    credit = _evaluate(_policy(refund_method="store_credit"))
    ask = _evaluate(_policy(refund_method="customer_choice"))
    chosen = evaluate_return(
        _policy(refund_method="customer_choice"),
        _order(),
        reason_code="too_small",
        items=(RequestedItem(line_item_id=501, quantity=1),),
        exchange=(),
        variants=(),
        evidence=NO_PHOTOS,
        now=NOW,
        refund_preference="store_credit",
    )

    assert isinstance(credit, Eligible) and credit.refund_as == "store_credit"
    assert isinstance(ask, Rejected) and ask.code == "refund_preference_missing"
    assert isinstance(chosen, Eligible) and chosen.refund_as == "store_credit"


def test_restocking_fee_follows_the_fault_and_comes_off_the_refund() -> None:
    eligible = _evaluate(
        _policy(restocking_fee_percent={"store_fault": "0", "customer_fault": "10"})
    )
    assert isinstance(eligible, Eligible)

    plan = _built(eligible, _calc("-52.15", "-9.05"), requested_at=NOW)

    assert plan.settlement.restocking_fee == Decimal("5.22")
    assert plan.settlement.balance == Decimal("41.98")
    assert "Reposición: 10% = 5.22 EUR" in plan.team_note()


def test_exclusions_ignore_the_case_of_shopify_tags() -> None:
    result = _evaluate(order=_order(_line(product_tags=frozenset({"Final-Sale"}))))

    assert isinstance(result, Refused) and result.code == "product_excluded"


def test_label_cost_leaves_the_balance_to_the_team() -> None:
    policy = _policy(
        shipping={
            "method": "store_label",
            "payer": {"store_fault": "store", "customer_fault": "customer"},
            "customer_fee_mode": "label_cost",
        }
    )
    eligible = _evaluate(policy)
    assert isinstance(eligible, Eligible)

    plan = _built(eligible, _calc("-52.15", "-9.05"), requested_at=NOW)

    assert plan.settlement.balance is None
    assert "coste real de la etiqueta" in plan.team_note()


def test_an_exchange_gives_back_at_most_the_returned_units() -> None:
    five = _evaluate(
        _exchange_policy(),
        exchange=(RequestedExchange(variant_id=88, quantity=5),),
        variants=(BLUSA_M,),
    )
    twice = _evaluate(
        _exchange_policy(),
        exchange=(
            RequestedExchange(variant_id=88, quantity=1),
            RequestedExchange(variant_id=88, quantity=1),
        ),
        variants=(BLUSA_M,),
    )

    assert isinstance(five, Rejected) and five.code == "exchange_quantity_exceeds_returned"
    assert isinstance(twice, Rejected) and twice.code == "exchange_variant_repeated"


def test_the_store_decides_if_a_return_with_photo_needs_approval() -> None:
    photo = Evidence(photos=(PHOTO,), readable=True)
    reviewed = _evaluate(
        _policy(evidence_requires_approval=True), reason="defective", evidence=photo
    )
    trusted = _evaluate(
        _policy(evidence_requires_approval=False), reason="defective", evidence=photo
    )

    assert isinstance(reviewed, Eligible) and reviewed.requires_approval is True
    assert isinstance(trusted, Eligible) and trusted.requires_approval is False


def test_an_exchange_needs_stock_for_every_unit_when_the_store_does_not_oversell() -> None:
    low = ExchangeVariant(variant_id=88, product_id=77, title="Blusa - M", available=True, stock=1)
    order = _order(_line(returnable_quantity=2))
    two = (RequestedExchange(variant_id=88, quantity=2),)
    items = (RequestedItem(line_item_id=501, quantity=2),)

    short = _evaluate(_exchange_policy(), order, items=items, exchange=two, variants=(low,))
    oversell = _evaluate(
        _exchange_policy(),
        order,
        items=items,
        exchange=two,
        variants=(
            ExchangeVariant(
                variant_id=88, product_id=77, title="Blusa - M", available=True, stock=None
            ),
        ),
    )

    assert isinstance(short, Rejected) and short.code == "exchange_variant_unavailable"
    assert isinstance(oversell, Eligible)


def test_three_decimal_currencies_keep_their_precision() -> None:
    eligible = _evaluate(
        _policy(restocking_fee_percent={"store_fault": "0", "customer_fault": "10"}),
        order=_order(currency="KWD", taxes_included=True),
    )
    assert isinstance(eligible, Eligible)

    plan = _built(
        eligible,
        ReturnCalculation(
            currency="KWD",
            returned=(
                CalculatedLine(
                    key="gid://shopify/FulfillmentLineItem/9001",
                    quantity=1,
                    subtotal=Decimal("-12.345"),
                    tax=Decimal("0"),
                ),
            ),
            exchanged=(),
        ),
        requested_at=NOW,
    )

    assert plan.settlement.returned_total == Decimal("12.345")
    assert plan.settlement.restocking_fee == Decimal("1.235")


def _restocking(currency: str, subtotal: str, percent: str) -> ReturnPlan:
    eligible = _evaluate(
        _policy(restocking_fee_percent={"store_fault": "0", "customer_fault": percent}),
        order=_order(currency=currency, taxes_included=True),
    )
    assert isinstance(eligible, Eligible)
    return _built(
        eligible,
        ReturnCalculation(
            currency=currency,
            returned=(
                CalculatedLine(
                    key="gid://shopify/FulfillmentLineItem/9001",
                    quantity=1,
                    subtotal=Decimal(subtotal),
                    tax=Decimal("0"),
                ),
            ),
            exchanged=(),
        ),
        requested_at=NOW,
    )


@pytest.mark.parametrize(
    ("currency", "subtotal", "percent", "fee"),
    [
        # Sin decimales: 1005 x 10% = 100.5 → 101 yenes, nunca 100.50.
        ("JPY", "-1005", "10", "101"),
        # Tres decimales aunque Shopify mande el importe con uno: 12.5 x 7% = 0.875.
        ("KWD", "-12.5", "7", "0.875"),
        ("EUR", "-52.15", "10", "5.22"),
    ],
)
def test_the_restocking_fee_rounds_to_the_decimals_of_the_currency(
    currency: str, subtotal: str, percent: str, fee: str
) -> None:
    plan = _restocking(currency, subtotal, percent)

    assert str(plan.settlement.restocking_fee) == fee


def _partial_swap(policy: ActivePolicy, exchanged: str, **kw: Any) -> ReturnPlan | Rejected:
    """Devuelve 2 blusas (52.15 cada una) y pide 1 a cambio por `exchanged`."""
    eligible = evaluate_return(
        policy,
        _order(),
        reason_code="too_small",
        items=(RequestedItem(line_item_id=501, quantity=2),),
        exchange=SWAP,
        variants=(BLUSA_M,),
        evidence=NO_PHOTOS,
        now=NOW,
        **kw,
    )
    assert isinstance(eligible, Eligible), eligible
    calculation = ReturnCalculation(
        currency="EUR",
        returned=(
            CalculatedLine(
                key="gid://shopify/FulfillmentLineItem/9001",
                quantity=2,
                subtotal=Decimal("-104.30"),
                tax=Decimal("0"),
            ),
        ),
        exchanged=(
            CalculatedLine(
                key="gid://shopify/ProductVariant/88",
                quantity=1,
                subtotal=Decimal(exchanged),
                tax=Decimal("0"),
            ),
        ),
    )
    return build_plan(eligible, calculation, requested_at=NOW)


def test_returned_units_not_exchanged_are_refunded_by_the_refund_method() -> None:
    """Un cambio parcial no mete en `lower_price` las unidades que solo se devuelven: se
    reembolsan como una devolución, según `refund_method`."""
    plan = _partial_swap(_exchange_policy(lower_price="no_refund"), "52.15")

    assert isinstance(plan, ReturnPlan)
    s = plan.settlement
    assert (s.exchanged_value, s.price_difference, s.price_rule) == (
        Decimal("52.15"),
        Decimal("0"),
        "none",
    )
    assert s.balance == Decimal("52.15")
    assert s.payouts == {"original_payment": Decimal("52.15")}
    assert "A devolver al recibir: 52.15 EUR, al método de pago original" in plan.team_note()


def test_a_partial_cheaper_exchange_splits_the_refund_and_the_credit() -> None:
    plan = _partial_swap(_exchange_policy(lower_price="store_credit"), "40.00")

    assert isinstance(plan, ReturnPlan)
    assert plan.settlement.price_difference == Decimal("-12.15")
    assert plan.settlement.balance == Decimal("64.30")
    assert plan.settlement.payouts == {
        "original_payment": Decimal("52.15"),
        "store_credit": Decimal("12.15"),
    }


def test_a_partial_exchange_asks_how_to_refund_when_the_store_lets_choose() -> None:
    policy = _policy(
        refund_method="customer_choice",
        exchanges=_exchange_policy().policy.exchanges.model_dump(),
    )
    ask = evaluate_return(
        policy,
        _order(),
        reason_code="too_small",
        items=(RequestedItem(line_item_id=501, quantity=2),),
        exchange=SWAP,
        variants=(BLUSA_M,),
        evidence=NO_PHOTOS,
        now=NOW,
    )
    full = _evaluate(policy, exchange=SWAP, variants=(BLUSA_M,))
    chosen = _partial_swap(policy, "52.15", refund_preference="store_credit")

    assert isinstance(ask, Rejected) and ask.code == "refund_preference_missing"
    assert isinstance(full, Eligible)
    assert isinstance(chosen, ReturnPlan)
    # 52.15 de la blusa que solo se devuelve, menos la tarifa de 4.95 de la etiqueta.
    assert chosen.settlement.payouts == {"store_credit": Decimal("47.20")}
