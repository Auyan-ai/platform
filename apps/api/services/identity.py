"""Identidad del comprador (ADR 0013): remitente verificado, grants y claims de un pedido.

Determinista: el código decide quién es el comprador y qué pedidos toca, nunca el LLM.
Todo teléfono pasa por `normalize_phone` y se compara en E.164 exacto. El estado del
grafo, las trazas y las tablas guardan solo hashes (`ClaimHash`); el email o teléfono en
claro vive únicamente en `messages.metadata.identity_evidence`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, NewType

import phonenumbers
from apps.api.services.writing_surface import HELPDESK_CHANNELS, normalize_source

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


# ─── Teléfonos de un pedido ───────────────────────────────────────────────────


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


# ─── Remitente verificado (ADR 0013 §1) ───────────────────────────────────────

SenderOrigin = Literal["email", "phone"]

# Orígenes de ticket de helpdesk en los que el email del remitente cuenta como
# verificado: correo y formulario web. Chat, messaging, API o desconocido no cuentan:
# ahí el email lo teclea el visitante y nadie lo comprueba.
_EMAIL_SENDER_SOURCES = frozenset({"email", "web", "webform", "contactform", "helpcenter"})


def sender_origin(channel: str | None, source_channel: str | None) -> SenderOrigin | None:
    """Qué contacto del remitente está verificado en este mensaje, según su origen.

    WhatsApp verifica el teléfono; el canal `email` y los tickets de helpdesk de origen
    correo o formulario web verifican el email. El resto no verifica nada.
    """
    if channel == "whatsapp":
        return "phone"
    if channel == "email":
        return "email"
    if channel in HELPDESK_CHANNELS and source_channel:
        if normalize_source(source_channel) in _EMAIL_SENDER_SOURCES:
            return "email"
    return None


def default_phone_region(
    tenant_config: dict[str, Any] | None, tenant_facts: dict[str, Any] | None
) -> str:
    """Región por defecto del tenant para teléfonos sin prefijo (determinista)."""
    extra = (tenant_config or {}).get("extra") or {}
    for value in (extra.get("phone_default_region"), (tenant_facts or {}).get("country_code")):
        if isinstance(value, str) and len(value.strip()) == 2:
            return value.strip().upper()
    return DEFAULT_PHONE_REGION


# ─── Evidencia de identidad del mensaje (ADR 0013 §3, la escribe el intake) ───

EVIDENCE_KEY = "identity_evidence"


@dataclass(frozen=True)
class IdentityEvidence:
    """Contacto del remitente que el origen del mensaje verifica. Texto en claro."""

    email: str | None = None
    phone: str | None = None


def build_identity_evidence(
    channel: str | None,
    source_channel: str | None,
    *,
    email: str | None,
    phone: str | None,
) -> dict[str, str] | None:
    """`messages.metadata.identity_evidence` de un inbound, o None si nada se verifica.

    Solo entra el contacto que el origen verifica (`sender_origin`): el email de un correo
    o formulario web, el teléfono de WhatsApp. El email que teclea un visitante de chat no.
    """
    origin = sender_origin(channel, source_channel)
    if origin == "email" and email and email.strip():
        return {"sender_email": email.strip()}
    if origin == "phone":
        normalized = normalize_phone(phone)
        if normalized:
            return {"sender_phone": normalized}
    return None


def inbound_identity_evidence(
    history: list[dict[str, Any]] | None, inbound_message_id: str | None
) -> IdentityEvidence:
    """Evidencia del mensaje entrante del turno.

    Con `inbound_message_id`, la de ese mensaje; sin él, la del último mensaje del
    cliente. Mensaje desconocido o sin evidencia → vacía (nada verificado).
    """
    customer_messages = [m for m in history or [] if m.get("role") == "customer"]
    if inbound_message_id is not None:
        message = next((m for m in customer_messages if m.get("id") == inbound_message_id), None)
    else:
        message = customer_messages[-1] if customer_messages else None
    raw = ((message or {}).get("metadata") or {}).get(EVIDENCE_KEY)
    if not isinstance(raw, dict):
        return IdentityEvidence()
    email, phone = raw.get("sender_email"), raw.get("sender_phone")
    return IdentityEvidence(
        email=email if isinstance(email, str) and email.strip() else None,
        phone=phone if isinstance(phone, str) and phone.strip() else None,
    )


def evidence_from_state(state: Mapping[str, Any]) -> IdentityEvidence:
    """Evidencia del turno. El cliente del simulador escribe como remitente de correo."""
    if state.get("simulation_mode"):
        email = (state.get("end_customer") or {}).get("email")
        return IdentityEvidence(email=email if isinstance(email, str) and email else None)
    return inbound_identity_evidence(
        state.get("conversation_history"), state.get("inbound_message_id")
    )


# ─── Grants y claims (ADR 0013 §2) ────────────────────────────────────────────

Level = Literal["guest", "verified"]
Method = Literal["sender_email", "sender_phone", "signed_session", "otp", "order_contact"]
ClaimHash = NewType("ClaimHash", str)

_LEVEL_RANK: dict[Level, int] = {"guest": 1, "verified": 2}


def level_at_least(level: Level | None, minimum: Level | None) -> bool:
    """¿`level` alcanza `minimum`? Sin mínimo siempre; sin nivel nunca (si hay mínimo)."""
    if minimum is None:
        return True
    return level is not None and _LEVEL_RANK[level] >= _LEVEL_RANK[minimum]


def _claim(salt: str, kind: str, value: str) -> ClaimHash:
    digest = hmac.new(salt.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()
    return ClaimHash(digest)


def email_claim(salt: str, email: str | None) -> ClaimHash | None:
    if not email or not email.strip():
        return None
    return _claim(salt, "email", email.strip().casefold())


def phone_claim(
    salt: str, phone: str | None, region: str = DEFAULT_PHONE_REGION
) -> ClaimHash | None:
    normalized = normalize_phone(phone, region)
    return _claim(salt, "phone", normalized) if normalized else None


def order_claims(
    order: dict[str, Any], *, salt: str, region: str = DEFAULT_PHONE_REGION
) -> frozenset[ClaimHash]:
    """Claims de un pedido: sus emails, teléfonos y cliente de Shopify, ya hasheados."""
    customer = order.get("customer") or {}
    claims: set[ClaimHash | None] = {
        email_claim(salt, order.get("email")),
        email_claim(salt, customer.get("email")),
        *(phone_claim(salt, phone, region) for phone in order_phones(order, region)),
    }
    if customer.get("id") is not None:
        claims.add(_claim(salt, "shopify_customer", str(customer["id"])))
    return frozenset(c for c in claims if c is not None)


@dataclass(frozen=True)
class Grant:
    """Un permiso sobre pedidos y cómo se obtuvo.

    `verified` lleva la identidad en `claims`; `guest` apunta a un único `order_id`.
    `valid_until=None` significa que solo vale para este mensaje.
    """

    level: Level
    method: Method
    claims: frozenset[ClaimHash] = frozenset()
    order_id: int | None = None
    valid_until: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        return self.valid_until is None or self.valid_until > now

    def to_state(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "method": self.method,
            "claims": sorted(self.claims),
            "order_id": self.order_id,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
        }

    @classmethod
    def from_state(cls, data: Mapping[str, Any]) -> Grant:
        valid_until = data.get("valid_until")
        return cls(
            level=data["level"],
            method=data["method"],
            claims=frozenset(ClaimHash(c) for c in data.get("claims") or []),
            order_id=data.get("order_id"),
            valid_until=datetime.fromisoformat(valid_until) if valid_until else None,
        )


@dataclass(frozen=True)
class IdentityContext:
    """Los grants del turno. Es lo único de identidad que viaja por el estado del grafo."""

    grants: tuple[Grant, ...] = ()

    def active(self, now: datetime | None = None) -> tuple[Grant, ...]:
        moment = now or datetime.now(UTC)
        return tuple(g for g in self.grants if g.is_active(moment))

    def has_grant(self, level: Level | None = None) -> bool:
        """¿Hay algún grant vigente (de ese nivel, si se indica)?"""
        return any(level is None or g.level == level for g in self.active())

    def level_for(self, claims: frozenset[ClaimHash], order_id: int | None = None) -> Level | None:
        """`verified` si un grant verified toca los claims del pedido; `guest` si hay un
        grant guest con su `order_id`; si no, None."""
        grants = self.active()
        if any(g.level == "verified" and g.claims & claims for g in grants):
            return "verified"
        if order_id is not None and any(
            g.level == "guest" and g.order_id == order_id for g in grants
        ):
            return "guest"
        return None

    def summary(self) -> dict[str, Any]:
        """Nivel y métodos para trazas. Nunca claims ni contactos."""
        active = self.active()
        return {
            "level": "verified" if self.has_grant("verified") else None,
            "methods": sorted({g.method for g in active}),
        }

    def to_state(self) -> dict[str, Any]:
        return {"grants": [g.to_state() for g in self.grants]}

    @classmethod
    def from_state(cls, data: Mapping[str, Any] | None) -> IdentityContext:
        if not data:
            return cls()
        return cls(grants=tuple(Grant.from_state(g) for g in data.get("grants") or []))


def sender_identity(
    evidence: IdentityEvidence, *, salt: str, region: str = DEFAULT_PHONE_REGION
) -> IdentityContext:
    """Grants `verified` del remitente: uno por contacto que el origen verificó."""
    grants: list[Grant] = []
    email = email_claim(salt, evidence.email)
    if email is not None:
        grants.append(Grant("verified", "sender_email", claims=frozenset({email})))
    phone = phone_claim(salt, evidence.phone, region)
    if phone is not None:
        grants.append(Grant("verified", "sender_phone", claims=frozenset({phone})))
    return IdentityContext(tuple(grants))


_NOTE_UNVERIFIED = (
    "Identidad: no verificada. Este mensaje no llega desde el email ni el teléfono de una "
    "compra, así que no puedes consultar ni modificar pedidos. Si el cliente pregunta por "
    "uno, explícale con amabilidad que escriba desde el email con el que compró (o por "
    "WhatsApp desde el teléfono de la compra), u ofrécele pasar el caso a una persona del "
    "equipo. No uses ni pidas un email o teléfono que escriba en el chat."
)
_NOTE_METHODS: dict[str, str] = {"sender_email": "email", "sender_phone": "teléfono"}


def identity_note(identity: IdentityContext) -> str:
    """Línea para el bloque volátil de `reason`. Texto fijo, sin datos del cliente."""
    if not identity.has_grant("verified"):
        return _NOTE_UNVERIFIED
    methods = sorted({_NOTE_METHODS.get(g.method, g.method) for g in identity.active()})
    return f"Identidad: verificada por el remitente ({', '.join(methods)})."
