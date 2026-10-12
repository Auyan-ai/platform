"""Modelo de identidad (ADR 0013 §2): claims hasheados, grants y nivel sobre un pedido."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.services.identity import (
    Grant,
    IdentityContext,
    IdentityEvidence,
    identity_note,
    level_at_least,
    order_claims,
    sender_identity,
)

SALT = "salt-a"
ORDER: dict[str, Any] = {
    "id": 1432,
    "email": "Carmen@Example.com",
    "customer": {"id": 99, "email": "carmen@example.com", "phone": "+34 600 11 12 22"},
    "shipping_address": {"phone": "611 22 33 44", "country_code": "ES"},
}


def _level(evidence: IdentityEvidence, order: dict[str, Any] | None = ORDER) -> Any:
    identity = sender_identity(evidence, salt=SALT)
    claims = order_claims(order or {}, salt=SALT)
    return identity.level_for(claims, (order or {}).get("id"))


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (IdentityEvidence(email="carmen@example.com"), "verified"),
        (IdentityEvidence(email="  CARMEN@EXAMPLE.COM "), "verified"),
        (IdentityEvidence(phone="+34600111222"), "verified"),
        (IdentityEvidence(phone="+34611223344"), "verified"),
        (IdentityEvidence(email="otra@example.com"), None),
        (IdentityEvidence(phone="+34699999999"), None),
        (IdentityEvidence(email="otra@example.com", phone="+34600111222"), "verified"),
        (IdentityEvidence(), None),
        (IdentityEvidence(phone="123"), None),
    ],
)
def test_level_by_contact(evidence: IdentityEvidence, expected: str | None) -> None:
    assert _level(evidence) == expected


def test_order_without_contact_gives_nothing() -> None:
    assert _level(IdentityEvidence(email="carmen@example.com"), {"id": 5}) is None


def test_order_phone_only_matches_by_phone() -> None:
    order = {"id": 5, "email": "carmen@example.com"}
    assert _level(IdentityEvidence(phone="+34600111222"), order) is None


def test_the_hash_depends_on_the_tenant_salt() -> None:
    a = order_claims(ORDER, salt="salt-a")
    b = order_claims(ORDER, salt="salt-b")
    assert a and a.isdisjoint(b)


def test_a_claim_is_not_the_plain_contact() -> None:
    claims = order_claims(ORDER, salt=SALT)
    assert all("carmen" not in c and "600" not in c for c in claims)


def test_a_guest_grant_only_covers_its_order() -> None:
    identity = IdentityContext((Grant("guest", "order_contact", order_id=1432),))
    claims = order_claims(ORDER, salt=SALT)
    assert identity.level_for(claims, 1432) == "guest"
    assert identity.level_for(claims, 1433) is None
    assert identity.level_for(claims) is None


def test_an_expired_grant_does_not_count() -> None:
    past = datetime.now(UTC) - timedelta(minutes=1)
    claims = order_claims(ORDER, salt=SALT)
    expired = IdentityContext((Grant("verified", "otp", claims=claims, valid_until=past),))
    assert expired.level_for(claims) is None
    assert not expired.has_grant()
    fresh = Grant("verified", "otp", claims=claims, valid_until=datetime.now(UTC) + timedelta(1))
    assert IdentityContext((fresh,)).level_for(claims) == "verified"


def test_state_roundtrip_keeps_grants_and_only_hashes() -> None:
    identity = sender_identity(
        IdentityEvidence(email="carmen@example.com", phone="+34600111222"), salt=SALT
    )
    state = identity.to_state()
    assert IdentityContext.from_state(state) == identity
    assert "carmen" not in str(state) and "600111222" not in str(state)
    assert IdentityContext.from_state(None) == IdentityContext()


def test_summary_has_level_and_methods_but_no_claims() -> None:
    identity = sender_identity(IdentityEvidence(email="carmen@example.com"), salt=SALT)
    assert identity.summary() == {"level": "verified", "methods": ["sender_email"]}
    assert IdentityContext().summary() == {"level": None, "methods": []}


def test_level_order() -> None:
    assert level_at_least("verified", "guest")
    assert level_at_least("guest", "guest")
    assert not level_at_least("guest", "verified")
    assert not level_at_least(None, "guest")
    assert level_at_least(None, None)


def test_note_for_the_llm_never_carries_contacts() -> None:
    verified = sender_identity(IdentityEvidence(email="carmen@example.com"), salt=SALT)
    note = identity_note(verified)
    assert note.startswith("Identidad: el cliente escribe desde su propio email;")
    assert "carmen" not in note
    assert "todavía no puedes consultar ni modificar pedidos" in identity_note(IdentityContext())
