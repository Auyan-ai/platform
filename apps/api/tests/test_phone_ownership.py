"""Ownership L3 por teléfono (Sprint 2, PR-6): email O teléfono del pedido, fail-closed."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.agents.nodes import execute_skill
from apps.api.agents.nodes.execute_skill import build_skill_context
from apps.api.integrations.base import IntegrationContext
from apps.api.services.identity import (
    check_order_ownership,
    default_phone_region,
    order_phones,
    phones_match,
)
from apps.api.skills.base import SkillContext
from apps.api.tests.conftest import TENANT_ID

MODULE = "apps.api.agents.nodes.execute_skill"
ORDER: dict[str, Any] = {
    "id": 7404799197464,
    "name": "#1432",
    "email": "carmen@example.com",
    "phone": None,
    "customer": {"email": "carmen@example.com", "phone": "+34 600 11 12 22"},
    "shipping_address": {"phone": "611 22 33 44", "country_code": "ES"},
    "billing_address": {"phone": None, "country_code": "ES"},
}


# ─── Normalización y comparación ──────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["+34 600 11 12 22", "600111222", "0034600111222", "34600111222"])
def test_same_phone_in_different_formats(raw: str) -> None:
    assert phones_match(raw, "+34600111222")


def test_order_phones_collects_all_sources() -> None:
    assert order_phones(ORDER) == {"+34600111222", "+34611223344"}


def test_address_phone_uses_the_address_country() -> None:
    order = {"shipping_address": {"phone": "412 1234567", "country_code": "VE"}}
    assert order_phones(order) == {"+584121234567"}


# ─── check_order_ownership ────────────────────────────────────────────────────


def test_phone_match_passes() -> None:
    check = check_order_ownership(ORDER, customer_email=None, customer_phone="+34611223344")
    assert (check.owner, check.reason) == (True, "phone_match")


def test_other_phone_is_blocked() -> None:
    check = check_order_ownership(ORDER, customer_email=None, customer_phone="+34699999999")
    assert (check.owner, check.reason) == (False, "phone_mismatch")


def test_only_bsuid_is_blocked() -> None:
    check = check_order_ownership(ORDER, customer_email=None, customer_phone=None)
    assert (check.owner, check.reason) == (False, "no_customer_identity")


def test_order_without_phone_is_blocked() -> None:
    order = {"email": "carmen@example.com"}
    check = check_order_ownership(order, customer_email=None, customer_phone="+34600111222")
    assert (check.owner, check.reason) == (False, "order_without_phone")


def test_email_match_passes_even_if_phone_differs() -> None:
    check = check_order_ownership(
        ORDER, customer_email="CARMEN@example.com", customer_phone="+34699999999"
    )
    assert (check.owner, check.reason) == (True, "email_match")


def test_unresolved_order_is_blocked() -> None:
    check = check_order_ownership(None, customer_email="x@y.z", customer_phone="+34600111222")
    assert (check.owner, check.reason) == (False, "order_unresolved")


def test_invalid_phone_is_not_a_match() -> None:
    check = check_order_ownership(ORDER, customer_email=None, customer_phone="123")
    assert check.owner is False


def test_default_region_resolution() -> None:
    assert default_phone_region(None, None) == "ES"
    assert default_phone_region({"extra": {"phone_default_region": "ve"}}, None) == "VE"
    assert default_phone_region({"extra": {}}, {"country_code": "MX"}) == "MX"


# ─── Gate L3 (execute_skill) ──────────────────────────────────────────────────


def _patch_commerce(monkeypatch: pytest.MonkeyPatch, order: dict | None, channel: str) -> None:
    adapter = MagicMock()
    adapter.get_order_by_name = AsyncMock(return_value=order)
    adapter.get_order = AsyncMock(return_value=None)

    def _ctx(state: Any) -> SkillContext:
        customer = state.get("end_customer") or {}
        return SkillContext(
            tenant_id=str(TENANT_ID),
            conversation_id="c",
            integration_ctx=IntegrationContext(tenant_id=TENANT_ID, credentials={}, config={}),
            commerce_mock=adapter,
            customer_email=customer.get("email"),
            customer_phone=customer.get("phone"),
            channel=channel,
        )

    monkeypatch.setattr(f"{MODULE}.build_skill_context", _ctx)


def _state(email: str | None, phone: str | None) -> dict[str, Any]:
    return {
        "tenant_id": str(TENANT_ID),
        "conversation_id": "22222222-2222-2222-2222-222222222222",
        "end_customer": {"email": email, "phone": phone},
    }


async def test_whatsapp_owner_by_phone_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_commerce(monkeypatch, ORDER, "whatsapp")
    err = await execute_skill._l3_ownership_error(_state(None, "+34600111222"), {"order_id": 1432})
    assert err is None


async def test_whatsapp_other_phone_offers_a_person(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_commerce(monkeypatch, ORDER, "whatsapp")
    err = await execute_skill._l3_ownership_error(_state(None, "+34699999999"), {"order_id": 1432})
    assert err is not None and "persona del equipo" in err
    record = next(r for r in caplog.records if r.message == "l3_ownership_blocked")
    assert record.reason == "phone_mismatch"
    assert "699999999" not in str(record.__dict__)


async def test_whatsapp_bsuid_only_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_commerce(monkeypatch, ORDER, "whatsapp")
    err = await execute_skill._l3_ownership_error(_state(None, None), {"order_id": 1432})
    assert err == execute_skill._OWNERSHIP_ERROR_MESSAGING


async def test_email_channel_keeps_email_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_commerce(monkeypatch, ORDER, "zendesk")
    err = await execute_skill._l3_ownership_error(_state("otro@x.com", None), {"order_id": 1432})
    assert err == execute_skill._OWNERSHIP_ERROR


def test_skill_context_carries_phone_channel_and_region() -> None:
    ctx = build_skill_context(
        {
            "tenant_id": str(TENANT_ID),
            "conversation_id": "c",
            "channel": "whatsapp",
            "end_customer": {"email": None, "phone": "+34600111222"},
            "tenant_config": {"extra": {"phone_default_region": "PT"}},
        }
    )
    assert (ctx.customer_phone, ctx.channel, ctx.phone_region) == (
        "+34600111222",
        "whatsapp",
        "PT",
    )


# ─── get_order_status: la dirección solo al dueño (email o teléfono) ─────────


async def _order_status(customer_email: str | None, customer_phone: str | None) -> Any:
    from apps.api.skills.shopify.get_order_status import GetOrderStatus

    order = {**ORDER, "shipping_address": {**ORDER["shipping_address"], "address1": "Calle 1"}}
    adapter = MagicMock()
    adapter.get_order_by_name = AsyncMock(return_value=order)
    adapter.get_order = AsyncMock(return_value=order)
    ctx = SkillContext(
        tenant_id=str(TENANT_ID),
        conversation_id="c",
        integration_ctx=IntegrationContext(tenant_id=TENANT_ID, credentials={}, config={}),
        commerce_mock=adapter,
        customer_email=customer_email,
        customer_phone=customer_phone,
    )
    skill = GetOrderStatus()
    return await skill.execute(ctx, skill.input_schema(order_identifier="1432"))


async def test_order_status_reveals_address_to_phone_owner() -> None:
    out = await _order_status(None, "+34611223344")
    assert out.found is True and out.shipping_address is not None


async def test_order_status_hides_the_order_from_other_phone() -> None:
    out = await _order_status(None, "+34699999999")
    assert (out.found, out.order_id, out.shipping_address) == (False, None, None)
