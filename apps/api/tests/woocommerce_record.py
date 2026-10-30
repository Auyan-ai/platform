"""Graba las respuestas de un WooCommerce real para `tests/integrations/test_woocommerce_adapter.py`.

Uso, con el Playground de `scripts/woocommerce_dev/` levantado y sembrado:

    AUYAN_TEST_WOOCOMMERCE_URL=http://127.0.0.1:9400 \\
        python -m apps.api.tests.woocommerce_record

Cada escenario crea sus pedidos por la REST (eso no se graba) y luego llama al adapter: se
graba cada petición del adapter y su respuesta, con el host reescrito a
`https://tienda-prueba.test`. Los tests reproducen las mismas llamadas en el mismo orden.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import httpx
from apps.api.integrations.woocommerce import WooCommerceAdapter
from apps.api.tests.woocommerce_support import (
    DEV_KEY,
    DEV_SECRET,
    FIXTURES,
    LIVE_URL,
    PlaygroundTransport,
    create_order,
    live,
)

Refs = dict[str, Any]
Scenario = Callable[[WooCommerceAdapter, Any], Awaitable[Refs]]
_TRACKING = {
    "key": "_wc_shipment_tracking_items",
    "value": [
        {
            "tracking_provider": "correos",
            "custom_tracking_provider": "",
            "custom_tracking_link": "https://correos.es/seguimiento?n=PQ4455",
            "tracking_number": "PQ4455",
            "date_shipped": "1761400000",
            "tracking_id": "t1",
        }
    ],
}


def _email() -> str:
    return f"rec-{uuid.uuid4().hex[:8]}@example.com"


async def _card(**kw: Any) -> dict[str, Any]:
    return await create_order(
        email=kw.pop("email", _email()),
        phone=kw.pop("phone", "+34600111222"),
        payment_method="auyan_test",
        paid=True,
        **kw,
    )


async def _seed_refund(order_id: int, reason: str) -> None:
    assert LIVE_URL
    async with httpx.AsyncClient(
        transport=PlaygroundTransport(), auth=(DEV_KEY, DEV_SECRET), timeout=60
    ) as http:
        response = await http.post(
            f"{LIVE_URL}/wp-json/wc/v3/orders/{order_id}/refunds",
            json={"amount": "10.00", "reason": reason, "api_refund": True},
        )
        response.raise_for_status()


async def order_card(adapter: WooCommerceAdapter, ctx: Any) -> Refs:
    order = await _card(quantity=2)
    await _seed_refund(order["id"], "talla [auyan:rec-seed]")
    return {"order_id": order["id"], "number": order["number"], "email": order["billing"]["email"]}


async def order_card_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    await adapter.get_order_by_name(ctx, f"#{refs['number']}")
    await adapter.get_order_snapshot(ctx, refs["order_id"])
    await adapter.get_refundable_balance(ctx, refs["order_id"])
    await adapter.find_refund(ctx, refs["order_id"], "rec-seed")


async def order_transfer(adapter: WooCommerceAdapter, ctx: Any) -> Refs:
    order = await create_order(email=_email(), phone="612333444", payment_method="bacs", paid=True)
    return {"order_id": order["id"]}


async def order_transfer_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    await adapter.get_order_snapshot(ctx, refs["order_id"])


async def order_cod(adapter: WooCommerceAdapter, ctx: Any) -> Refs:
    order = await create_order(
        email=_email(), phone="612333444", payment_method="cod", paid=False, status="processing"
    )
    return {"order_id": order["id"], "number": order["number"]}


async def order_cod_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    await adapter.get_order_by_name(ctx, refs["number"])
    await adapter.get_order_snapshot(ctx, refs["order_id"])


async def order_completed(adapter: WooCommerceAdapter, ctx: Any) -> Refs:
    order = await _card(status="completed")
    return {"order_id": order["id"], "number": order["number"]}


order_completed_calls = order_cod_calls


async def order_tracking(adapter: WooCommerceAdapter, ctx: Any) -> Refs:
    order = await _card(meta=[_TRACKING])
    return {"order_id": order["id"], "number": order["number"]}


order_tracking_calls = order_cod_calls


async def order_sequential(adapter: WooCommerceAdapter, ctx: Any) -> Refs:
    visible = str(700_000 + secrets.randbelow(100_000))
    first = await _card(meta=[{"key": "_auyan_order_number", "value": visible}])
    second = await _card(meta=[{"key": "_auyan_order_number", "value": str(first["id"])}])
    return {"first_id": first["id"], "second_id": second["id"], "visible": visible}


async def order_sequential_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    await adapter.get_order_by_name(ctx, f"#{refs['visible']}")
    try:
        await adapter.get_order_snapshot(ctx, refs["first_id"])
    except Exception as exc:  # el rechazo por ambigüedad es lo que se graba
        print(f"  order_sequential: {exc}")


async def search(adapter: WooCommerceAdapter, ctx: Any) -> Refs:
    email = _email()
    national = str(600_000_000 + secrets.randbelow(99_999_999))
    mine = await _card(email=email, phone=national)
    await _card(email=f"otra-{email}", phone=f"+34{national}")
    return {"email": email, "phone": f"+34{national}", "mine": mine["id"]}


async def search_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    await adapter.search_orders_by_email(ctx, refs["email"].upper())
    await adapter.search_orders_by_phone(ctx, refs["phone"])


async def refund_ok(adapter: WooCommerceAdapter, ctx: Any) -> Refs:
    return {"order_id": (await _card())["id"]}


async def refund_ok_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    await adapter.refund_partial(
        ctx, refs["order_id"], amount=Decimal("5.00"), note="talla", idempotency_key="rec-ok"
    )
    await adapter.find_refund(ctx, refs["order_id"], "rec-ok")


refund_declined = refund_ok


async def refund_declined_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    try:
        await adapter.refund_partial(
            ctx, refs["order_id"], amount=Decimal("5.00"), note="FAIL", idempotency_key="rec-fail"
        )
    except Exception as exc:
        print(f"  refund_declined: {exc}")
    await adapter.find_refund(ctx, refs["order_id"], "rec-fail")


refund_manual = order_transfer


async def refund_manual_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    await adapter.refund_partial(
        ctx, refs["order_id"], amount=Decimal("2.00"), idempotency_key="rec-manual"
    )


cancel_card = refund_ok


async def cancel_card_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    await adapter.cancel_order(ctx, refs["order_id"], refund=True, restock=True)
    await adapter.get_order_snapshot(ctx, refs["order_id"])


address = refund_ok


async def address_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    await adapter.update_shipping_address(
        ctx,
        refs["order_id"],
        address1="Avenida de la Constitución 20",
        address2="3º B",
        city="Sevilla",
        province="SE",
        zip_code="41004",
        country="Portugal",
    )


notes = refund_ok


async def notes_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    await adapter.add_order_note(ctx, refs["order_id"], "Cliente avisado")
    await adapter.append_order_note(ctx, refs["order_id"], "Liquidación A")
    await adapter.append_order_note(ctx, refs["order_id"], "Liquidación A")


async def catalog(adapter: WooCommerceAdapter, ctx: Any) -> Refs:
    return {}


async def catalog_calls(adapter: WooCommerceAdapter, ctx: Any, refs: Refs) -> None:
    await adapter.search_products(ctx, "sudadera")
    await adapter.search_products(ctx, "camiseta")
    await adapter.get_shop_currency(ctx)
    await adapter.get_policies(ctx)
    await adapter.validate(ctx)


SCENARIOS = (
    "order_card",
    "order_transfer",
    "order_cod",
    "order_completed",
    "order_tracking",
    "order_sequential",
    "search",
    "refund_ok",
    "refund_declined",
    "refund_manual",
    "cancel_card",
    "address",
    "notes",
    "catalog",
)


async def record(name: str) -> None:
    adapter, ctx, transport = live()
    refs = await globals()[name](adapter, ctx)
    transport.recorded.clear()
    await globals()[f"{name}_calls"](adapter, ctx, refs)
    assert LIVE_URL
    body = {"refs": refs, "exchanges": transport.dump(LIVE_URL)}
    (FIXTURES / f"{name}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n")
    print(f"{name}: {len(body['exchanges'])} respuestas")


async def main() -> None:
    if not LIVE_URL:
        raise SystemExit("AUYAN_TEST_WOOCOMMERCE_URL no configurada")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name in SCENARIOS:
        await record(name)


if __name__ == "__main__":
    asyncio.run(main())
