"""Catálogo de demo de una tienda WooCommerce sobre su Store API pública (ADR 0016 §7, #422).

`GET /wp-json/wc/store/v1/products` responde sin credenciales con precio, stock y atributos.
Devuelve la misma forma REST de producto que `DemoCatalogAdapter` (Shopify), de modo que
`get_product_info` no distingue de dónde viene.

Rutas, por orden: `/wp-json/wc/store/v1`, `/wp-json/wc/store` (WooCommerce antiguo) y las dos con
`/?rest_route=` cuando `/wp-json` está bloqueado. La primera que responde con una lista queda
fijada para el resto de la instancia.

Los precios llegan en unidades menores (`"4500"` con `currency_minor_unit: 2` es 45.00). La
cortesía con el sitio es la de `DemoCatalogAdapter`: AuyanBot siempre, 429 con `Retry-After` y tope.
"""

from __future__ import annotations

import html
import logging
from decimal import Decimal
from typing import Any

import httpx
from apps.api.integrations.demo_catalog import (
    BOT_USER_AGENT,
    MAX_RETRIES,
    MAX_RETRY_AFTER_SECONDS,
    DemoCatalogBase,
    DemoCatalogError,
    retry_after_seconds,
)
from apps.api.integrations.wordpress_rest import rest_url

logger = logging.getLogger(__name__)

_STORE_API_ROUTES: tuple[tuple[bool, str], ...] = (
    (True, "/wc/store/v1"),
    (True, "/wc/store"),
    (False, "/wc/store/v1"),
    (False, "/wc/store"),
)
_VARIATIONS_PER_PRODUCT = 100


def price_from_minor_units(prices: dict[str, Any], key: str = "price") -> str:
    """`prices.price="4500"` con `currency_minor_unit=2` → `"45.00"`."""
    minor = int(prices.get("currency_minor_unit", 2))
    raw = prices.get(key) or "0"
    return str(Decimal(raw).scaleb(-minor).quantize(Decimal(1).scaleb(-minor)))


def _clean(text: Any) -> str:
    return html.unescape(str(text or "")).strip()


def _slug_from_permalink(permalink: Any) -> str:
    """WooCommerce antiguo no trae `slug` en la Store API: sale de la URL del producto."""
    return str(permalink or "").rstrip("/").rsplit("/", 1)[-1]


def _extra_tags(node: dict[str, Any]) -> list[str]:
    tags = [_clean(t.get("name")) for t in node.get("tags") or []]
    for attr in node.get("attributes") or []:
        if attr.get("has_variations"):
            continue
        terms = ", ".join(_clean(t.get("name")) for t in attr.get("terms") or [])
        if terms:
            tags.append(f"{_clean(attr.get('name'))}: {terms}")
    return [t for t in tags if t]


def _variant_title(parent: dict[str, Any], variation: dict[str, Any]) -> str:
    for listed in parent.get("variations") or []:
        if listed.get("id") == variation.get("id"):
            values = [_clean(a.get("value")) for a in listed.get("attributes") or []]
            if any(values):
                return " / ".join(v for v in values if v)
    label = _clean(variation.get("variation"))
    return label.split(": ", 1)[-1] if label else "Default Title"


def product_from_store_api(
    node: dict[str, Any], variations: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Producto de la Store API → misma forma que `products.json` de la Admin REST de Shopify.

    `variations` son los productos tipo `variation` del padre; sin ellos un producto variable
    sale con las variantes que lista el padre y la disponibilidad del padre.
    """
    prices = node.get("prices") or {}
    if node.get("type") == "variable" and variations is not None:
        variants = [
            {
                "id": int(v["id"]),
                "title": _variant_title(node, v),
                "price": price_from_minor_units(v.get("prices") or prices),
                "available": bool(v.get("is_in_stock")),
            }
            for v in variations
        ]
    elif node.get("type") == "variable":
        variants = [
            {
                "id": int(v["id"]),
                "title": " / ".join(_clean(a.get("value")) for a in v.get("attributes") or [])
                or "Default Title",
                "price": price_from_minor_units(prices),
                "available": bool(node.get("is_in_stock")),
            }
            for v in node.get("variations") or []
        ]
    else:
        variants = [
            {
                "id": int(node["id"]),
                "title": "Default Title",
                "price": price_from_minor_units(prices),
                "available": bool(node.get("is_in_stock")),
            }
        ]
    categories = node.get("categories") or []
    return {
        "id": int(node["id"]),
        "title": _clean(node.get("name")),
        "handle": node.get("slug") or _slug_from_permalink(node.get("permalink")),
        "product_type": _clean(categories[0].get("name")) if categories else "",
        "status": "active",
        "body_html": node.get("description") or node.get("short_description") or "",
        "tags": _extra_tags(node),
        "online_store_url": node.get("permalink"),
        "variants": variants,
    }


class WooCommerceDemoCatalogAdapter(DemoCatalogBase):
    """Catálogo en vivo de una tienda WooCommerce pública. Sin credenciales, solo lectura."""

    _route: tuple[bool, str] | None = None
    _currency: str | None = None

    async def _get(
        self, client: httpx.AsyncClient, path: str, **params: str | int
    ) -> tuple[int, Any]:
        """`GET` de la Store API con respaldo de ruta. Devuelve (estado, JSON) de la primera
        ruta que responde algo distinto de "no existe"."""
        routes = (self._route,) if self._route else _STORE_API_ROUTES
        last = 404
        for pretty, prefix in routes:
            url = rest_url(f"https://{self.domain}", f"{prefix}{path}", pretty=pretty, **params)
            response = await self._send(client, url)
            last = response.status_code
            if last >= 500:
                raise DemoCatalogError(f"storefront_http_{last}")
            if last != 200:
                continue
            try:
                body = response.json()
            except ValueError:
                continue
            if not isinstance(body, list | dict):
                continue
            self._route = (pretty, prefix)
            return last, body
        return last, None

    async def _send(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        for attempt in range(MAX_RETRIES + 1):
            response = await client.get(url)
            if response.status_code != 429:
                return response
            wait = retry_after_seconds(response)
            if attempt == MAX_RETRIES or wait > MAX_RETRY_AFTER_SECONDS:
                raise DemoCatalogError(f"rate_limited: retry_after={wait}s")
            logger.info("demo_catalog_rate_limited", extra={"domain": self.domain, "wait": wait})
            await self._sleep(wait)
        raise AssertionError("unreachable")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            headers={"User-Agent": BOT_USER_AGENT},
            timeout=10,
            follow_redirects=True,
            max_redirects=3,
        )

    def _remember_currency(self, node: dict[str, Any]) -> None:
        code = (node.get("prices") or {}).get("currency_code")
        if code and self._currency is None:
            self._currency = str(code)

    async def _variations(
        self, client: httpx.AsyncClient, parent: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        status, body = await self._get(
            client,
            "/products",
            parent=parent["id"],
            type="variation",
            per_page=_VARIATIONS_PER_PRODUCT,
        )
        if status != 200 or not isinstance(body, list):
            return None
        mine = [v for v in body if v.get("parent") == parent["id"]]
        return mine or None

    async def _assemble(self, client: httpx.AsyncClient, node: dict[str, Any]) -> dict[str, Any]:
        self._remember_currency(node)
        variations = (
            await self._variations(client, node) if node.get("type") == "variable" else None
        )
        return product_from_store_api(node, variations)

    async def search_products(
        self, ctx: Any, query: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        async with self._client() as client:
            status, body = await self._get(client, "/products", search=query, per_page=limit)
            if not isinstance(body, list):
                raise DemoCatalogError(f"woocommerce_store_api_unavailable: http_{status}")
            return [await self._assemble(client, node) for node in body]

    async def get_product(self, ctx: Any, product_id: int) -> dict[str, Any] | None:
        """Detalle de un producto por id; el id de una variación devuelve su producto padre."""
        async with self._client() as client:
            status, node = await self._get(client, f"/products/{int(product_id)}")
            if status == 404 or not isinstance(node, dict):
                return None
            if node.get("parent"):
                status, node = await self._get(client, f"/products/{int(node['parent'])}")
                if not isinstance(node, dict):
                    return None
            return await self._assemble(client, node)

    async def get_shop_currency(self, ctx: Any) -> str:
        if self._currency is None:
            async with self._client() as client:
                status, body = await self._get(client, "/products", per_page=1)
                if not isinstance(body, list):
                    raise DemoCatalogError(f"woocommerce_store_api_unavailable: http_{status}")
                for node in body:
                    self._remember_currency(node)
        if self._currency is None:
            raise DemoCatalogError("woocommerce_currency_unavailable")
        return self._currency
