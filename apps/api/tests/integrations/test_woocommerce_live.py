"""El adapter de WooCommerce y las skills L3 contra un WooCommerce real.

Opt-in: `AUYAN_TEST_WOOCOMMERCE_URL=http://127.0.0.1:9400` con el Playground de
`scripts/woocommerce_dev/` levantado y sembrado. Cada test crea sus propios pedidos por la
REST, así que se pueden repetir sobre la misma tienda.
"""

from __future__ import annotations

import random
import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.integrations.base import MutationNotApplied
from apps.api.integrations.commerce import CommerceActionError
from apps.api.integrations.woocommerce import WooCommerceError, WooCommerceRejected
from apps.api.services.approval_execution import Applied, NotApplied, execute_once
from apps.api.services.identity import email_claim, order_claims, phone_claim
from apps.api.skills.base import SkillContext, SkillRefusal
from apps.api.skills.shopify._order_guard import ActionOutcome
from apps.api.skills.shopify.cancel_order import CancelOrder, CancelOrderInput
from apps.api.skills.shopify.refund_partial import RefundPartial, RefundPartialInput
from apps.api.skills.shopify.update_shipping_address import (
    UpdateShippingAddress,
    UpdateShippingAddressInput,
)
from apps.api.tests.woocommerce_support import LIVE_URL, create_order, live, requires_woocommerce

pytestmark = requires_woocommerce

SALT = "sal-de-prueba"


def _email() -> str:
    return f"live-{uuid.uuid4().hex[:10]}@example.com"


def _phone() -> str:
    return f"6{random.randint(10_000_000, 99_999_999)}"


async def _card_order(**kw: Any) -> dict[str, Any]:
    return await create_order(
        email=kw.pop("email", _email()),
        phone=kw.pop("phone", "+34600111222"),
        payment_method="auyan_test",
        paid=True,
        **kw,
    )


async def _cod_order() -> dict[str, Any]:
    """Contra reembolso en `processing`: WooCommerce no le pone `date_paid`, no hay cobro."""
    return await create_order(
        email=_email(), phone="+34600111222", payment_method="cod", paid=False, status="processing"
    )


async def _transfer_order() -> dict[str, Any]:
    """Transferencia ya cobrada: pasarela sin reembolsos por API, devuelve la tienda."""
    return await create_order(
        email=_email(), phone="+34600111222", payment_method="bacs", paid=True
    )


async def _refunds(order_id: int) -> list[dict[str, Any]]:
    adapter, ctx, transport = live()
    client = adapter._client(ctx)
    refunds: list[dict[str, Any]] = await client.get(f"wc/v3/orders/{order_id}/refunds")
    return refunds


def _skill_ctx(key: str | None = None) -> SkillContext:
    adapter, ctx, _ = live()
    return SkillContext(
        tenant_id=str(ctx.tenant_id),
        conversation_id=str(uuid.uuid4()),
        integration_ctx=ctx,
        commerce=adapter,
        idempotency_key=key,
    )


# ─── Lecturas ─────────────────────────────────────────────────────────────────


async def test_reads_an_order_in_the_canonical_shape() -> None:
    email = _email()
    created = await _card_order(email=email, quantity=2)
    adapter, ctx, _ = live()

    order = await adapter.get_order_by_name(ctx, f"#{created['number']}")

    assert order is not None
    assert order["id"] == created["id"]
    assert order["name"] == f"#{created['number']}"
    assert order["email"] == email
    assert order["financial_status"] == "paid"
    assert order["fulfillment_status"] is None
    assert order["total_price"] == "59.80"
    assert order["total_price_set"]["presentment_money"] == {
        "amount": "59.80",
        "currency_code": "EUR",
    }
    assert [(i["title"], i["quantity"], i["price"]) for i in order["line_items"]] == [
        ("Camiseta Lino Azul", 2, "29.90")
    ]
    assert order["shipping_address"]["address1"] == "Calle Mayor 1"
    assert order["shipping_address"]["zip"] == "28013"
    assert order["shipping_address"]["province"] == "M"
    claims = order_claims(order, salt=SALT)
    assert email_claim(SALT, email.upper()) in claims
    assert phone_claim(SALT, "600 11 12 22", "ES") in claims


async def test_finds_orders_by_exact_email_only() -> None:
    email = _email()
    mine = await _card_order(email=email)
    await _card_order(email=f"otra-{email}")
    adapter, ctx, _ = live()

    found = await adapter.search_orders_by_email(ctx, email.upper())

    assert [o["id"] for o in found] == [mine["id"]]


async def test_finds_orders_by_phone_stored_without_prefix() -> None:
    national = _phone()
    mine = await _card_order(phone=national)
    adapter, ctx, _ = live()

    found = await adapter.search_orders_by_phone(ctx, f"+34{national}")

    assert [o["id"] for o in found] == [mine["id"]]


async def test_sequential_number_is_found_by_search_and_ambiguity_stops_the_action() -> None:
    visible = str(random.randint(700_000, 799_999))
    first = await _card_order(meta=[{"key": "_auyan_order_number", "value": visible}])
    second = await _card_order(meta=[{"key": "_auyan_order_number", "value": str(first["id"])}])
    adapter, ctx, _ = live()

    by_visible = await adapter.get_order_by_name(ctx, f"#{visible}")
    snapshot = await adapter.get_order_snapshot(ctx, int(visible))
    by_number = await adapter.get_order_by_name(ctx, str(first["id"]))

    assert by_visible is not None and by_visible["id"] == first["id"]
    assert by_visible["name"] == f"#{visible}"
    assert (snapshot.order_id, snapshot.name) == (first["id"], f"#{visible}")
    assert by_number is not None and by_number["id"] == second["id"]
    with pytest.raises(WooCommerceError, match="order_ref_ambiguous"):
        await adapter.get_order_snapshot(ctx, first["id"])


async def test_tracking_from_shipment_tracking_marks_the_order_shipped() -> None:
    created = await _card_order(
        meta=[
            {
                "key": "_wc_shipment_tracking_items",
                "value": [
                    {
                        "tracking_provider": "correos",
                        "tracking_number": "PQ4455",
                        "date_shipped": "1761400000",
                        "tracking_id": "t1",
                    }
                ],
            }
        ]
    )
    adapter, ctx, _ = live()

    order = await adapter.get_order_by_name(ctx, created["number"])
    snapshot = await adapter.get_order_snapshot(ctx, created["id"])

    assert order is not None
    assert order["fulfillment_status"] == "partial"
    assert order["fulfillments"][0]["tracking_number"] == "PQ4455"
    assert order["fulfillments"][0]["tracking_company"] == "correos"
    assert snapshot.shipped is True


async def test_snapshot_routes_card_to_automatic_and_transfer_to_manual() -> None:
    card = await _card_order()
    transfer = await _transfer_order()
    cod = await _cod_order()
    adapter, ctx, _ = live()

    card_snapshot = await adapter.get_order_snapshot(ctx, card["id"])
    transfer_snapshot = await adapter.get_order_snapshot(ctx, transfer["id"])
    cod_snapshot = await adapter.get_order_snapshot(ctx, cod["id"])
    cod_order = await adapter.get_order(ctx, str(cod["id"]))

    assert (card_snapshot.refund_route.mode, card_snapshot.refund_route.gateway) == (
        "automatic",
        "auyan_test",
    )
    assert (transfer_snapshot.refund_route.mode, transfer_snapshot.refund_route.gateway) == (
        "manual",
        "bacs",
    )
    assert card_snapshot.paid and transfer_snapshot.paid
    assert not card_snapshot.cancelled and not card_snapshot.shipped
    assert not cod_snapshot.paid
    assert cod_order["financial_status"] == "pending"
    with pytest.raises(WooCommerceError, match="order_has_no_refundable_payment"):
        await adapter.get_refundable_balance(ctx, cod["id"])


async def test_catalog_policies_currency_and_validation() -> None:
    adapter, ctx, _ = live()

    products = await adapter.search_products(ctx, "sudadera")
    policies = await adapter.get_policies(ctx)
    currency = await adapter.get_shop_currency(ctx)
    store = await adapter.validate(ctx)

    assert [(v["title"], v["available"]) for v in products[0]["variants"]] == [
        ("L", True),
        ("M", False),
        ("S", True),
    ]
    assert {p["handle"] for p in policies} >= {"refund_returns", "privacy-policy", "envios"}
    assert currency == "EUR"
    assert store["currency"] == "EUR"


# ─── Escrituras del adapter ───────────────────────────────────────────────────


async def test_automatic_refund_is_created_and_found_by_its_marker() -> None:
    card = await _card_order()
    adapter, ctx, _ = live()
    key = str(uuid.uuid4())

    issued = await adapter.refund_partial(
        ctx, card["id"], amount=Decimal("5.00"), note="talla", idempotency_key=key
    )
    found = await adapter.find_refund(ctx, card["id"], key)
    balance = await adapter.get_refundable_balance(ctx, card["id"])

    assert (issued.amount, issued.currency) == (Decimal("5.00"), "EUR")
    assert found is not None and found.refund_id == issued.refund_id
    assert found.transactions[0].manual_gateway is False
    assert balance.remaining == Decimal("24.90")
    assert (await _refunds(card["id"]))[0]["refunded_payment"] is True


async def test_refund_the_gateway_declines_is_not_applied_and_leaves_nothing() -> None:
    card = await _card_order()
    adapter, ctx, _ = live()
    key = str(uuid.uuid4())

    with pytest.raises(WooCommerceRejected, match="Declined by test gateway") as raised:
        await adapter.refund_partial(
            ctx, card["id"], amount=Decimal("5.00"), note="FAIL", idempotency_key=key
        )

    assert isinstance(raised.value, MutationNotApplied)
    assert await adapter.find_refund(ctx, card["id"], key) is None
    assert await _refunds(card["id"]) == []


async def test_manual_refund_is_only_recorded() -> None:
    transfer = await _transfer_order()
    adapter, ctx, _ = live()

    issued = await adapter.refund_partial(
        ctx, transfer["id"], amount=Decimal("2.00"), idempotency_key=str(uuid.uuid4())
    )

    refunds = await _refunds(transfer["id"])
    assert [(r["id"], r["refunded_payment"]) for r in refunds] == [(issued.refund_id, False)]


async def test_refund_above_the_balance_is_rejected_before_sending() -> None:
    card = await _card_order()
    adapter, ctx, transport = live()

    with pytest.raises(WooCommerceRejected, match="refund_amount_exceeds_refundable"):
        await adapter.refund_partial(
            ctx, card["id"], amount=Decimal("30.00"), idempotency_key=str(uuid.uuid4())
        )
    assert all(r.method == "GET" for r in transport.requests)


async def test_cancel_refunds_through_the_gateway() -> None:
    card = await _card_order()
    adapter, ctx, _ = live()

    order = await adapter.cancel_order(ctx, card["id"], refund=True, restock=True)
    snapshot = await adapter.get_order_snapshot(ctx, card["id"])

    assert snapshot.cancelled is True
    assert order["financial_status"] == "refunded"
    assert order["cancelled_at"] is not None
    assert [r["amount"] for r in await _refunds(card["id"])] == ["29.90"]


async def test_shipping_address_and_notes() -> None:
    card = await _card_order()
    adapter, ctx, _ = live()

    updated = await adapter.update_shipping_address(
        ctx,
        card["id"],
        address1="Calle Nueva 5",
        city="Sevilla",
        province="SE",
        zip_code="41001",
    )
    await adapter.add_order_note(ctx, card["id"], "Cliente avisado")
    await adapter.append_order_note(ctx, card["id"], "Liquidación A")
    await adapter.append_order_note(ctx, card["id"], "Liquidación A")
    notes = await adapter._client(ctx).get(f"wc/v3/orders/{card['id']}/notes")

    assert updated["shipping_address"]["address1"] == "Calle Nueva 5"
    assert updated["shipping_address"]["address2"] is None
    assert updated["shipping_address"]["country"] == "ES"
    texts = [n["note"] for n in notes if not n["customer_note"]]
    assert texts.count("Liquidación A") == 1
    assert "Cliente avisado" in texts


# ─── Skills L3 reales con el adapter de WooCommerce ───────────────────────────


async def test_cancel_order_skill_confirms_a_card_cancellation() -> None:
    card = await _card_order()
    skill = CancelOrder()
    ctx = _skill_ctx(str(uuid.uuid4()))

    prepared = await skill.prepare(ctx, {"order_id": int(card["number"])})
    result = await execute_once(
        skill, ctx, CancelOrderInput.model_validate(prepared), earlier_attempt=False
    )

    assert (prepared["refund_mode"], prepared["refund_gateway"]) == ("automatic", "auyan_test")
    assert isinstance(result, Applied)
    assert result.output["outcome"] == ActionOutcome.CONFIRMED
    assert result.output["cancelled"] is True
    reconciled = await skill.reconcile(ctx, CancelOrderInput(order_id=card["id"]))
    assert reconciled is not None and reconciled.outcome is ActionOutcome.CONFIRMED  # type: ignore[attr-defined]


async def test_cancel_order_skill_hands_a_transfer_refund_to_the_store() -> None:
    transfer = await _transfer_order()
    skill = CancelOrder()
    ctx = _skill_ctx(str(uuid.uuid4()))

    result = await execute_once(
        skill, ctx, CancelOrderInput(order_id=transfer["id"]), earlier_attempt=False
    )

    assert isinstance(result, Applied)
    assert result.output["outcome"] == ActionOutcome.REFUND_MANUAL
    assert result.output["cancelled"] is True
    assert (result.output["refund_mode"], result.output["refund_gateway"]) == ("manual", "bacs")
    assert [r["refunded_payment"] for r in await _refunds(transfer["id"])] == [False]


async def test_cancel_order_skill_on_unpaid_cod_cancels_without_refund() -> None:
    cod = await _cod_order()
    skill = CancelOrder()
    ctx = _skill_ctx(str(uuid.uuid4()))

    result = await execute_once(
        skill, ctx, CancelOrderInput(order_id=cod["id"]), earlier_attempt=False
    )

    assert isinstance(result, Applied)
    assert result.output["cancelled"] is True
    assert result.output["outcome"] == ActionOutcome.REFUND_MANUAL
    assert await _refunds(cod["id"]) == []


async def test_cancel_order_skill_refuses_a_completed_order_naming_woocommerce() -> None:
    done = await _card_order(status="completed")
    skill = CancelOrder()

    with pytest.raises(SkillRefusal) as refused:
        await skill.prepare(_skill_ctx(), {"order_id": done["id"]})

    assert refused.value.code == "order_shipped"
    assert "WooCommerce lo marca como enviado (estado fulfilled" in refused.value.team_reason


async def test_refund_partial_skill_confirms_and_never_refunds_twice() -> None:
    card = await _card_order()
    skill = RefundPartial()
    key = str(uuid.uuid4())
    ctx = _skill_ctx(key)

    prepared = await skill.prepare(ctx, {"order_id": card["id"], "amount": "7.50"})
    inputs = RefundPartialInput.model_validate(prepared)
    first = await execute_once(skill, ctx, inputs, earlier_attempt=False)
    again = await execute_once(skill, ctx, inputs, earlier_attempt=True)

    assert (prepared["currency"], prepared["refund_mode"]) == ("EUR", "automatic")
    assert isinstance(first, Applied) and isinstance(again, Applied)
    assert first.output["outcome"] == ActionOutcome.CONFIRMED
    assert first.output["amount"] == {"amount": "7.50", "currency": "EUR"}
    assert again.output["refund_id"] == first.output["refund_id"]
    assert len(await _refunds(card["id"])) == 1


async def test_refund_partial_skill_declined_by_the_gateway_is_not_applied() -> None:
    card = await _card_order()
    skill = RefundPartial()
    ctx = _skill_ctx(str(uuid.uuid4()))

    result = await execute_once(
        skill,
        ctx,
        RefundPartialInput(order_id=card["id"], amount=Decimal("3.00"), note="FAIL"),
        earlier_attempt=False,
    )

    assert isinstance(result, NotApplied)
    assert "Declined by test gateway" in result.error
    assert await _refunds(card["id"]) == []


async def test_refund_partial_skill_on_a_transfer_is_a_manual_refund() -> None:
    transfer = await _transfer_order()
    skill = RefundPartial()
    ctx = _skill_ctx(str(uuid.uuid4()))
    inputs = RefundPartialInput(order_id=transfer["id"], amount=Decimal("4.00"))

    result = await execute_once(skill, ctx, inputs, earlier_attempt=False)
    found = await skill.reconcile(ctx, inputs)

    assert isinstance(result, Applied)
    assert result.output["outcome"] == ActionOutcome.REFUND_MANUAL
    assert found is not None and found.refund_id == result.output["refund_id"]  # type: ignore[attr-defined]


async def test_refund_partial_skill_rejects_more_than_the_balance_in_prepare() -> None:
    card = await _card_order()

    with pytest.raises(CommerceActionError, match="refund_amount_exceeds_refundable"):
        await RefundPartial().prepare(_skill_ctx(), {"order_id": card["id"], "amount": "40.00"})


async def test_update_shipping_address_skill_confirms_the_saved_address() -> None:
    card = await _card_order()
    skill = UpdateShippingAddress()
    ctx = _skill_ctx(str(uuid.uuid4()))
    inputs = UpdateShippingAddressInput(
        order_id=card["id"],
        address1="Avenida de la Constitución 20",
        address2="3º B",
        city="Sevilla",
        province="Sevilla",
        zip_code="41004",
    )

    await skill.prepare(ctx, inputs.model_dump())
    result = await execute_once(skill, ctx, inputs, earlier_attempt=False)
    reconciled = await skill.reconcile(ctx, inputs)

    assert isinstance(result, Applied)
    assert result.output["outcome"] == ActionOutcome.CONFIRMED
    assert (result.output["new_address1"], result.output["new_zip"], result.output["new_country"]) == (
        "Avenida de la Constitución 20",
        "41004",
        "ES",
    )
    assert reconciled is not None


async def test_store_url_over_plain_http_is_refused_without_the_dev_flag() -> None:
    from apps.api.integrations.woocommerce import WooCommerceAdapter
    from apps.api.tests.woocommerce_support import integration

    assert LIVE_URL
    with pytest.raises(ValueError, match="woocommerce_store_url_must_be_public"):
        await WooCommerceAdapter(allow_http_loopback=False).get_shop_currency(
            integration(LIVE_URL)
        )
