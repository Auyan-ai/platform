"""Identidad del comprador por teléfono: normalización a E.164 y comparación.

Determinista (regla dura del Sprint 2): el teléfono decide identidad y ownership L3,
así que nunca se compara texto libre. Todo teléfono pasa por `normalize_phone` y se
compara en E.164 exacto.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

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


# ─── Ownership de un pedido (gate L3 y privacidad de la dirección) ────────────


@dataclass(frozen=True)
class OwnershipCheck:
    """Resultado del gate de ownership. `reason` nunca lleva PII (va a logs)."""

    owner: bool
    reason: str  # email_match | phone_match | order_unresolved | no_customer_identity |
    #              email_mismatch | no_customer_phone | order_without_phone | phone_mismatch


def order_phones(order: dict[str, Any], default_region: str = DEFAULT_PHONE_REGION) -> set[str]:
    """Teléfonos del pedido en E.164: `phone`, `customer.phone` y los de las direcciones.

    Cada teléfono de dirección se normaliza con el país de esa dirección.
    """
    customer = order.get("customer") or {}
    candidates: list[tuple[Any, str]] = [
        (order.get("phone"), default_region),
        (customer.get("phone"), default_region),
    ]
    for key in ("shipping_address", "billing_address"):
        address = order.get(key) or {}
        region = str(address.get("country_code") or default_region)
        candidates.append((address.get("phone"), region))
    phones: set[str] = set()
    for raw, region in candidates:
        phone = normalize_phone(str(raw), region) if raw else None
        if phone:
            phones.add(phone)
    return phones


def _same_email(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.strip().casefold() == b.strip().casefold())


def check_order_ownership(
    order: dict[str, Any] | None,
    *,
    customer_email: str | None,
    customer_phone: str | None,
    default_region: str = DEFAULT_PHONE_REGION,
) -> OwnershipCheck:
    """¿El comprador de la conversación es el dueño del pedido? Fail-closed.

    Pasa si coincide el email (como siempre) **o** el teléfono E.164 del comprador con
    alguno del pedido. Sin identidad, pedido no resuelto o sin coincidencia → no dueño.
    """
    if not order:
        return OwnershipCheck(False, "order_unresolved")
    order_email = order.get("email") or (order.get("customer") or {}).get("email")
    if _same_email(customer_email, order_email):
        return OwnershipCheck(True, "email_match")
    phone = normalize_phone(customer_phone, default_region)
    if phone is not None:
        phones = order_phones(order, default_region)
        if phone in phones:
            return OwnershipCheck(True, "phone_match")
        return OwnershipCheck(False, "phone_mismatch" if phones else "order_without_phone")
    if customer_email:
        return OwnershipCheck(False, "email_mismatch")
    if customer_phone:
        return OwnershipCheck(False, "no_customer_phone")
    return OwnershipCheck(False, "no_customer_identity")


def default_phone_region(
    tenant_config: dict[str, Any] | None, tenant_facts: dict[str, Any] | None
) -> str:
    """Región por defecto del tenant para teléfonos sin prefijo (determinista)."""
    extra = (tenant_config or {}).get("extra") or {}
    for value in (extra.get("phone_default_region"), (tenant_facts or {}).get("country_code")):
        if isinstance(value, str) and len(value.strip()) == 2:
            return value.strip().upper()
    return DEFAULT_PHONE_REGION
