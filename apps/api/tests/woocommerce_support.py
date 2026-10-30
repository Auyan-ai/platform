"""WooCommerce real para tests: el Playground de `scripts/woocommerce_dev/` en vivo, o sus
respuestas grabadas en `tests/fixtures/woocommerce/` para los tests que corren siempre.

Los tests en vivo se activan con `AUYAN_TEST_WOOCOMMERCE_URL` (p. ej.
`http://127.0.0.1:9400`). Las claves por defecto son las que siembra `seed.php`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import httpx
import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.woocommerce import WooCommerceAdapter

LIVE_URL = os.environ.get("AUYAN_TEST_WOOCOMMERCE_URL")
requires_woocommerce = pytest.mark.skipif(
    not LIVE_URL, reason="AUYAN_TEST_WOOCOMMERCE_URL no configurada"
)
DEV_KEY = os.environ.get(
    "AUYAN_TEST_WOOCOMMERCE_KEY", "ck_auyandevlocal000000000000000000000000000"
)
DEV_SECRET = os.environ.get(
    "AUYAN_TEST_WOOCOMMERCE_SECRET", "cs_auyandevlocal000000000000000000000000000"
)

FIXTURES = Path(__file__).parent / "fixtures" / "woocommerce"
# Host de las respuestas grabadas: el del Playground se reescribe a este.
RECORDED_STORE = "https://tienda-prueba.test"
TENANT = UUID("44444444-4444-4444-4444-444444444444")

# Playground redirige (302) toda petición sin la cookie de su auto-login.
_PLAYGROUND_COOKIE = "playground_auto_login_already_happened=1"
_KEEP_HEADERS = ("content-type", "retry-after")


def integration(store_url: str) -> IntegrationContext:
    return IntegrationContext(
        tenant_id=TENANT,
        credentials={
            "store_url": store_url,
            "consumer_key": DEV_KEY,
            "consumer_secret": DEV_SECRET,
        },
        provider="woocommerce",
    )


def _key(method: str, url: httpx.URL | str) -> str:
    parts = urlsplit(str(url))
    query = "&".join(f"{k}={v}" for k, v in sorted(parse_qsl(parts.query)))
    return f"{method} {parts.path}?{query}" if query else f"{method} {parts.path}"


class PlaygroundTransport(httpx.AsyncBaseTransport):
    """Transporte real con la cookie del Playground. Con `record`, guarda cada respuesta
    con el host de la tienda reescrito a `RECORDED_STORE`."""

    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self.recorded: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request.headers["Cookie"] = _PLAYGROUND_COOKIE
        self.requests.append(request)
        response = await self._inner.handle_async_request(request)
        body = await response.aread()
        self.recorded.append(
            {
                "request": _key(request.method, request.url),
                "body": json.loads(request.content) if request.content else None,
                "status": response.status_code,
                "headers": {k: v for k, v in response.headers.items() if k in _KEEP_HEADERS},
                "response": body.decode(),
            }
        )
        return httpx.Response(
            response.status_code, headers=response.headers, content=body, request=request
        )

    def dump(self, store_url: str) -> list[dict[str, Any]]:
        host = re.escape(urlsplit(store_url).netloc)
        pattern = re.compile(rf"https?(:\\?/\\?/){host}")
        return [
            {
                **entry,
                "response": json.loads(
                    pattern.sub(lambda m: f"https{m.group(1)}tienda-prueba.test", entry["response"])
                ),
            }
            for entry in self.recorded
        ]


class ReplayTransport(httpx.AsyncBaseTransport):
    """Reproduce en orden las respuestas grabadas de un escenario. Falla si la petición
    no es la que se grabó en ese punto."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = list(entries)
        self.sent: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        if not self._entries:
            raise AssertionError(f"petición no grabada: {_key(request.method, request.url)}")
        entry = self._entries.pop(0)
        got = _key(request.method, request.url)
        if got != entry["request"]:
            raise AssertionError(f"se esperaba {entry['request']}, llegó {got}")
        sent = json.loads(request.content) if request.content else None
        if sent != entry["body"]:
            raise AssertionError(f"{got}: se esperaba el cuerpo {entry['body']}, llegó {sent}")
        return httpx.Response(
            entry["status"],
            headers=entry["headers"],
            content=json.dumps(entry["response"]).encode(),
            request=request,
        )

    @property
    def exhausted(self) -> bool:
        return not self._entries


def recorded(scenario: str) -> tuple[WooCommerceAdapter, IntegrationContext, ReplayTransport]:
    """Adapter que habla con las respuestas grabadas de `scenario`."""
    entries = json.loads((FIXTURES / f"{scenario}.json").read_text())
    transport = ReplayTransport(entries)
    return WooCommerceAdapter(transport=transport), integration(RECORDED_STORE), transport


def live() -> tuple[WooCommerceAdapter, IntegrationContext, PlaygroundTransport]:
    assert LIVE_URL
    transport = PlaygroundTransport()
    adapter = WooCommerceAdapter(transport=transport, allow_http_loopback=True)
    return adapter, integration(LIVE_URL), transport


async def create_order(
    *,
    email: str,
    phone: str,
    payment_method: str,
    paid: bool,
    status: str | None = None,
    quantity: int = 1,
    meta: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Crea un pedido real por la REST para que cada test tenga el suyo."""
    assert LIVE_URL
    async with httpx.AsyncClient(
        transport=PlaygroundTransport(), auth=(DEV_KEY, DEV_SECRET), timeout=60
    ) as http:
        products = (
            await http.get(f"{LIVE_URL}/wp-json/wc/v3/products", params={"sku": "CAM-AZ"})
        ).json()
        address = {
            "first_name": "Ana",
            "last_name": "García",
            "address_1": "Calle Mayor 1",
            "city": "Madrid",
            "state": "M",
            "postcode": "28013",
            "country": "ES",
            "phone": phone,
        }
        body: dict[str, Any] = {
            "payment_method": payment_method,
            "set_paid": paid,
            "billing": {**address, "email": email},
            "shipping": address,
            "line_items": [{"product_id": products[0]["id"], "quantity": quantity}],
            "meta_data": meta or [],
        }
        response = await http.post(f"{LIVE_URL}/wp-json/wc/v3/orders", json=body)
        response.raise_for_status()
        order: dict[str, Any] = response.json()
        if status:
            response = await http.put(
                f"{LIVE_URL}/wp-json/wc/v3/orders/{order['id']}", json={"status": status}
            )
            response.raise_for_status()
            order = response.json()
        return order
