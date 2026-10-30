"""El adapter de WooCommerce contra respuestas grabadas de un WooCommerce real.

Las respuestas salen del Playground de `scripts/woocommerce_dev/` con
`python -m apps.api.tests.woocommerce_record`. Cada test repite las llamadas que hizo la
grabación, en el mismo orden y con el mismo cuerpo: `ReplayTransport` falla si no.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.integrations.base import IntegrationContext, MutationNotApplied
from apps.api.integrations.commerce import (
    MarkedRefund,
    RefundableBalance,
    RefundRoute,
    SnapshotFulfillment,
    SnapshotTransaction,
)
from apps.api.integrations.woocommerce import (
    WooCommerceAdapter,
    WooCommerceError,
    WooCommerceRejected,
    financial_status,
    fulfillment_status,
    store_base_url,
)
from apps.api.services.identity import email_claim, order_claims, phone_claim
from apps.api.tests.woocommerce_support import ReplayTransport, recorded

SALT = "sal"


def _writes(transport: ReplayTransport) -> list[tuple[str, Any]]:
    return [(r.method, json.loads(r.read())) for r in transport.sent if r.method != "GET"]


def _refund(refund_id: int, *, manual: bool = False) -> SnapshotTransaction:
    return SnapshotTransaction(
        id=f"refund:{refund_id}",
        kind="refund",
        status="success",
        gateway="auyan_test",
        manual_gateway=manual,
        error_code=None,
    )


# ─── Pedidos en la forma canónica ─────────────────────────────────────────────


async def test_a_paid_card_order_in_the_canonical_shape() -> None:
    adapter, ctx, transport, refs = recorded("order_card")
    order_id = refs["order_id"]

    order = await adapter.get_order_by_name(ctx, f"#{refs['number']}")
    snapshot = await adapter.get_order_snapshot(ctx, order_id)
    balance = await adapter.get_refundable_balance(ctx, order_id)
    found = await adapter.find_refund(ctx, order_id, "rec-seed")

    assert order is not None
    assert {k: order[k] for k in ("id", "name", "email", "phone", "currency")} == {
        "id": order_id,
        "name": f"#{refs['number']}",
        "email": refs["email"],
        "phone": "+34600111222",
        "currency": "EUR",
    }
    assert (order["financial_status"], order["fulfillment_status"]) == (
        "partially_refunded",
        None,
    )
    assert order["total_price_set"]["presentment_money"] == {
        "amount": "59.80",
        "currency_code": "EUR",
    }
    item = order["line_items"][0]
    assert (item["title"], item["quantity"], item["price"], item["sku"]) == (
        "Camiseta Lino Azul",
        2,
        "29.90",
        "CAM-AZ",
    )
    assert item["price_set"]["presentment_money"] == {"amount": "29.90", "currency_code": "EUR"}
    assert order["shipping_address"] == {
        "first_name": "Ana",
        "last_name": "García",
        "company": None,
        "address1": "Calle Mayor 1",
        "address2": None,
        "city": "Madrid",
        "province": "M",
        "province_code": "M",
        "zip": "28013",
        "country": "ES",
        "country_code": "ES",
        "phone": "+34600111222",
    }
    assert order["fulfillments"] == []
    claims = order_claims(order, salt=SALT)
    assert email_claim(SALT, refs["email"].upper()) in claims
    assert phone_claim(SALT, "600111222", "ES") in claims

    refund_id = found.refund_id if found else None
    assert snapshot.paid and not snapshot.cancelled and not snapshot.shipped
    assert snapshot.refund_route == RefundRoute(mode="automatic", gateway="auyan_test")
    assert snapshot.transactions[1:] == (_refund(refund_id or 0),)
    assert balance == RefundableBalance(
        captured=Decimal("59.80"), refunded=Decimal("10.00"), currency="EUR"
    )
    assert found == MarkedRefund(
        refund_id=refund_id or 0,
        amount=Decimal("10.00"),
        currency="EUR",
        transactions=(_refund(refund_id or 0),),
    )
    assert transport.exhausted


async def test_unpaid_cash_on_delivery_has_no_payment_and_routes_manual() -> None:
    adapter, ctx, transport, refs = recorded("order_cod")

    order = await adapter.get_order_by_name(ctx, refs["number"])
    snapshot = await adapter.get_order_snapshot(ctx, refs["order_id"])

    assert order is not None and order["financial_status"] == "pending"
    assert snapshot.transactions == ()
    assert snapshot.refund_route == RefundRoute(mode="manual", gateway=None)
    assert transport.exhausted


async def test_a_paid_transfer_routes_the_refund_to_the_store() -> None:
    adapter, ctx, _, refs = recorded("order_transfer")

    snapshot = await adapter.get_order_snapshot(ctx, refs["order_id"])

    assert snapshot.paid
    assert snapshot.refund_route == RefundRoute(mode="manual", gateway="bacs")


async def test_a_completed_order_counts_as_shipped() -> None:
    adapter, ctx, _, refs = recorded("order_completed")

    order = await adapter.get_order_by_name(ctx, refs["number"])
    snapshot = await adapter.get_order_snapshot(ctx, refs["order_id"])

    assert order is not None
    assert (order["financial_status"], order["fulfillment_status"]) == ("paid", "fulfilled")
    assert [(f["status"], f["tracking_number"]) for f in order["fulfillments"]] == [
        ("success", None)
    ]
    assert order["fulfillments"][0]["created_at"] is not None
    assert snapshot.fulfillment_status == "fulfilled"
    assert snapshot.shipped


async def test_shipment_tracking_becomes_a_fulfillment_with_its_number() -> None:
    adapter, ctx, _, refs = recorded("order_tracking")

    order = await adapter.get_order_by_name(ctx, refs["number"])
    snapshot = await adapter.get_order_snapshot(ctx, refs["order_id"])

    assert order is not None
    assert order["fulfillment_status"] == "partial"
    fulfillment = order["fulfillments"][0]
    assert {
        k: fulfillment[k]
        for k in ("tracking_number", "tracking_company", "tracking_url", "created_at")
    } == {
        "tracking_number": "PQ4455",
        "tracking_company": "correos",
        "tracking_url": "https://correos.es/seguimiento?n=PQ4455",
        "created_at": "2025-10-25T13:46:40+00:00",
    }
    assert snapshot.fulfillments == (
        SnapshotFulfillment(status="success", tracking_numbers=("PQ4455",)),
    )
    assert snapshot.shipped


async def test_sequential_numbers_resolve_by_search_and_ambiguity_is_refused() -> None:
    adapter, ctx, transport, refs = recorded("order_sequential")

    order = await adapter.get_order_by_name(ctx, f"#{refs['visible']}")

    assert order is not None
    assert (order["id"], order["name"]) == (refs["first_id"], f"#{refs['visible']}")
    with pytest.raises(WooCommerceError, match="order_ref_ambiguous"):
        await adapter.get_order_snapshot(ctx, refs["first_id"])
    assert transport.exhausted


async def test_search_keeps_only_the_exact_email_and_phone() -> None:
    adapter, ctx, _, refs = recorded("search")

    by_email = await adapter.search_orders_by_email(ctx, refs["email"].upper())
    by_phone = await adapter.search_orders_by_phone(ctx, refs["phone"])

    assert [o["id"] for o in by_email] == [refs["mine"]]
    assert len(by_phone) == 2
    assert refs["mine"] in {o["id"] for o in by_phone}


# ─── Reembolsos ───────────────────────────────────────────────────────────────


async def test_an_automatic_refund_goes_through_the_gateway_with_the_marker() -> None:
    adapter, ctx, transport, refs = recorded("refund_ok")

    issued = await adapter.refund_partial(
        ctx, refs["order_id"], amount=Decimal("5.00"), note="talla", idempotency_key="rec-ok"
    )
    found = await adapter.find_refund(ctx, refs["order_id"], "rec-ok")

    assert (issued.amount, issued.currency) == (Decimal("5.00"), "EUR")
    assert found is not None and found.refund_id == issued.refund_id
    assert _writes(transport) == [
        ("POST", {"amount": "5.00", "reason": "talla [auyan:rec-ok]", "api_refund": True})
    ]


async def test_a_refund_the_gateway_declines_is_not_applied() -> None:
    adapter, ctx, transport, refs = recorded("refund_declined")

    with pytest.raises(WooCommerceRejected, match="Declined by test gateway") as raised:
        await adapter.refund_partial(
            ctx, refs["order_id"], amount=Decimal("5.00"), note="FAIL", idempotency_key="rec-fail"
        )

    assert isinstance(raised.value, MutationNotApplied)
    assert await adapter.find_refund(ctx, refs["order_id"], "rec-fail") is None
    assert transport.exhausted


async def test_a_manual_refund_is_recorded_without_the_gateway() -> None:
    adapter, ctx, transport, refs = recorded("refund_manual")

    issued = await adapter.refund_partial(
        ctx, refs["order_id"], amount=Decimal("2.00"), idempotency_key="rec-manual"
    )

    assert issued.amount == Decimal("2.00")
    assert _writes(transport) == [
        ("POST", {"amount": "2.00", "reason": "[auyan:rec-manual]", "api_refund": False})
    ]


# ─── Cancelar, dirección y notas ──────────────────────────────────────────────


async def test_cancel_refunds_everything_and_leaves_the_order_cancelled() -> None:
    adapter, ctx, transport, refs = recorded("cancel_card")

    order = await adapter.cancel_order(ctx, refs["order_id"], refund=True, restock=True)
    snapshot = await adapter.get_order_snapshot(ctx, refs["order_id"])

    assert order["financial_status"] == "refunded"
    assert snapshot.cancelled
    assert [t.kind for t in snapshot.transactions] == ["sale", "refund"]
    assert _writes(transport) == [
        ("PUT", {"status": "cancelled"}),
        (
            "POST",
            {"amount": "29.90", "reason": "Cancelación del pedido (customer)", "api_refund": True},
        ),
        # Un reembolso del total deja el pedido en `refunded`: se vuelve a cancelar.
        ("PUT", {"status": "cancelled"}),
    ]


async def test_shipping_address_sends_the_country_code() -> None:
    adapter, ctx, transport, refs = recorded("address")

    order = await adapter.update_shipping_address(
        ctx,
        refs["order_id"],
        address1="Avenida de la Constitución 20",
        address2="3º B",
        city="Sevilla",
        province="SE",
        zip_code="41004",
        country="Portugal",
    )

    assert {
        k: order["shipping_address"][k] for k in ("address1", "address2", "zip", "country")
    } == {
        "address1": "Avenida de la Constitución 20",
        "address2": "3º B",
        "zip": "41004",
        "country": "PT",
    }
    assert transport.exhausted


async def test_append_order_note_does_not_repeat_a_note() -> None:
    adapter, ctx, transport, refs = recorded("notes")

    await adapter.add_order_note(ctx, refs["order_id"], "Cliente avisado")
    await adapter.append_order_note(ctx, refs["order_id"], "Liquidación A")
    await adapter.append_order_note(ctx, refs["order_id"], "Liquidación A")

    assert _writes(transport) == [
        ("POST", {"note": "Cliente avisado", "customer_note": False}),
        ("POST", {"note": "Liquidación A", "customer_note": False}),
    ]


# ─── Catálogo, políticas y alta ───────────────────────────────────────────────


async def test_catalog_policies_currency_and_validation() -> None:
    adapter, ctx, transport, _ = recorded("catalog")

    sweatshirt = await adapter.search_products(ctx, "sudadera")
    tshirt = await adapter.search_products(ctx, "camiseta")
    currency = await adapter.get_shop_currency(ctx)
    policies = await adapter.get_policies(ctx)
    store = await adapter.validate(ctx)

    assert [(v["title"], v["price"], v["available"]) for v in sweatshirt[0]["variants"]] == [
        ("L", "45.00", True),
        ("M", "45.00", False),
        ("S", "45.00", True),
    ]
    assert [(v["id"], v["title"], v["available"]) for v in tshirt[0]["variants"]] == [
        (tshirt[0]["id"], "Camiseta Lino Azul", True)
    ]
    assert tshirt[0]["status"] == "active"
    assert currency == "EUR"
    assert {p["handle"] for p in policies} == {"refund_returns", "privacy-policy", "envios"}
    assert all(p["url"].startswith("https://tienda-prueba.test/") for p in policies)
    assert store == {
        "site_url": "https://tienda-prueba.test",
        "wc_version": "11.2.1",
        "currency": "EUR",
    }
    policy_request = next(r for r in transport.sent if "/wp/v2/" in r.url.path)
    assert "authorization" not in policy_request.headers


# ─── Reglas puras ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "date_paid", "refunds", "financial", "fulfillment"),
    [
        ("pending", None, [], "pending", None),
        ("on-hold", None, [], "pending", None),
        ("failed", None, [], "pending", None),
        ("processing", None, [], "pending", None),
        ("processing", "2026-10-30T10:00:00", [], "paid", None),
        ("processing", "2026-10-30T10:00:00", ["-5.00"], "partially_refunded", None),
        ("completed", "2026-10-30T10:00:00", [], "paid", "fulfilled"),
        ("cancelled", None, [], "voided", None),
        ("cancelled", "2026-10-30T10:00:00", ["-29.90"], "refunded", None),
        ("refunded", "2026-10-30T10:00:00", ["-29.90"], "refunded", None),
    ],
)
def test_status_table(
    status: str,
    date_paid: str | None,
    refunds: list[str],
    financial: str,
    fulfillment: str | None,
) -> None:
    order = {
        "status": status,
        "date_paid": date_paid,
        "total": "29.90",
        "refunds": [{"id": i, "total": t} for i, t in enumerate(refunds)],
    }

    assert (financial_status(order), fulfillment_status(order)) == (financial, fulfillment)


@pytest.mark.parametrize(
    ("url", "allow", "expected"),
    [
        ("https://tienda.es/", False, "https://tienda.es"),
        ("https://tienda.es/shop/", False, "https://tienda.es/shop"),
        ("http://127.0.0.1:9400", True, "http://127.0.0.1:9400"),
        ("http://localhost:9400", True, "http://localhost:9400"),
    ],
)
def test_store_url_accepted(url: str, allow: bool, expected: str) -> None:
    assert store_base_url(url, allow_http_loopback=allow) == expected


@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("http://tienda.es", "woocommerce_store_url_must_be_https"),
        ("http://127.0.0.1:9400", "woocommerce_store_url_must_be_public"),
        ("https://192.168.1.10", "woocommerce_store_url_must_be_public"),
        ("https://169.254.169.254", "woocommerce_store_url_must_be_public"),
        ("tienda.es", "woocommerce_store_url_invalid"),
    ],
)
def test_store_url_refused(url: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        store_base_url(url, allow_http_loopback=False)


# ─── Reintentos ───────────────────────────────────────────────────────────────

_CTX = IntegrationContext(
    tenant_id=UUID(int=4),
    credentials={"store_url": "https://tienda.es", "consumer_key": "ck", "consumer_secret": "cs"},
    provider="woocommerce",
)


def _adapter(*responses: httpx.Response) -> tuple[WooCommerceAdapter, list[httpx.Request]]:
    sent: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return queue.pop(0)

    return WooCommerceAdapter(transport=httpx.MockTransport(handler)), sent


@pytest.fixture
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr("apps.api.integrations.woocommerce.asyncio.sleep", instant)


@pytest.mark.usefixtures("_no_sleep")
async def test_a_read_retries_429_and_5xx_up_to_its_cap() -> None:
    ok = httpx.Response(200, json={"value": "EUR"})
    adapter, sent = _adapter(
        httpx.Response(429, headers={"retry-after": "1"}), httpx.Response(503), ok
    )

    assert await adapter.get_shop_currency(_CTX) == "EUR"
    assert len(sent) == 3

    adapter, sent = _adapter(*(httpx.Response(503) for _ in range(3)))
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.get_shop_currency(_CTX)
    assert len(sent) == 3


async def test_a_write_is_never_retried_and_a_5xx_stays_unknown() -> None:
    order = {"id": 7, "number": "7", "status": "processing", "currency": "EUR"}
    adapter, sent = _adapter(
        httpx.Response(200, json=order), httpx.Response(503, json={"code": "x", "message": "y"})
    )

    with pytest.raises(httpx.HTTPStatusError) as raised:
        await adapter.update_shipping_address(
            _CTX, 7, address1="Calle 1", city="Madrid", province="M", zip_code="28001"
        )

    assert not isinstance(raised.value, MutationNotApplied)
    assert [r.method for r in sent] == ["GET", "PUT"]


async def test_a_write_that_cannot_connect_is_not_applied() -> None:
    order = {"id": 7, "number": "7", "status": "processing", "currency": "EUR"}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=order)

    adapter = WooCommerceAdapter(transport=httpx.MockTransport(handler))

    with pytest.raises(WooCommerceRejected, match="ConnectError"):
        await adapter.add_order_note(_CTX, 7, "nota")
    assert calls == ["GET", "POST"]
