"""Nivel `guest` (ADR 0013 §3 y §4): parsers, comprobación contra el pedido y límites.

El código decide todo: el LLM no interviene. Las tablas de abajo son los casos del ADR.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.services import identity_guest
from apps.api.services.fixed_texts import fixed_text
from apps.api.services.identity import IdentityContext, email_claim
from apps.api.services.identity_guest import (
    Contact,
    GuestPolicy,
    Pair,
    attempt_guest,
    attempt_key,
    candidate_pairs,
    extract_provided,
    guest_policy,
    missing_data,
    provided_from_history,
    run_guest_checks,
)
from apps.api.services.identity_messages import identity_message
from apps.api.skills.base import SkillContext
from apps.api.tests.conftest import CONVERSATION_ID, TENANT_ID

SALT = "salt"
NOW = datetime.now(UTC).replace(microsecond=0)
ORDERS = {
    "1001": {"id": 9001, "name": "#1001", "email": "ana@tienda.com", "phone": "+34600111222"},
    "1002": {"id": 9002, "name": "#1002", "email": "luis@tienda.com", "phone": "+34600333444"},
}


def _adapter(*, fail: bool = False) -> Any:
    adapter = MagicMock()

    async def by_name(_ctx: Any, ref: str) -> dict[str, Any] | None:
        if fail:
            raise RuntimeError("shopify down")
        return ORDERS.get(str(ref).lstrip("#"))

    adapter.get_order_by_name = by_name
    adapter.get_order = AsyncMock(return_value=None)
    return adapter


def _ctx(adapter: Any | None = None) -> SkillContext:
    return SkillContext(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        integration_ctx=IntegrationContext(tenant_id=TENANT_ID, credentials={}, config={}),
        commerce_mock=adapter or _adapter(),
        claim_salt=SALT,
    )


class Store:
    """`identity_checks` en memoria con las mismas reglas que las queries."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = "apps.api.services.identity_guest"
        monkeypatch.setattr(f"{module}.list_attempt_keys", self.list_attempt_keys)
        monkeypatch.setattr(f"{module}.count_conversation_failures", self.count_failures)
        monkeypatch.setattr(f"{module}.tenant_failure_stats", self.tenant_stats)
        monkeypatch.setattr(f"{module}.insert_guest_check", self.insert)

    async def list_attempt_keys(self, *_: Any) -> set[str]:
        return {r["attempt_key"] for r in self.rows}

    async def count_failures(self, *_: Any) -> int:
        return sum(r["outcome"] != "granted" for r in self.rows)

    async def tenant_stats(self, _conn: Any, _tenant: Any, since: datetime) -> Any:
        times = [r["at"] for r in self.rows if r["outcome"] != "granted" and r["at"] > since]
        return len(times), max(times, default=None)

    async def insert(self, _conn: Any, **kwargs: Any) -> bool:
        if kwargs["attempt_key"] in {r["attempt_key"] for r in self.rows}:
            return False
        self.rows.append({**kwargs, "at": NOW})
        return True


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Store:
    s = Store()
    s.install(monkeypatch)
    return s


def _pair(order: str, email: str) -> Pair:
    return Pair(order, Contact("email", email))


# ─── Parsers ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "orders", "contacts"),
    [
        (
            "Mi pedido es el #1001 y mi email Ana@Tienda.com",
            ["1001"],
            [("email", "ana@tienda.com")],
        ),
        ("pedido 1001, tel 600 111 222", ["1001"], [("phone", "+34600111222")]),
        ("+34 600 111 222 y pedido #20345", ["20345"], [("phone", "+34600111222")]),
        ("ana1234@tienda.com", [], [("email", "ana1234@tienda.com")]),
        ("hola, ¿dónde está mi pedido?", [], []),
        ("Nací en 1985, mi email es ana@tienda.com", [], [("email", "ana@tienda.com")]),
        ("código postal 28001, ana@tienda.com", [], [("email", "ana@tienda.com")]),
        ("talla 4000 ana@tienda.com", [], [("email", "ana@tienda.com")]),
        ("pedido 1431 ana@tienda.com", ["1431"], [("email", "ana@tienda.com")]),
        ("Nº 20345, ana@tienda.com", ["20345"], [("email", "ana@tienda.com")]),
        ("mi compra número 5521 fue ayer", ["5521"], []),
        ("pedido 1001 y el #1002", ["1001", "1002"], []),
        ("pedido 12", [], []),
    ],
)
def test_extract_provided_table(
    text: str, orders: list[str], contacts: list[tuple[str, str]]
) -> None:
    provided = extract_provided([text], region="ES")
    assert list(provided.order_refs) == orders
    assert [(c.kind, c.value) for c in provided.contacts] == contacts


def test_phone_digits_are_not_taken_as_an_order_number() -> None:
    provided = extract_provided(["llámame al 600111222"], region="ES")
    assert provided.order_refs == ()


def test_tenant_order_pattern_and_bad_pattern_fallback() -> None:
    custom = extract_provided(["pedido AB-77"], order_pattern=r"AB-\d+")
    assert custom.order_refs == ("AB-77",)
    bare = extract_provided(["AB-77 y 2024"], order_pattern=r"AB-\d+")
    assert bare.order_refs == ("AB-77",)
    broken = extract_provided(["pedido 1001", "año 2024"], order_pattern="(")
    assert broken.order_refs == ("1001",)


def test_history_pairs_data_across_messages_and_counts_chat_email() -> None:
    history = [
        {"role": "customer", "content": "¿Dónde está el pedido 1001?", "metadata": {}},
        {"role": "agent_ai", "content": "Dame tu email 9999", "metadata": {}},
        {
            "role": "customer",
            "content": "es el de ana",
            "metadata": {"provided_contact": {"email": "Ana@tienda.com"}},
        },
    ]
    provided = provided_from_history(history, region="ES", order_pattern=None)
    assert provided.order_refs == ("1001",)
    assert [c.value for c in provided.contacts] == ["ana@tienda.com"]
    assert [(p.order_ref, p.contact.value) for p in candidate_pairs(provided)] == [
        ("1001", "ana@tienda.com")
    ]


def test_missing_data_names_what_is_absent() -> None:
    both = extract_provided(["hola"])
    assert missing_data(both) == ["order_number", "contact"]
    assert missing_data(extract_provided(["pedido 1001"])) == ["contact"]
    assert missing_data(extract_provided(["ana@tienda.com"])) == ["order_number"]
    assert missing_data(extract_provided(["pedido 1001 ana@tienda.com"])) == []


def test_contacts_are_masked() -> None:
    assert Contact("email", "kenny@hotmail.com").masked() == "k***@h***.com"
    assert Contact("phone", "+34600111222").masked() == "***22"


# ─── attempt_guest ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("order", "contact", "outcome"),
    [
        ("1001", Contact("email", "ana@tienda.com"), "granted"),
        ("#1001", Contact("email", "ANA@tienda.com".casefold()), "granted"),
        ("1001", Contact("phone", "+34600111222"), "granted"),
        ("1001", Contact("email", "luis@tienda.com"), "contact_mismatch"),
        ("1002", Contact("phone", "+34600111222"), "contact_mismatch"),
        ("9999", Contact("email", "ana@tienda.com"), "order_not_found"),
    ],
)
async def test_attempt_guest_table(order: str, contact: Contact, outcome: str) -> None:
    attempt = await attempt_guest(_ctx(), order, contact)
    assert attempt.outcome == outcome
    assert (attempt.order is not None) == (outcome == "granted")


async def test_a_correct_email_with_someone_elses_order_grants_nothing(store: Store) -> None:
    result = await run_guest_checks(
        AsyncMock(), _ctx(), [_pair("1002", "ana@tienda.com")], policy=GuestPolicy(), now=NOW
    )
    assert result.status == "failed"
    assert result.grants == ()
    assert result.orders == ()


async def test_a_match_grants_guest_on_that_order_only(store: Store) -> None:
    result = await run_guest_checks(
        AsyncMock(), _ctx(), [_pair("1001", "ana@tienda.com")], policy=GuestPolicy(), now=NOW
    )
    assert result.status == "granted"
    grant = result.grants[0]
    assert (grant.level, grant.method, grant.order_id) == ("guest", "order_contact", 9001)
    assert grant.valid_until == NOW + timedelta(hours=24)
    assert grant.claims == frozenset()
    identity = IdentityContext(result.grants)
    ana = ORDERS["1001"]
    other = ORDERS["1002"]
    ctx = _ctx()
    assert identity.level_for(ctx.order_claims(ana), ana["id"]) == "guest"
    assert identity.level_for(ctx.order_claims(other), other["id"]) is None


async def test_stored_rows_never_hold_contacts_in_clear(store: Store) -> None:
    await run_guest_checks(
        AsyncMock(), _ctx(), [_pair("1001", "ana@tienda.com")], policy=GuestPolicy(), now=NOW
    )
    assert "ana@tienda.com" not in str(store.rows)
    assert store.rows[0]["claim_hashes"] == [email_claim(SALT, "ana@tienda.com")]


# ─── Respuesta idéntica y límites ─────────────────────────────────────────────


async def test_unknown_order_and_wrong_contact_get_the_same_reply(store: Store) -> None:
    unknown = await run_guest_checks(
        AsyncMock(), _ctx(), [_pair("9999", "ana@tienda.com")], policy=GuestPolicy(), now=NOW
    )
    wrong = await run_guest_checks(
        AsyncMock(), _ctx(), [_pair("1002", "ana@tienda.com")], policy=GuestPolicy(), now=NOW
    )
    assert unknown.reply == wrong.reply == fixed_text("guest_not_verified", "es")
    assert [r["outcome"] for r in store.rows] == ["order_not_found", "contact_mismatch"]
    assert "existe" not in unknown.reply


async def test_each_pair_is_tried_once_per_conversation(store: Store) -> None:
    first = await run_guest_checks(
        AsyncMock(), _ctx(), [_pair("1002", "ana@tienda.com")], policy=GuestPolicy(), now=NOW
    )
    again = await run_guest_checks(
        AsyncMock(), _ctx(), [_pair("1002", "ana@tienda.com")], policy=GuestPolicy(), now=NOW
    )
    assert first.status == "failed"
    assert again.status == "idle"
    assert len(store.rows) == 1


async def test_at_most_three_pairs_per_message(store: Store) -> None:
    pairs = [_pair(str(9000 + i), "ana@tienda.com") for i in range(6)]
    await run_guest_checks(AsyncMock(), _ctx(), pairs, policy=GuestPolicy(), now=NOW)
    assert len(store.rows) == 3


async def test_the_fifth_failure_locks_the_conversation(store: Store) -> None:
    policy = GuestPolicy()
    for i in range(5):
        result = await run_guest_checks(
            AsyncMock(), _ctx(), [_pair(str(8000 + i), "ana@tienda.com")], policy=policy, now=NOW
        )
        assert result.reply == fixed_text("guest_not_verified", "es")
    locked = await run_guest_checks(
        AsyncMock(), _ctx(), [_pair("1001", "ana@tienda.com")], policy=policy, now=NOW
    )
    assert locked.status == "locked"
    assert locked.reply == fixed_text("guest_locked", "es")
    assert locked.grants == ()
    assert len(store.rows) == 5


async def test_failures_in_one_message_stop_at_the_limit(store: Store) -> None:
    policy = GuestPolicy(guest_max_failures_per_conversation=2)
    pairs = [_pair(str(8000 + i), "ana@tienda.com") for i in range(3)]
    await run_guest_checks(AsyncMock(), _ctx(), pairs, policy=policy, now=NOW)
    assert len(store.rows) == 2


async def test_tenant_failures_pause_guest_then_resume(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    policy = GuestPolicy(guest_max_failures_per_tenant_hour=3, max_pairs_per_message=3)
    pairs = [_pair(str(8000 + i), "ana@tienda.com") for i in range(3)]
    with caplog.at_level("ERROR"):
        await run_guest_checks(AsyncMock(), _ctx(), pairs, policy=policy, now=NOW)
    assert any(r.message == "guest_tenant_paused" for r in caplog.records)

    other_conversation = _ctx()
    paused = await run_guest_checks(
        AsyncMock(),
        other_conversation,
        [_pair("1001", "ana@tienda.com")],
        policy=policy,
        now=NOW + timedelta(minutes=5),
    )
    assert paused.status == "paused"
    assert paused.reply == fixed_text("guest_paused", "es")

    for row in store.rows:
        row["attempt_key"] += "-old"
    resumed = await run_guest_checks(
        AsyncMock(),
        other_conversation,
        [_pair("1001", "ana@tienda.com")],
        policy=policy,
        now=NOW + timedelta(minutes=16),
    )
    assert resumed.status == "granted"


async def test_an_adapter_error_is_not_recorded_and_reports_the_store_down(
    store: Store,
) -> None:
    result = await run_guest_checks(
        AsyncMock(),
        _ctx(_adapter(fail=True)),
        [_pair("1001", "ana@tienda.com")],
        policy=GuestPolicy(),
        now=NOW,
    )
    assert result.status == "unavailable"
    assert result.reply == fixed_text("commerce_unavailable", "es")
    assert result.error
    assert store.rows == []


def test_attempt_key_ignores_case_and_leading_hash_is_normalized_by_callers() -> None:
    claim = email_claim(SALT, "ana@tienda.com")
    assert claim is not None
    assert attempt_key(SALT, "AB-1", claim) == attempt_key(SALT, "ab-1", claim)
    assert attempt_key("other", "AB-1", claim) != attempt_key(SALT, "AB-1", claim)


# ─── Política y textos ────────────────────────────────────────────────────────


def test_policy_defaults_overrides_and_invalid_values() -> None:
    assert guest_policy(None).guest_max_failures_per_conversation == 5
    custom = guest_policy({"extra": {"identity_policy": {"guest_max_failures_per_tenant_hour": 9}}})
    assert custom.guest_max_failures_per_tenant_hour == 9
    broken = guest_policy(
        {"extra": {"identity_policy": {"guest_max_failures_per_conversation": 0}}}
    )
    assert broken.guest_max_failures_per_conversation == 5


def test_tenant_can_override_the_fixed_texts() -> None:
    facts = {"identity_messages": {"guest_not_verified": "  Revisa los datos, porfa.  "}}
    assert identity_message("guest_not_verified", facts) == "Revisa los datos, porfa."
    assert identity_message("guest_locked", facts) == fixed_text("guest_locked", "es")
    assert identity_message("guest_paused", {"identity_messages": {"guest_paused": " "}}) == (
        fixed_text("guest_paused", "es")
    )


def test_provided_contact_only_for_a_typed_email() -> None:
    assert identity_guest.build_provided_contact(" Ana@x.com ") == {"email": "Ana@x.com"}
    assert identity_guest.build_provided_contact("  ") is None
    assert identity_guest.build_provided_contact(None) is None


async def test_guest_texts_follow_the_conversation_language(store: Store) -> None:
    from dataclasses import replace

    ctx = replace(_ctx(), language="en")
    failed = await run_guest_checks(
        AsyncMock(), ctx, [_pair("9999", "otra@tienda.com")], policy=GuestPolicy(), now=NOW
    )
    assert failed.reply == fixed_text("guest_not_verified", "en")
    assert failed.reply.startswith("I couldn't verify")

    down = await run_guest_checks(
        AsyncMock(),
        replace(_ctx(_adapter(fail=True)), language="ca"),
        [_pair("1001", "ana@tienda.com")],
        policy=GuestPolicy(),
        now=NOW,
    )
    assert down.reply == fixed_text("commerce_unavailable", "ca")


def test_commerce_unavailable_refusal_uses_language_and_tenant_overrides() -> None:
    from dataclasses import replace

    from apps.api.services.identity_guest import commerce_unavailable_refusal

    refusal = commerce_unavailable_refusal("timeout", replace(_ctx(), language="en"))
    assert refusal.customer_message == fixed_text("commerce_unavailable", "en")

    facts = {"identity_messages": {"commerce_unavailable": {"en": "Store is down, one sec."}}}
    custom = replace(_ctx(), language="en", tenant_facts=facts)
    assert commerce_unavailable_refusal("timeout", custom).customer_message == (
        "Store is down, one sec."
    )
    french = replace(_ctx(), language="fr", tenant_facts=facts)
    assert commerce_unavailable_refusal("timeout", french).customer_message == (
        fixed_text("commerce_unavailable", "fr")
    )


def test_plain_string_override_follows_the_tenant_default_language() -> None:
    facts = {"identity_messages": {"guest_locked": "Locked, sorry."}}
    assert identity_message("guest_locked", facts, language="en", tenant_default="en") == (
        "Locked, sorry."
    )
    assert identity_message("guest_locked", facts, language="en", tenant_default="es") == (
        fixed_text("guest_locked", "en")
    )
