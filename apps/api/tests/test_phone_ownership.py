"""Identidad por teléfono (Sprint 2, PR-6) con el gate único de ADR 0013: email O teléfono."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.agents.nodes import execute_skill
from apps.api.agents.nodes.execute_skill import build_skill_context
from apps.api.services.identity import (
    default_phone_region,
    order_phones,
    phones_match,
)
from apps.api.skills.shopify.cancel_order import CancelOrder
from apps.api.skills.shopify.get_order_status import GetOrderStatus
from apps.api.tests.conftest import TENANT_ID
from apps.api.tests.identity_support import identity_state, patch_commerce

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


def test_default_region_resolution() -> None:
    assert default_phone_region(None, None) == "ES"
    assert default_phone_region({"extra": {"phone_default_region": "ve"}}, None) == "VE"
    assert default_phone_region({"extra": {}}, {"country_code": "MX"}) == "MX"


# ─── Gate de identidad (execute_skill) ────────────────────────────────────────


def _adapter(order: dict[str, Any] | None = ORDER) -> Any:
    adapter = MagicMock()
    adapter.get_order_by_name = AsyncMock(return_value=order)
    adapter.get_order = AsyncMock(return_value=None)
    return adapter


async def _gate(skill: Any, state: dict[str, Any], raw_input: dict[str, Any]) -> Any:
    return await execute_skill._identity_gate(state, skill, raw_input)


async def test_whatsapp_owner_by_phone_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_commerce(monkeypatch, _adapter())
    state = identity_state(phone="+34600111222", channel="whatsapp")
    assert await _gate(CancelOrder, state, {"order_id": 1432}) is None


async def test_whatsapp_phone_of_the_address_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_commerce(monkeypatch, _adapter())
    state = identity_state(phone="+34611223344", channel="whatsapp")
    assert await _gate(CancelOrder, state, {"order_id": 1432}) is None


async def test_whatsapp_other_phone_offers_a_person(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    patch_commerce(monkeypatch, _adapter())
    state = identity_state(phone="+34699999999", channel="whatsapp")
    blocked = await _gate(CancelOrder, state, {"order_id": 1432})
    assert blocked is not None
    verdict, error = blocked
    assert verdict == "identity_required" and "persona del equipo" in error
    record = next(r for r in caplog.records if r.message == "identity_gate_blocked")
    assert record.verdict == "identity_required"
    assert "699999999" not in str(record.__dict__)


async def test_whatsapp_bsuid_only_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_commerce(monkeypatch, _adapter())
    blocked = await _gate(CancelOrder, identity_state(channel="whatsapp"), {"order_id": 1432})
    assert blocked == ("identity_required", execute_skill._IDENTITY_REQUIRED_ERROR_MESSAGING)


async def test_email_channel_keeps_email_message(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_commerce(monkeypatch, _adapter())
    state = identity_state(email="otro@x.com")
    blocked = await _gate(CancelOrder, state, {"order_id": 1432})
    assert blocked == ("identity_required", execute_skill._IDENTITY_REQUIRED_ERROR)


def test_skill_context_carries_phone_channel_and_region() -> None:
    state = identity_state(phone="+34600111222", channel="whatsapp")
    state["tenant_config"] = {"extra": {"phone_default_region": "PT"}}
    ctx = build_skill_context(state)  # type: ignore[arg-type]
    assert (ctx.customer_phone, ctx.channel, ctx.phone_region) == (
        "+34600111222",
        "whatsapp",
        "PT",
    )
    assert str(TENANT_ID) == ctx.tenant_id


# ─── get_order_status: el pedido solo para su dueño (email o teléfono) ───────


async def test_order_status_is_open_to_the_phone_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_commerce(monkeypatch, _adapter())
    state = identity_state(phone="+34611223344", channel="whatsapp")
    assert await _gate(GetOrderStatus, state, {"order_identifier": "1432"}) is None


async def test_order_status_is_closed_to_other_phone(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_commerce(monkeypatch, _adapter())
    state = identity_state(phone="+34699999999", channel="whatsapp")
    blocked = await _gate(GetOrderStatus, state, {"order_identifier": "1432"})
    assert blocked is not None and blocked[0] == "identity_required"


async def test_a_missing_order_answers_like_a_foreign_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Los números de pedido son correlativos: existir o no no se distingue."""
    state = identity_state(phone="+34699999999", channel="whatsapp")
    patch_commerce(monkeypatch, _adapter(ORDER))
    foreign = await _gate(GetOrderStatus, state, {"order_identifier": "1432"})
    patch_commerce(monkeypatch, _adapter(None))
    missing = await _gate(GetOrderStatus, state, {"order_identifier": "9999"})
    assert foreign == missing and foreign is not None
