"""Importes de una respuesta, con su moneda, y si la evidencia del agente los respalda.

La regla global del agente da cada importe en la moneda que trae la herramienta, sin
deducirla ni convertirla. Comprobarlo es literal: lo hace el código, no el supervisor
LLM, que aprobó "68,95 €" en un pedido en USD (#332).

Criterio: solo es importe un número pegado a una marca de moneda (símbolo, código ISO o
la palabra euro/dólar), antes o después. Tallas, porcentajes, números de pedido, fechas,
teléfonos y cantidades no llevan marca y no se miran. En la evidencia cuenta además el
JSON de las herramientas: un objeto con `currency` da esa moneda a los números que
contiene, también a los anidados.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

_ISO_CODES = frozenset(
    {
        "EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON",
        "BGN", "ISK", "TRY", "MXN", "CAD", "AUD", "NZD", "ARS", "CLP", "COP", "PEN",
        "UYU", "BOB", "PYG", "BRL", "JPY", "CNY", "HKD", "SGD", "INR", "ZAR", "AED",
    }
)  # fmt: skip
# "$" y "dólares" no dicen cuál: valen para cualquier moneda que se escribe con "$".
_DOLLAR_SIGN = frozenset(
    {"USD", "CAD", "AUD", "NZD", "MXN", "ARS", "CLP", "COP", "UYU", "SGD", "HKD"}
)
_EUR = frozenset({"EUR"})

_MARKERS: dict[str, frozenset[str]] = {
    "us$": frozenset({"USD"}),
    "$": _DOLLAR_SIGN,
    "€": _EUR,
    "£": frozenset({"GBP"}),
    "euro": _EUR,
    "euros": _EUR,
    "dólar": _DOLLAR_SIGN,
    "dólares": _DOLLAR_SIGN,
    "dolar": _DOLLAR_SIGN,
    "dolares": _DOLLAR_SIGN,
    "dollar": _DOLLAR_SIGN,
    "dollars": _DOLLAR_SIGN,
}

# Miles con punto, coma o espacio fino; decimales con 1-2 cifras tras punto o coma.
_NUMBER = (
    r"(?<![\d.,])(?:\d{1,3}(?:[.,\u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?!\d)"
)
_ISO = "|".join(sorted(_ISO_CODES))
_SYMBOL = r"US\$|\$|€|£"
_WORD = r"(?i:euros?|d[óo]lar(?:es)?|dollars?)\b"
_GAP = r"[ \u00a0\u202f]?"
_AMOUNT_RE = re.compile(
    rf"(?:(?P<pre>{_SYMBOL}|\b(?:{_ISO})\b){_GAP}(?P<n1>{_NUMBER}))"
    rf"|(?:(?P<n2>{_NUMBER}){_GAP}(?P<post>{_SYMBOL}|(?:{_ISO})\b|{_WORD}))"
)
_DECIMAL_TAIL = re.compile(r"[.,](\d{1,2})$")
_PLAIN_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_ISO_SHAPE = re.compile(r"[A-Z]{3}")
_CURRENCY_KEYS = ("currency", "currency_code")


@dataclass(frozen=True)
class Amount:
    value: Decimal
    # Monedas ISO que puede ser: una para "€" o "USD", varias para "$".
    currencies: frozenset[str]
    written: str


@dataclass(frozen=True)
class AmountProblem:
    written: str
    # Monedas con las que aparece ese valor en la evidencia; vacío si no aparece.
    evidence_currencies: frozenset[str]


def _parse_number(number: str) -> Decimal:
    digits = re.sub(r"[\u00a0\u202f]", "", number)
    tail = _DECIMAL_TAIL.search(digits)
    integer = digits[: tail.start()] if tail else digits
    integer = re.sub(r"[.,]", "", integer)
    return Decimal(f"{integer}.{tail.group(1)}" if tail else integer)


def _currencies(marker: str) -> frozenset[str]:
    if marker in _ISO_CODES:
        return frozenset({marker})
    return _MARKERS[marker.lower()]


def amounts_in(text: str) -> list[Amount]:
    return [
        Amount(
            _parse_number(match["n1"] or match["n2"]),
            _currencies(match["pre"] or match["post"]),
            match.group(0),
        )
        for match in _AMOUNT_RE.finditer(text)
    ]


def _segments(text: str) -> Iterator[str | dict[str, Any]]:
    """Trozos de texto y los objetos JSON incrustados entre ellos (salidas de herramientas,
    datos ya verificados)."""
    decoder = json.JSONDecoder()
    start = 0
    brace = text.find("{")
    while brace != -1:
        try:
            data, end = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            brace = text.find("{", brace + 1)
            continue
        yield text[start:brace]
        yield data
        start = end
        brace = text.find("{", end)
    yield text[start:]


def _amounts_in_data(data: Any, currency: str | None) -> Iterator[Amount]:
    if isinstance(data, dict):
        own = next((data[k] for k in _CURRENCY_KEYS if isinstance(data.get(k), str)), None)
        if own and _ISO_SHAPE.fullmatch(own):
            currency = own
        for key, value in data.items():
            if key not in _CURRENCY_KEYS:
                yield from _amounts_in_data(value, currency)
    elif isinstance(data, list):
        for item in data:
            yield from _amounts_in_data(item, currency)
    elif isinstance(data, str):
        yield from amounts_in(data)
        if currency and _PLAIN_NUMBER.fullmatch(data):
            yield Amount(Decimal(data), frozenset({currency}), data)
    elif currency and isinstance(data, int | float) and not isinstance(data, bool):
        yield Amount(Decimal(str(data)), frozenset({currency}), str(data))


def _evidence_currencies(evidence: str) -> dict[Decimal, frozenset[str]]:
    found: dict[Decimal, set[str]] = defaultdict(set)
    for segment in _segments(evidence):
        amounts = (
            amounts_in(segment) if isinstance(segment, str) else _amounts_in_data(segment, None)
        )
        for amount in amounts:
            found[amount.value] |= amount.currencies
    return {value: frozenset(currencies) for value, currencies in found.items()}


def unbacked_amounts(response: str, evidence: str) -> list[AmountProblem]:
    """Importes de `response` cuyo valor no aparece en `evidence` con una moneda compatible,
    en orden de aparición y sin repetir."""
    evidence_currencies = _evidence_currencies(evidence)
    problems: dict[AmountProblem, None] = {}
    for amount in amounts_in(response):
        backing = evidence_currencies.get(amount.value, frozenset())
        if not amount.currencies & backing:
            problems[AmountProblem(amount.written, backing)] = None
    return list(problems)
