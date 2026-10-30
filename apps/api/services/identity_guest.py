"""Nivel `guest` (ADR 0013 §3 y §4): número de pedido + email o teléfono del pedido.

Todo es código y está probado: los parsers sacan los datos del texto del cliente, el HMAC
compara el contacto con los claims del pedido y los contadores de `identity_checks`
aplican los límites contra la enumeración. El LLM no decide nada de esto.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import asyncpg
import phonenumbers
from apps.api.db.identity_checks import (
    count_conversation_failures,
    insert_guest_check,
    list_active_guest_grants,
    list_attempt_keys,
    tenant_failure_stats,
)
from apps.api.services.identity import (
    DEFAULT_PHONE_REGION,
    ClaimHash,
    Grant,
    email_claim,
    phone_claim,
)
from apps.api.services.identity_messages import MessageKey, identity_message
from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from apps.api.skills.base import SkillContext, SkillRefusal

logger = logging.getLogger(__name__)

# Sin patrón propio del tenant, un número es un pedido solo si va con `#` o con una palabra
# clave cerca. Un año, un código postal o una talla no son un intento.
_HASH_ORDER_RE = re.compile(r"#\s?(\d{4,})")
_KEYWORD_ORDER_RE = re.compile(
    r"\b(?:pedidos?|[oó]rdenes|orden|orders?|compras?|n[º°]|n\.º|n[uú]mero|numero|num)"
    r"[^\d\n]{0,25}?(\d{4,})",
    re.IGNORECASE,
)
MAX_ITEMS_PER_KIND = 10
PROVIDED_CONTACT_KEY = "provided_contact"

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


class GuestPolicy(BaseModel):
    """Límites del nivel `guest`. Salen de `tenant_configurations.extra["identity_policy"]`."""

    model_config = ConfigDict(extra="ignore")

    guest_max_failures_per_conversation: int = Field(default=5, ge=1)
    guest_max_failures_per_tenant_hour: int = Field(default=50, ge=1)
    max_pairs_per_message: int = Field(default=3, ge=1)
    grant_ttl_hours: int = Field(default=24, ge=1)
    tenant_pause_minutes: int = Field(default=15, ge=1)


def guest_policy(tenant_config: Mapping[str, Any] | None) -> GuestPolicy:
    raw = ((tenant_config or {}).get("extra") or {}).get("identity_policy")
    if not isinstance(raw, Mapping):
        return GuestPolicy()
    try:
        return GuestPolicy.model_validate(raw)
    except ValidationError:
        logger.warning("identity_policy_invalid: se usan los límites por defecto")
        return GuestPolicy()


# ─── Datos aportados (parsers) ────────────────────────────────────────────────


@dataclass(frozen=True)
class Contact:
    """Email (casefold) o teléfono (E.164) aportado por el cliente."""

    kind: Literal["email", "phone"]
    value: str

    def claim(self, salt: str, region: str = DEFAULT_PHONE_REGION) -> ClaimHash | None:
        if self.kind == "email":
            return email_claim(salt, self.value)
        return phone_claim(salt, self.value, region)

    def masked(self) -> str:
        """Iniciales y dominio: `k***@h***.com`, o los dos últimos dígitos de un teléfono."""
        if self.kind == "phone":
            return "***" + self.value[-2:]
        local, _, domain = self.value.partition("@")
        host, _, tld = domain.rpartition(".")
        return f"{local[:1]}***@{host[:1]}***.{tld}"


@dataclass(frozen=True)
class ProvidedData:
    order_refs: tuple[str, ...] = ()
    contacts: tuple[Contact, ...] = ()


def normalize_order_ref(value: str) -> str:
    return value.strip().lstrip("#").strip()


def _compile_tenant_pattern(pattern: str | None) -> re.Pattern[str] | None:
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error:
        logger.warning("order_name_pattern_invalid: se usa la detección por defecto")
        return None


def _order_refs(text: str, tenant_pattern: re.Pattern[str] | None) -> list[str]:
    """Referencias de pedido del texto, en orden de aparición."""
    if tenant_pattern is not None:
        found = [(m.start(), m.group(0)) for m in tenant_pattern.finditer(text)]
    else:
        found = [(m.start(1), m.group(1)) for m in _HASH_ORDER_RE.finditer(text)]
        found += [(m.start(1), m.group(1)) for m in _KEYWORD_ORDER_RE.finditer(text)]
    return [ref for _, raw in sorted(found) if (ref := normalize_order_ref(raw))]


def _unique(items: Iterable[Any]) -> list[Any]:
    return list(dict.fromkeys(items))


def extract_provided(
    texts: Sequence[str],
    *,
    region: str = DEFAULT_PHONE_REGION,
    order_pattern: str | None = None,
    extra_emails: Sequence[str] = (),
) -> ProvidedData:
    """Pedidos, emails y teléfonos de los textos del cliente (el más reciente primero).

    Regex para emails, `phonenumbers` para teléfonos y, para pedidos, el patrón del tenant o
    (sin él) un número con `#` o junto a una palabra clave. Lo ambiguo no es un intento: lo
    recoge la skill de respaldo. Los dígitos de un email o teléfono no cuentan como pedido.
    """
    pattern = _compile_tenant_pattern(order_pattern)
    orders: list[str] = []
    contacts: list[Contact] = []
    for text in texts:
        spans: list[tuple[int, int]] = []
        for match in _EMAIL_RE.finditer(text):
            contacts.append(Contact("email", match.group(0).casefold()))
            spans.append(match.span())
        for phone_match in phonenumbers.PhoneNumberMatcher(text, region):
            e164 = phonenumbers.format_number(
                phone_match.number, phonenumbers.PhoneNumberFormat.E164
            )
            contacts.append(Contact("phone", e164))
            spans.append((phone_match.start, phone_match.end))
        remaining = list(text)
        for start, end in spans:
            remaining[start:end] = " " * (end - start)
        orders.extend(_order_refs("".join(remaining), pattern))
    contacts.extend(Contact("email", e.strip().casefold()) for e in extra_emails if e.strip())
    return ProvidedData(
        order_refs=tuple(_unique(orders)[:MAX_ITEMS_PER_KIND]),
        contacts=tuple(_unique(contacts)[:MAX_ITEMS_PER_KIND]),
    )


def provided_from_history(
    history: Sequence[Mapping[str, Any]] | None,
    *,
    region: str,
    order_pattern: str | None,
) -> ProvidedData:
    """Datos aportados en los mensajes del cliente de la conversación, el último primero.

    Suma el email que el intake guardó en `metadata.provided_contact` (el que tecleó el
    visitante de un chat): vale como dato aportado, nunca como remitente.
    """
    texts: list[str] = []
    emails: list[str] = []
    for message in reversed([m for m in history or [] if m.get("role") == "customer"]):
        texts.append(str(message.get("content") or ""))
        provided = (message.get("metadata") or {}).get(PROVIDED_CONTACT_KEY)
        if isinstance(provided, Mapping) and isinstance(provided.get("email"), str):
            emails.append(provided["email"])
    return extract_provided(texts, region=region, order_pattern=order_pattern, extra_emails=emails)


def build_provided_contact(email: str | None) -> dict[str, str] | None:
    """`messages.metadata.provided_contact` del intake: el email tecleado, sin verificar."""
    if email and email.strip():
        return {"email": email.strip()}
    return None


# ─── Pares y claves de intento ────────────────────────────────────────────────


@dataclass(frozen=True)
class Pair:
    order_ref: str
    contact: Contact


def attempt_key(salt: str, order_ref: str, contact_claim: ClaimHash) -> str:
    digest = hmac.new(
        salt.encode(), f"attempt:{order_ref.casefold()}:{contact_claim}".encode(), "sha256"
    )
    return digest.hexdigest()


def candidate_pairs(provided: ProvidedData) -> list[Pair]:
    return [Pair(o, c) for o in provided.order_refs for c in provided.contacts]


def missing_data(provided: ProvidedData) -> list[str]:
    """Qué falta para tocar pedidos: `order_number` y/o `contact`."""
    missing: list[str] = []
    if not provided.order_refs:
        missing.append("order_number")
    if not provided.contacts:
        missing.append("contact")
    return missing


# ─── Comprobación contra el pedido ────────────────────────────────────────────

GuestOutcome = Literal["granted", "order_not_found", "contact_mismatch"]


class OrderLookupError(Exception):
    """El adapter de commerce falló: no sabemos si el pedido existe."""


COMMERCE_UNAVAILABLE = "commerce_unavailable"


def commerce_unavailable_reason(error: str) -> str:
    """Motivo de escalado cuando la tienda no responde al resolver un pedido."""
    return f"{COMMERCE_UNAVAILABLE}: la tienda no respondió al consultar el pedido ({error})"


def _say(ctx: SkillContext, key: MessageKey, tenant_facts: Mapping[str, Any] | None) -> str:
    """Texto fijo de identidad en el idioma de la conversación."""
    return identity_message(
        key, tenant_facts, language=ctx.language, tenant_default=ctx.default_language
    )


def commerce_unavailable_refusal(error: str, ctx: SkillContext) -> SkillRefusal:
    """La tienda caída no es un fallo de identidad: texto fijo al cliente y escalado."""
    from apps.api.skills.base import SkillRefusal

    return SkillRefusal(
        COMMERCE_UNAVAILABLE,
        customer_message=_say(ctx, COMMERCE_UNAVAILABLE, ctx.tenant_facts),
        team_reason=commerce_unavailable_reason(error),
    )


@dataclass(frozen=True)
class GuestAttempt:
    outcome: GuestOutcome
    order: dict[str, Any] | None = None


def can_lookup_orders(ctx: SkillContext) -> bool:
    return ctx.commerce is not None


async def lookup_order(ctx: SkillContext, order_ref: str) -> dict[str, Any] | None:
    """El pedido de la referencia vía el adapter de commerce. Lanza `OrderLookupError`."""
    adapter = ctx.commerce
    if adapter is None:
        raise OrderLookupError("no_commerce_adapter")
    try:
        order: dict[str, Any] | None = await adapter.get_order_by_name(
            ctx.integration_ctx, order_ref
        )
        if not order:
            order = await adapter.get_order(ctx.integration_ctx, order_ref)
    except Exception as exc:
        raise OrderLookupError(type(exc).__name__) from exc
    return order or None


async def attempt_guest(ctx: SkillContext, order_ref: str, contact: Contact) -> GuestAttempt:
    """Resuelve el pedido y compara el contacto con sus claims, ambos hasheados.

    Pedido inexistente y contacto equivocado son casos distintos solo para el registro
    interno: al cliente y al LLM les llega el mismo texto fijo.
    """
    order = await lookup_order(ctx, order_ref)
    if order is None or order.get("id") is None:
        return GuestAttempt("order_not_found")
    claim = contact.claim(ctx.claim_salt, ctx.phone_region)
    if claim is None or claim not in ctx.order_claims(order):
        return GuestAttempt("contact_mismatch")
    return GuestAttempt("granted", order)


GUEST_FACTS_HEADER = (
    "Pedido que el cliente identificó en esta conversación con su número y el email o "
    "teléfono de la compra. Úsalo directamente:"
)


def guest_facts(existing: str | None, orders: Sequence[Mapping[str, Any]]) -> str:
    """`known_facts` con los pedidos ya proyectados que el cliente acaba de identificar."""
    lines = [
        f"- shopify.get_order_status: {json.dumps(order, ensure_ascii=False)}" for order in orders
    ]
    block = GUEST_FACTS_HEADER + "\n" + "\n".join(lines)
    return "\n\n".join(part for part in (existing, block) if part)


# ─── Una ronda de comprobaciones con límites ──────────────────────────────────

RoundStatus = Literal["idle", "granted", "failed", "locked", "paused", "unavailable"]


@dataclass(frozen=True)
class GuestRound:
    status: RoundStatus = "idle"
    grants: tuple[Grant, ...] = ()
    orders: tuple[dict[str, Any], ...] = ()
    # Texto fijo que cierra el turno sin pasar por el LLM; None si el turno sigue.
    reply: str | None = None
    # `unavailable`: error del adapter de commerce (sin pedido que comparar).
    error: str | None = None


async def load_guest_grants(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID, now: datetime | None = None
) -> tuple[Grant, ...]:
    rows = await list_active_guest_grants(conn, tenant_id, conversation_id, now or _now())
    return tuple(
        Grant("guest", "order_contact", order_id=r.order_id, valid_until=r.valid_until)
        for r in rows
    )


def _now() -> datetime:
    return datetime.now(UTC)


async def run_guest_checks(
    conn: asyncpg.Connection,
    ctx: SkillContext,
    pairs: Sequence[Pair],
    *,
    policy: GuestPolicy,
    tenant_facts: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> GuestRound:
    """Prueba los pares nuevos (como mucho `max_pairs_per_message`) y aplica los límites.

    Cada par se prueba una vez por conversación. Con la conversación bloqueada o el
    tenant en pausa no se consulta nada. Si ningún par concede y alguno falló, `reply`
    es el texto fijo. Un error del adapter no cuenta como fallo: el par no se registra.
    """
    moment = now or _now()
    tenant_id, conversation_id = UUID(ctx.tenant_id), UUID(ctx.conversation_id)
    salt = ctx.claim_salt

    keyed = {
        attempt_key(salt, p.order_ref, claim): p
        for p in pairs
        if (claim := p.contact.claim(salt, ctx.phone_region)) is not None
    }
    if not keyed:
        return GuestRound()
    seen = await list_attempt_keys(conn, tenant_id, conversation_id)
    fresh = [(k, p) for k, p in keyed.items() if k not in seen][: policy.max_pairs_per_message]
    if not fresh:
        return GuestRound()

    conversation_failures = await count_conversation_failures(conn, tenant_id, conversation_id)
    if conversation_failures >= policy.guest_max_failures_per_conversation:
        logger.warning(
            "guest_locked",
            extra={"tenant_id": ctx.tenant_id, "conversation_id": ctx.conversation_id},
        )
        return GuestRound("locked", reply=_say(ctx, "guest_locked", tenant_facts))
    tenant_failures, latest = await tenant_failure_stats(
        conn, tenant_id, moment - timedelta(hours=1)
    )
    pause = timedelta(minutes=policy.tenant_pause_minutes)
    if (
        tenant_failures >= policy.guest_max_failures_per_tenant_hour
        and latest is not None
        and latest > moment - pause
    ):
        logger.warning("guest_paused", extra={"tenant_id": ctx.tenant_id})
        return GuestRound("paused", reply=_say(ctx, "guest_paused", tenant_facts))

    grants: list[Grant] = []
    orders: list[dict[str, Any]] = []
    failed = False
    lookup_error: str | None = None
    for key, pair in fresh:
        if conversation_failures >= policy.guest_max_failures_per_conversation:
            break
        try:
            attempt = await attempt_guest(ctx, pair.order_ref, pair.contact)
        except OrderLookupError as exc:
            logger.error(
                "guest_lookup_failed",
                extra={"tenant_id": ctx.tenant_id, "error": str(exc)},
            )
            lookup_error = str(exc)
            continue
        claim = pair.contact.claim(salt, ctx.phone_region)
        order_id = int(attempt.order["id"]) if attempt.order else None
        valid_until = moment + timedelta(hours=policy.grant_ttl_hours) if attempt.order else None
        inserted = await insert_guest_check(
            conn,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            outcome=attempt.outcome,
            order_id=order_id,
            claim_hashes=[claim] if claim and attempt.order else [],
            attempt_key=key,
            contact_masked=pair.contact.masked(),
            valid_until=valid_until,
        )
        if not inserted:
            continue
        if attempt.order is not None:
            grants.append(
                Grant("guest", "order_contact", order_id=order_id, valid_until=valid_until)
            )
            orders.append(attempt.order)
            continue
        failed = True
        conversation_failures += 1
        tenant_failures += 1
        logger.info(
            "guest_check_failed",
            extra={"tenant_id": ctx.tenant_id, "outcome": attempt.outcome},
        )
        if tenant_failures == policy.guest_max_failures_per_tenant_hour:
            logger.error(
                "guest_tenant_paused",
                extra={"tenant_id": ctx.tenant_id, "failures": tenant_failures},
            )

    if grants:
        return GuestRound("granted", tuple(grants), tuple(orders))
    if lookup_error is not None:
        return GuestRound(
            "unavailable",
            reply=_say(ctx, COMMERCE_UNAVAILABLE, tenant_facts),
            error=lookup_error,
        )
    if failed:
        return GuestRound("failed", reply=_say(ctx, "guest_not_verified", tenant_facts))
    return GuestRound()
