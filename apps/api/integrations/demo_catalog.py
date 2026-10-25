"""Adaptador de comercio de solo lectura para las demos (ADR 0015).

Una demo no tiene credenciales de la tienda: lee su catálogo público por la Storefront API
(`POST https://<dominio>/api/<versión>/graphql.json`), que en una tienda Shopify pública
responde sin token. Devuelve las mismas formas que `ShopifyAdapter` (productos con forma REST,
moneda ISO), de modo que `get_product_info` no distingue de dónde vienen.

Cortesía con el sitio: el User-Agent nos identifica siempre como AuyanBot, un 429 se reintenta
solo respetando `Retry-After` y con tope, y nada se envía sin ese encabezado.

Todo lo que no es catálogo (pedidos, reembolsos, devoluciones, políticas) lanza
`DemoCatalogUnavailable`: las skills lo tratan como tienda no disponible y el agente escala
con razón explícita.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BOT_USER_AGENT = "AuyanBot/0.1 (+https://auyan.es/bot)"
STOREFRONT_API_VERSION = "2025-07"
MAX_RETRIES = 2
MAX_RETRY_AFTER_SECONDS = 10.0
_DEFAULT_RETRY_AFTER_SECONDS = 1.0
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")

_PRODUCT_FIELDS = """
id title handle productType description tags onlineStoreUrl
variants(first: 50) { nodes { id title availableForSale price { amount currencyCode } } }
"""
_SEARCH_PRODUCTS = (
    "query($q: String!, $n: Int!) { products(first: $n, query: $q) { nodes {"
    + _PRODUCT_FIELDS
    + "} } }"
)
_SHOP_CURRENCY = "{ shop { paymentSettings { currencyCode } } }"


class DemoCatalogError(RuntimeError):
    """Fallo al leer el catálogo público de la demo."""


class DemoCatalogUnavailable(DemoCatalogError):
    """La demo no ofrece esta operación: solo lee el catálogo público.

    Los pedidos y cualquier escritura necesitan la tienda real del cliente.
    """


def normalize_domain(store: str) -> str:
    """Dominio público sin esquema ni ruta; rechaza lo que no sea un hostname."""
    host = re.sub(r"^https?://", "", store.strip().lower()).split("/")[0]
    if not _DOMAIN_RE.match(host):
        raise ValueError(f"invalid_store_domain: {store!r}")
    return host


def _numeric_id(gid: str) -> int:
    """`gid://shopify/Product/123` → 123, el id numérico que usa la forma REST."""
    return int(gid.rsplit("/", 1)[-1])


def product_from_storefront(node: dict[str, Any]) -> dict[str, Any]:
    """Producto de la Storefront API → misma forma que `products.json` de la Admin REST."""
    variants = [
        {
            "id": _numeric_id(v["id"]),
            "title": v.get("title", ""),
            "price": str((v.get("price") or {}).get("amount", "0.00")),
            "available": bool(v.get("availableForSale")),
        }
        for v in (node.get("variants") or {}).get("nodes", [])
    ]
    return {
        "id": _numeric_id(node["id"]),
        "title": node.get("title", ""),
        "handle": node.get("handle", ""),
        "product_type": node.get("productType", ""),
        "status": "active",
        "body_html": node.get("description") or "",
        "tags": list(node.get("tags") or []),
        "online_store_url": node.get("onlineStoreUrl"),
        "variants": variants,
    }


def retry_after_seconds(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After")
    try:
        return max(float(raw), 0.0) if raw is not None else _DEFAULT_RETRY_AFTER_SECONDS
    except ValueError:
        return _DEFAULT_RETRY_AFTER_SECONDS


class DemoCatalogAdapter:
    """Catálogo en vivo de una tienda pública. Sin credenciales, solo lectura."""

    def __init__(
        self,
        store_domain: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.domain = normalize_domain(store_domain)
        self._transport = transport
        self._sleep = sleep

    async def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"https://{self.domain}/api/{STOREFRONT_API_VERSION}/graphql.json"
        async with httpx.AsyncClient(
            transport=self._transport,
            headers={"User-Agent": BOT_USER_AGENT},
            timeout=10,
        ) as client:
            for attempt in range(MAX_RETRIES + 1):
                response = await client.post(
                    url, json={"query": query, "variables": variables or {}}
                )
                if response.status_code != 429:
                    break
                wait = retry_after_seconds(response)
                if attempt == MAX_RETRIES or wait > MAX_RETRY_AFTER_SECONDS:
                    raise DemoCatalogError(f"rate_limited: retry_after={wait}s")
                logger.info(
                    "demo_catalog_rate_limited", extra={"domain": self.domain, "wait": wait}
                )
                await self._sleep(wait)
        if response.status_code != 200:
            raise DemoCatalogError(f"storefront_http_{response.status_code}")
        body = response.json()
        if body.get("errors"):
            raise DemoCatalogError(f"storefront_graphql_errors: {body['errors']}")
        data: dict[str, Any] = body["data"]
        return data

    async def search_products(
        self, ctx: Any, query: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        data = await self._graphql(_SEARCH_PRODUCTS, {"q": query, "n": limit})
        return [product_from_storefront(n) for n in data["products"]["nodes"]]

    async def get_shop_currency(self, ctx: Any) -> str:
        data = await self._graphql(_SHOP_CURRENCY)
        return str(data["shop"]["paymentSettings"]["currencyCode"])

    def __getattr__(self, name: str) -> Callable[..., Awaitable[Any]]:
        if name.startswith("_"):
            raise AttributeError(name)

        async def _unavailable(*args: Any, **kwargs: Any) -> Any:
            raise DemoCatalogUnavailable(f"{name}: la demo solo lee el catálogo público")

        return _unavailable
