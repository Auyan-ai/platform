"""Identidad del comprador por teléfono: normalización a E.164 y comparación.

Determinista (regla dura del Sprint 2): el teléfono decide identidad y ownership L3,
así que nunca se compara texto libre. Todo teléfono pasa por `normalize_phone` y se
compara en E.164 exacto.
"""

from __future__ import annotations

import logging

import phonenumbers

logger = logging.getLogger(__name__)

DEFAULT_PHONE_REGION = "ES"


def normalize_phone(raw: str | None, default_region: str = DEFAULT_PHONE_REGION) -> str | None:
    """E.164 (`+34600111222`) o None si no es un número válido.

    Acepta `+34 600 11 12 22`, `600111222` (región por defecto), `0034600111222` y el
    formato de WhatsApp sin `+` (`34600111222`) cuando la región por defecto no lo
    reconoce como nacional.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("00"):
        text = "+" + text[2:]
    for candidate, region in _candidates(text, default_region):
        try:
            parsed = phonenumbers.parse(candidate, region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    return None


def _candidates(text: str, default_region: str) -> list[tuple[str, str | None]]:
    if text.startswith("+"):
        return [(text, None)]
    candidates: list[tuple[str, str | None]] = [(text, default_region.upper())]
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        # WhatsApp/Meta envía el número internacional sin '+'.
        candidates.append(("+" + digits, None))
    return candidates


def phones_match(a: str | None, b: str | None, default_region: str = DEFAULT_PHONE_REGION) -> bool:
    """True si ambos teléfonos son válidos y coinciden en E.164."""
    na = normalize_phone(a, default_region)
    nb = normalize_phone(b, default_region)
    return na is not None and na == nb
