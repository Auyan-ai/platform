"""Importes de una respuesta respaldados (o no), con su moneda, por la evidencia (#332)."""

from __future__ import annotations

import json
from decimal import Decimal

from apps.api.services.amount_grounding import (
    Amount,
    AmountProblem,
    amounts_in,
    unbacked_amounts,
)

# Salida de get_order_status en staging antes de #317 (trace c7b32bac): la moneda solo a
# nivel de pedido, los precios sin ella.
_ORDER_BEFORE_317 = {
    "found": True,
    "order_number": "#1431",
    "currency": "USD",
    "line_items": [
        {"line_item_id": 17463441162520, "price": "68.95", "quantity": 1, "title": "Blusa"},
        {"line_item_id": 17463441195288, "price": "76.95", "quantity": 1, "title": "Bolso"},
    ],
    "total_price": "145.90",
}

# La misma salida desde #317: cada importe con su moneda.
_ORDER_AFTER_317 = {
    "found": True,
    "order_number": "#1431",
    "line_items": [
        {"line_item_id": 1, "title": "Blusa", "price": {"amount": "68.95", "currency": "USD"}},
        {"line_item_id": 2, "title": "Bolso", "price": {"amount": "76.95", "currency": "USD"}},
    ],
    "total": {"amount": "145.90", "currency": "USD"},
}

_POLICY = (
    "Las devoluciones adicionales de un mismo pedido tienen un coste de 3,95 €, "
    "que se descuentan del reembolso."
)


def _evidence(order: dict) -> str:
    return f"{_POLICY}\n- shopify.get_order_status → {json.dumps(order, ensure_ascii=False)}"


def test_c7b32bac_euros_for_a_usd_order_are_rejected() -> None:
    response = "El pedido incluye:\n- Blusa Satinada (68,95 €)\n- Bolso Bandolera (76,95 €)"
    expected = [
        AmountProblem("68,95 €", frozenset({"USD"})),
        AmountProblem("76,95 €", frozenset({"USD"})),
    ]
    assert unbacked_amounts(response, _evidence(_ORDER_BEFORE_317)) == expected
    assert unbacked_amounts(response, _evidence(_ORDER_AFTER_317)) == expected


def test_same_currency_in_any_format_is_backed() -> None:
    for response in (
        "Blusa (68,95 USD) y Bolso (76,95 USD): total 145,90 USD.",
        "La blusa costó 68,95 $ y el bolso 76,95$.",
        "Blusa US$68.95, bolso US$ 76.95, total $145.90.",
        "Total del pedido: USD 145,9.",
        "Pagaste 145,90 dólares.",
    ):
        for order in (_ORDER_BEFORE_317, _ORDER_AFTER_317):
            assert unbacked_amounts(response, _evidence(order)) == [], response


def test_amount_from_store_text_keeps_its_currency() -> None:
    evidence = _evidence(_ORDER_AFTER_317)
    assert unbacked_amounts("La segunda devolución cuesta 3,95 euros.", evidence) == []
    assert unbacked_amounts("La segunda devolución cuesta 3,95 USD.", evidence) == [
        AmountProblem("3,95 USD", frozenset({"EUR"}))
    ]


def test_amount_missing_from_the_evidence_is_unbacked() -> None:
    assert unbacked_amounts("Te devolvemos 50,00 USD.", _evidence(_ORDER_AFTER_317)) == [
        AmountProblem("50,00 USD", frozenset())
    ]


def test_thousands_separators_in_spanish_and_english() -> None:
    evidence = json.dumps({"total": {"amount": "1234.50", "currency": "EUR"}})
    assert unbacked_amounts("Total: 1.234,50 € (o €1,234.50).", evidence) == []
    assert unbacked_amounts("Total: 1\u00a0234,50\u00a0€.", evidence) == []


def test_numbers_without_a_currency_are_not_amounts() -> None:
    text = (
        "Pedido #1431 del 30/09/2026, talla 38 EU, 2 unidades, 10 % de descuento, "
        "código 4521, entrega en 3-5 días laborables, teléfono 612 345 678."
    )
    assert amounts_in(text) == []


def test_amounts_carry_value_and_currency() -> None:
    assert amounts_in("Blusa 68,95 €, envío £4 y 1.234,50 EUR") == [
        Amount(Decimal("68.95"), frozenset({"EUR"}), "68,95 €"),
        Amount(Decimal("4"), frozenset({"GBP"}), "£4"),
        Amount(Decimal("1234.50"), frozenset({"EUR"}), "1.234,50 EUR"),
    ]
