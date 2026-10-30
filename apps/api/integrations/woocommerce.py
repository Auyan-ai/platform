"""Adapter de comercio para WooCommerce (ADR 0016 §3, §4 y §6).

Habla con la REST `wc/v3` con Basic auth (consumer key y secret, permisos `read_write`)
sobre HTTPS, y con `wp/v2` sin credenciales para las páginas públicas de políticas. Cada
pedido sale en la forma canónica del contrato (la REST de Shopify) que leen las skills y
el gate de identidad.

WooCommerce no tiene tags de pedido, ni API de devoluciones o cambios: esas capacidades
no se declaran y el agente escala esos casos. El seguimiento de envío solo existe si la
tienda usa el plugin Shipment Tracking (meta `_wc_shipment_tracking_items`).

Reintentos: una lectura se repite ante 429, 5xx o un fallo de red, con tope. Una
escritura nunca se repite: WooCommerce no admite clave de idempotencia.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import ipaddress
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx
import phonenumbers
from apps.api.integrations.base import IntegrationContext, MutationNotApplied
from apps.api.integrations.commerce import (
    CommerceActionError,
    CommerceAdapter,
    CommerceCapability,
    CreatedReturn,
    IssuedRefund,
    MarkedRefund,
    OrderSnapshot,
    RefundableBalance,
    SnapshotFulfillment,
    SnapshotTransaction,
    country_to_iso2,
    refund_marker,
)
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.services.identity import normalize_phone
from apps.api.services.returns import (
    ExchangeVariant,
    ReturnableOrder,
    ReturnCalculation,
    ReturnPlan,
)

logger = logging.getLogger(__name__)

CAPABILITIES = frozenset(
    {
        CommerceCapability.ORDER_READ,
        CommerceCapability.PRODUCT_READ,
        CommerceCapability.POLICIES,
        CommerceCapability.ORDER_NOTES,
        CommerceCapability.CANCEL,
        CommerceCapability.SHIPPING_ADDRESS,
        CommerceCapability.REFUNDS,
    }
)

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_READ_ATTEMPTS = 3
_READ_BACKOFF_SECONDS = 0.5
_MAX_RETRY_AFTER_SECONDS = 5.0
_SEARCH_PAGE = 50

# Errores de `POST /orders/{id}/refunds` tras los que consta que no hay reembolso:
# WooCommerce borra el que creó si la pasarela lo rechaza, y responde 500 con este código.
_REFUND_NOT_CREATED = frozenset(
    {"woocommerce_rest_cannot_create_order_refund", "woocommerce_rest_invalid_order_id"}
)

# Slugs de las páginas de políticas que WordPress y WooCommerce crean (en inglés) y los
# habituales de una tienda en español.
POLICY_SLUGS = (
    "refund_returns",
    "politica-de-devoluciones",
    "devoluciones",
    "envios",
    "politica-de-envios",
    "shipping",
    "terms",
    "terms-and-conditions",
    "terminos-y-condiciones",
    "condiciones-generales",
    "condiciones-de-venta",
    "privacy-policy",
    "politica-de-privacidad",
    "aviso-legal",
)


class WooCommerceError(CommerceActionError):
    """WooCommerce no permite la acción, o su respuesta no se puede usar."""


class WooCommerceRejected(WooCommerceError, MutationNotApplied):
    """Consta que la escritura no se aplicó: WooCommerce la rechazó o no llegó a enviarse."""


# ─── Forma canónica del pedido ────────────────────────────────────────────────


def _money(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _gmt(value: str | None) -> str | None:
    """Fecha `*_gmt` de WooCommerce (sin zona) en ISO 8601 con offset UTC."""
    return f"{value}+00:00" if value else None


def refunded_total(order: dict[str, Any]) -> Decimal:
    """Lo reembolsado según el pedido (`refunds[].total` va en negativo)."""
    return sum((abs(_money(r.get("total"))) for r in order.get("refunds") or []), Decimal(0))


def tracking_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    """Envíos con número de seguimiento del plugin Shipment Tracking, si la tienda lo usa."""
    for meta in order.get("meta_data") or []:
        if meta.get("key") == "_wc_shipment_tracking_items" and isinstance(meta.get("value"), list):
            return [t for t in meta["value"] if isinstance(t, dict) and t.get("tracking_number")]
    return []


def financial_status(order: dict[str, Any]) -> str:
    """`financial_status` de Shopify a partir del pedido de WooCommerce.

    | status de WC                               | date_paid | financial_status         |
    |--------------------------------------------|-----------|--------------------------|
    | refunded                                   | cualquiera| refunded                 |
    | cancelled                                  | vacío     | voided                   |
    | pending, on-hold, failed, checkout-draft   | vacío     | pending                  |
    | cualquier otro (processing, completed…)    | puesto    | paid                     |
    |   … con reembolsos por debajo del total     | puesto    | partially_refunded       |
    |   … con reembolsos que cubren el total      | puesto    | refunded                 |

    El cobro lo dice `date_paid`, no el estado: WooCommerce lo pone al pasar a un estado
    pagado (processing, completed) y una transferencia en `on-hold` no lo tiene.
    """
    status = order.get("status")
    if status == "refunded":
        return "refunded"
    if not order.get("date_paid"):
        return "voided" if status == "cancelled" else "pending"
    refunded = refunded_total(order)
    if refunded <= 0:
        return "paid"
    return "refunded" if refunded >= _money(order.get("total")) else "partially_refunded"


def fulfillment_status(order: dict[str, Any]) -> str | None:
    """`fulfillment_status` de Shopify (REST).

    | status de WC | seguimiento (Shipment Tracking) | fulfillment_status |
    |--------------|---------------------------------|--------------------|
    | completed    | cualquiera                      | fulfilled          |
    | otro         | con algún número                | partial            |
    | otro         | sin seguimiento                 | None (sin enviar)  |

    WooCommerce no sabe qué artículos van en cada envío: un número de seguimiento en un
    pedido sin completar cuenta como envío parcial, nunca como no enviado.
    """
    if order.get("status") == "completed":
        return "fulfilled"
    return "partial" if tracking_items(order) else None


_DISPLAY_FULFILLMENT = {"fulfilled": "fulfilled", "partial": "partially_fulfilled"}


def _shipped_at(item: dict[str, Any]) -> str | None:
    raw = item.get("date_shipped")
    if raw in (None, ""):
        return None
    try:
        return _dt.datetime.fromtimestamp(int(raw), _dt.UTC).isoformat()
    except (TypeError, ValueError):
        return str(raw)


def canonical_fulfillments(order: dict[str, Any]) -> list[dict[str, Any]]:
    """Un fulfillment por número de seguimiento. Un pedido completado sin seguimiento
    lleva uno sin número, fechado al completarse: así consta que salió y cuándo."""
    fulfillments = []
    for item in tracking_items(order):
        number = str(item["tracking_number"])
        link = item.get("custom_tracking_link") or None
        shipped = _shipped_at(item)
        fulfillments.append(
            {
                "id": item.get("tracking_id"),
                "status": "success",
                "created_at": shipped,
                "updated_at": shipped,
                "tracking_company": item.get("custom_tracking_provider")
                or item.get("tracking_provider")
                or None,
                "tracking_number": number,
                "tracking_numbers": [number],
                "tracking_url": link,
                "tracking_urls": [link] if link else [],
                "shipment_status": None,
            }
        )
    if not fulfillments and order.get("status") == "completed":
        completed = _gmt(order.get("date_completed_gmt"))
        fulfillments.append(
            {
                "id": None,
                "status": "success",
                "created_at": completed,
                "updated_at": completed,
                "tracking_company": None,
                "tracking_number": None,
                "tracking_numbers": [],
                "tracking_url": None,
                "tracking_urls": [],
                "shipment_status": None,
            }
        )
    return fulfillments


def _money_set(amount: Any, currency: str) -> dict[str, Any]:
    money = {"amount": str(amount), "currency_code": currency}
    return {"shop_money": money, "presentment_money": dict(money)}


def _address(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw or not any(raw.get(k) for k in ("address_1", "city", "postcode")):
        return None
    country = raw.get("country") or None
    return {
        "first_name": raw.get("first_name") or None,
        "last_name": raw.get("last_name") or None,
        "company": raw.get("company") or None,
        "address1": raw.get("address_1") or None,
        "address2": raw.get("address_2") or None,
        "city": raw.get("city") or None,
        "province": raw.get("state") or None,
        "province_code": raw.get("state") or None,
        "zip": raw.get("postcode") or None,
        "country": country,
        "country_code": country,
        "phone": raw.get("phone") or None,
    }


def _line_item(item: dict[str, Any], currency: str) -> dict[str, Any]:
    quantity = int(item.get("quantity") or 0)
    unit = item.get("price")
    if unit is None and quantity:
        unit = _money(item.get("subtotal")) / quantity
    price = f"{_money(unit):.2f}"
    return {
        "id": item["id"],
        "title": item.get("name") or "",
        "name": item.get("name") or "",
        "quantity": quantity,
        "sku": item.get("sku") or None,
        "product_id": item.get("product_id") or None,
        "variant_id": item.get("variation_id") or None,
        "price": price,
        "price_set": _money_set(price, currency),
    }


def canonical_order(order: dict[str, Any]) -> dict[str, Any]:
    """El pedido de WooCommerce en la forma REST de Shopify del contrato de comercio."""
    currency = str(order.get("currency") or "")
    billing = order.get("billing") or {}
    number = str(order.get("number") or order["id"])
    customer_id = order.get("customer_id") or 0
    customer = (
        {
            "id": customer_id,
            "email": billing.get("email") or None,
            "phone": billing.get("phone") or None,
            "first_name": billing.get("first_name") or None,
            "last_name": billing.get("last_name") or None,
        }
        if customer_id
        else None
    )
    cancelled = order.get("status") == "cancelled"
    return {
        "id": order["id"],
        "name": f"#{number}",
        "order_number": number,
        "email": billing.get("email") or None,
        "phone": billing.get("phone") or None,
        "customer": customer,
        "financial_status": financial_status(order),
        "fulfillment_status": fulfillment_status(order),
        "cancelled_at": _gmt(order.get("date_modified_gmt")) if cancelled else None,
        "created_at": _gmt(order.get("date_created_gmt")),
        "currency": currency,
        "presentment_currency": currency,
        "total_price": str(order.get("total") or "0"),
        "total_price_set": _money_set(order.get("total") or "0", currency),
        "total_tax": str(order.get("total_tax") or "0"),
        "line_items": [_line_item(i, currency) for i in order.get("line_items") or []],
        "shipping_address": _address(order.get("shipping")),
        "billing_address": _address(billing),
        "fulfillments": canonical_fulfillments(order),
        "payment_gateway_names": [order["payment_method"]] if order.get("payment_method") else [],
        "tags": "",
    }


# ─── Snapshot y reembolsos ────────────────────────────────────────────────────


def refund_transaction(refund: dict[str, Any], gateway: str | None) -> SnapshotTransaction:
    """Un reembolso de WooCommerce. Existe solo si se completó: si la pasarela rechaza,
    WooCommerce lo borra. `refunded_payment=false` es un reembolso apuntado a mano."""
    return SnapshotTransaction(
        id=f"refund:{refund['id']}",
        kind="refund",
        status="success",
        gateway=gateway,
        manual_gateway=not refund.get("refunded_payment"),
        error_code=None,
    )


def order_snapshot(
    order: dict[str, Any], refunds: list[dict[str, Any]], *, gateway_refunds: bool
) -> OrderSnapshot:
    """Lo que decide una L3, con transacciones sintetizadas: un cobro si hay `date_paid`
    (manual si la pasarela no reembolsa por API) y un reembolso por cada uno del pedido."""
    gateway = order.get("payment_method") or None
    transactions: list[SnapshotTransaction] = []
    if order.get("date_paid"):
        transactions.append(
            SnapshotTransaction(
                id=f"payment:{order.get('transaction_id') or order['id']}",
                kind="sale",
                status="success",
                gateway=gateway,
                manual_gateway=not gateway_refunds,
                error_code=None,
            )
        )
    transactions.extend(refund_transaction(r, gateway) for r in refunds)
    shipping = order.get("shipping") or {}
    status = fulfillment_status(order)
    return OrderSnapshot(
        order_id=int(order["id"]),
        name=f"#{order.get('number') or order['id']}",
        cancelled=order.get("status") == "cancelled",
        fulfillment_status=_DISPLAY_FULFILLMENT.get(status or "", "unfulfilled"),
        fulfillments=tuple(
            SnapshotFulfillment(status=f["status"], tracking_numbers=tuple(f["tracking_numbers"]))
            for f in canonical_fulfillments(order)
        ),
        transactions=tuple(transactions),
        shipping_address={
            "address1": shipping.get("address_1") or None,
            "address2": shipping.get("address_2") or None,
            "city": shipping.get("city") or None,
            "zip": shipping.get("postcode") or None,
            "country": shipping.get("country") or None,
        },
    )


def refundable_balance(order: dict[str, Any]) -> RefundableBalance:
    if not order.get("date_paid"):
        raise WooCommerceError("order_has_no_refundable_payment")
    currency = order.get("currency")
    if not currency:
        raise WooCommerceError("order_currency_missing")
    return RefundableBalance(
        captured=_money(order.get("total")),
        refunded=refunded_total(order),
        currency=str(currency),
    )


# ─── Productos y políticas ────────────────────────────────────────────────────


def _available(raw: dict[str, Any]) -> bool:
    return raw.get("purchasable", True) is not False and raw.get("stock_status") in (
        "instock",
        "onbackorder",
    )


def canonical_product(product: dict[str, Any], variations: list[dict[str, Any]]) -> dict[str, Any]:
    """El producto en la forma de `products.json` de Shopify. Un producto simple es su
    única variante, con el id del producto."""
    if variations:
        variants = [
            {
                "id": v["id"],
                "title": " / ".join(str(a.get("option")) for a in v.get("attributes") or [])
                or product.get("name", ""),
                "price": str(v.get("price") or "0.00"),
                "available": _available(v),
            }
            for v in variations
        ]
    else:
        variants = [
            {
                "id": product["id"],
                "title": product.get("name", ""),
                "price": str(product.get("price") or "0.00"),
                "available": _available(product),
            }
        ]
    categories = product.get("categories") or []
    return {
        "id": product["id"],
        "title": product.get("name", ""),
        "product_type": categories[0].get("name", "") if categories else "",
        "status": "active",
        "body_html": product.get("description") or product.get("short_description") or "",
        "tags": [t.get("name", "") for t in product.get("tags") or []],
        "variants": variants,
    }


def canonical_policy(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": (page.get("title") or {}).get("rendered", ""),
        "body": (page.get("content") or {}).get("rendered", ""),
        "url": page.get("link", ""),
        "handle": page.get("slug", ""),
    }


# ─── Cliente HTTP ─────────────────────────────────────────────────────────────


def _ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if host == "localhost":
        return ipaddress.ip_address("127.0.0.1")
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def store_base_url(store_url: str, *, allow_http_loopback: bool) -> str:
    """La URL de la tienda, solo HTTPS: Basic auth viaja con la clave en claro.

    Una IP privada, de enlace local o de loopback no es una tienda: se rechaza para que la
    API no llame a su propia red. Loopback por HTTP solo con el flag de desarrollo.
    """
    parts = urlsplit(store_url.strip())
    host = parts.hostname
    if not host:
        raise ValueError(f"woocommerce_store_url_invalid: {store_url!r}")
    ip = _ip(host)
    if ip is not None and ip.is_loopback:
        if not allow_http_loopback or parts.scheme not in ("http", "https"):
            raise ValueError("woocommerce_store_url_must_be_public")
    elif ip is not None and (ip.is_private or ip.is_link_local or ip.is_reserved):
        raise ValueError("woocommerce_store_url_must_be_public")
    elif parts.scheme != "https":
        raise ValueError("woocommerce_store_url_must_be_https")
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}"


@dataclass(frozen=True)
class _ApiError:
    status: int
    code: str | None
    message: str


def _api_error(response: httpx.Response) -> _ApiError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return _ApiError(
        status=response.status_code,
        code=body.get("code"),
        message=str(body.get("message") or response.text[:200]),
    )


class WooCommerceClient:
    def __init__(
        self,
        base_url: str,
        consumer_key: str,
        consumer_secret: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = base_url
        self._auth = httpx.BasicAuth(consumer_key, consumer_secret)
        self._transport = transport

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=_TIMEOUT, transport=self._transport, follow_redirects=False
        )

    async def get(
        self, path: str, params: dict[str, Any] | None = None, *, auth: bool = True
    ) -> Any:
        """GET con reintento acotado ante 429, 5xx y fallos de red."""
        url = f"{self._base}/wp-json/{path}"
        for attempt in range(1, _READ_ATTEMPTS + 1):
            delay = _READ_BACKOFF_SECONDS * 2 ** (attempt - 1)
            try:
                async with self._http() as http:
                    response = await http.get(url, params=params, auth=self._auth if auth else None)
            except httpx.TransportError:
                if attempt == _READ_ATTEMPTS:
                    raise
            else:
                retryable = response.status_code == 429 or response.status_code >= 500
                if not retryable or attempt == _READ_ATTEMPTS:
                    response.raise_for_status()
                    return response.json()
                retry_after = response.headers.get("retry-after", "")
                if retry_after.isdigit():
                    delay = min(float(retry_after), _MAX_RETRY_AFTER_SECONDS)
            logger.warning("woocommerce.read_retry path=%s attempt=%d", path, attempt)
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def write(self, method: str, path: str, body: dict[str, Any]) -> httpx.Response:
        """Una escritura, sin reintento. Un fallo de conexión es que no llegó a enviarse;
        cualquier otro error de red deja el resultado sin saber y se propaga."""
        try:
            async with self._http() as http:
                return await http.request(
                    method, f"{self._base}/wp-json/{path}", json=body, auth=self._auth
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise WooCommerceRejected(f"{type(exc).__name__}: {exc}") from exc


# ─── Adapter stateless ────────────────────────────────────────────────────────


@IntegrationRegistry.register(kind="commerce", provider="woocommerce")
class WooCommerceAdapter:
    """CommerceAdapter de WooCommerce.

    Credenciales: `store_url` (https://tienda.es), `consumer_key`, `consumer_secret`.

    El número visible del pedido (`number`) puede no ser el id: con un plugin de
    numeración secuencial lo filtra el plugin. Una referencia se resuelve primero como
    número visible y, si ninguno coincide, como id. Si apunta a dos pedidos distintos
    (el número de uno es el id de otro), la acción no sigue: `order_ref_ambiguous`.
    """

    capabilities = CAPABILITIES
    platform_name: ClassVar[str] = "WooCommerce"

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        allow_http_loopback: bool | None = None,
    ) -> None:
        self._transport = transport
        self._allow_http_loopback = allow_http_loopback

    def _http_loopback_allowed(self) -> bool:
        if self._allow_http_loopback is not None:
            return self._allow_http_loopback
        from apps.api.core.config import get_settings

        return get_settings().woocommerce_allow_http_loopback

    def _client(self, ctx: IntegrationContext) -> WooCommerceClient:
        creds = ctx.credentials
        missing = [k for k in ("store_url", "consumer_key", "consumer_secret") if not creds.get(k)]
        if missing:
            raise ValueError(f"woocommerce credentials missing {', '.join(missing)}")
        url = str(creds["store_url"])
        host = _ip(urlsplit(url.strip()).hostname or "")
        allow = host is not None and host.is_loopback and self._http_loopback_allowed()
        return WooCommerceClient(
            store_base_url(url, allow_http_loopback=allow),
            str(creds["consumer_key"]),
            str(creds["consumer_secret"]),
            transport=self._transport,
        )

    # ── Resolución de pedidos ──────────────────────────────────────────────────

    async def _order_by_id(self, client: WooCommerceClient, order_id: str) -> dict[str, Any] | None:
        if not order_id.isdigit():
            return None
        try:
            order: dict[str, Any] = await client.get(f"wc/v3/orders/{order_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return order

    async def _order_by_number(
        self, client: WooCommerceClient, number: str, by_id: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if by_id is not None and str(by_id.get("number")) == number:
            return by_id
        found: list[dict[str, Any]] = await client.get(
            "wc/v3/orders", {"search": number, "per_page": _SEARCH_PAGE}
        )
        return next((o for o in found if str(o.get("number")) == number), None)

    async def _find(self, client: WooCommerceClient, ref: Any) -> dict[str, Any]:
        """El pedido de una referencia: número visible primero, id después. Lanza
        `WooCommerceError` si no existe o si número e id son de pedidos distintos."""
        wanted = str(ref).strip().lstrip("#").strip()
        by_id = await self._order_by_id(client, wanted)
        by_number = await self._order_by_number(client, wanted, by_id)
        if by_number is not None and by_id is not None and by_number["id"] != by_id["id"]:
            raise WooCommerceError(
                f"order_ref_ambiguous: {wanted} es el número del pedido {by_number['id']} "
                f"y el id de otro pedido (número {by_id.get('number')})"
            )
        order = by_number or by_id
        if order is None:
            raise WooCommerceError(f"order_not_found: {wanted}")
        return order

    async def _gateway_refunds(self, client: WooCommerceClient, gateway: str | None) -> bool:
        """True si la pasarela reembolsa por API (`refunds` en `method_supports`)."""
        if not gateway:
            return False
        try:
            data = await client.get(f"wc/v3/payment_gateways/{gateway}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        return "refunds" in (data.get("method_supports") or [])

    # ── order_read ─────────────────────────────────────────────────────────────

    async def get_order(self, ctx: IntegrationContext, order_id: str) -> dict[str, Any]:
        order = await self._client(ctx).get(f"wc/v3/orders/{int(order_id)}")
        return canonical_order(order)

    async def get_order_by_name(
        self, ctx: IntegrationContext, order_name: str
    ) -> dict[str, Any] | None:
        client = self._client(ctx)
        number = str(order_name).strip().lstrip("#").strip()
        if not number:
            return None
        order = await self._order_by_number(client, number, await self._order_by_id(client, number))
        return canonical_order(order) if order else None

    async def _search_orders(
        self, ctx: IntegrationContext, term: str, keep: Any, limit: int
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = await self._client(ctx).get(
            "wc/v3/orders", {"search": term, "per_page": _SEARCH_PAGE}
        )
        return [canonical_order(o) for o in found if keep(o)][:limit]

    async def search_orders_by_email(
        self, ctx: IntegrationContext, email: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        """`search` de WooCommerce busca por subcadena en muchos campos: se queda solo con
        los pedidos cuyo email de facturación es exactamente ese."""
        wanted = email.strip().casefold()
        if not wanted:
            return []
        return await self._search_orders(
            ctx,
            wanted,
            lambda o: str((o.get("billing") or {}).get("email") or "").casefold() == wanted,
            limit,
        )

    async def search_orders_by_phone(
        self, ctx: IntegrationContext, phone: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Busca por el número nacional (casa tanto `612333444` como `+34612333444`) y
        compara en E.164 con la región del país de facturación de cada pedido."""
        wanted = normalize_phone(phone)
        if wanted is None:
            return []
        national = str(phonenumbers.parse(wanted).national_number)

        def keep(order: dict[str, Any]) -> bool:
            billing = order.get("billing") or {}
            raw = billing.get("phone")
            region = str(billing.get("country") or "ES")
            return bool(raw) and normalize_phone(str(raw), region) == wanted

        return await self._search_orders(ctx, national, keep, limit)

    async def get_order_snapshot(self, ctx: IntegrationContext, order_id: int) -> OrderSnapshot:
        client = self._client(ctx)
        order = await self._find(client, order_id)
        refunds = await client.get(f"wc/v3/orders/{order['id']}/refunds", {"per_page": 100})
        supports = await self._gateway_refunds(client, order.get("payment_method"))
        return order_snapshot(order, refunds, gateway_refunds=supports)

    # ── product_read ───────────────────────────────────────────────────────────

    async def search_products(
        self, ctx: IntegrationContext, query: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        client = self._client(ctx)
        products: list[dict[str, Any]] = await client.get(
            "wc/v3/products", {"search": query, "status": "publish", "per_page": limit}
        )
        result = []
        for product in products:
            variations: list[dict[str, Any]] = []
            if product.get("type") == "variable":
                variations = await client.get(
                    f"wc/v3/products/{product['id']}/variations", {"per_page": 100}
                )
            result.append(canonical_product(product, variations))
        return result

    async def get_shop_currency(self, ctx: IntegrationContext) -> str:
        data = await self._client(ctx).get("wc/v3/settings/general/woocommerce_currency")
        return str(data["value"])

    # ── policies ───────────────────────────────────────────────────────────────

    async def get_policies(self, ctx: IntegrationContext) -> list[dict[str, Any]]:
        """Las páginas publicadas de políticas, por `wp/v2` y sin credenciales: WordPress
        trata un Basic auth que no es una contraseña de aplicación como login fallido."""
        pages: list[dict[str, Any]] = await self._client(ctx).get(
            "wp/v2/pages",
            {
                "slug": ",".join(POLICY_SLUGS),
                "per_page": 100,
                "_fields": "slug,title,content,link",
            },
            auth=False,
        )
        return [canonical_policy(p) for p in pages]

    # ── order_notes ────────────────────────────────────────────────────────────

    async def _post_note(self, client: WooCommerceClient, order_id: int, note: str) -> None:
        response = await client.write(
            "POST", f"wc/v3/orders/{order_id}/notes", {"note": note, "customer_note": False}
        )
        self._raise_for_write(response, "order_note")

    async def add_order_note(
        self, ctx: IntegrationContext, order_id: int, note: str
    ) -> dict[str, Any]:
        """Añade una nota privada (las notas de WooCommerce no se reemplazan)."""
        client = self._client(ctx)
        order = await self._find(client, order_id)
        await self._post_note(client, order["id"], note)
        return {"id": order["id"], "note": note}

    async def append_order_note(self, ctx: IntegrationContext, order_id: int, text: str) -> None:
        """Añade `text` como nota privada salvo que alguna nota ya lo lleve."""
        client = self._client(ctx)
        order = await self._find(client, order_id)
        notes = await client.get(f"wc/v3/orders/{order['id']}/notes", {"type": "internal"})
        if any(text.strip() in str(n.get("note") or "") for n in notes):
            return
        await self._post_note(client, order["id"], text)

    async def tag_order(
        self, ctx: IntegrationContext, order_id: int, tags_to_add: list[str]
    ) -> dict[str, Any]:
        raise WooCommerceRejected("capability_not_supported: order_tags")

    # ── cancel / shipping_address ──────────────────────────────────────────────

    def _raise_for_write(self, response: httpx.Response, action: str) -> None:
        """Un 4xx es WooCommerce rechazando la escritura. Un 5xx no dice si se guardó."""
        if response.is_success:
            return
        error = _api_error(response)
        if response.is_client_error:
            raise WooCommerceRejected(f"{action}_rejected: {error.code}: {error.message}")
        response.raise_for_status()

    async def _create_refund(
        self,
        client: WooCommerceClient,
        order: dict[str, Any],
        *,
        amount: Decimal,
        reason: str,
        api_refund: bool,
    ) -> IssuedRefund:
        """`POST /orders/{id}/refunds` por la pasarela si reembolsa por API
        (`api_refund: true`, ver `_gateway_refunds`); si no, solo se apunta y devuelve la
        tienda.

        Un 4xx, o un 500 con `woocommerce_rest_cannot_create_order_refund` (WooCommerce
        borra el reembolso que la pasarela rechaza), es `WooCommerceRejected`. Cualquier
        otro fallo tras enviarlo deja el resultado sin saber y se propaga.
        """
        currency = refundable_balance(order).currency
        response = await client.write(
            "POST",
            f"wc/v3/orders/{order['id']}/refunds",
            {"amount": f"{amount:.2f}", "reason": reason, "api_refund": api_refund},
        )
        if response.is_success:
            created = response.json()
            return IssuedRefund(
                refund_id=int(created["id"]), amount=_money(created["amount"]), currency=currency
            )
        error = _api_error(response)
        if response.is_client_error or error.code in _REFUND_NOT_CREATED:
            raise WooCommerceRejected(f"refund_create_failed: {error.code}: {error.message}")
        response.raise_for_status()
        raise AssertionError("unreachable")

    async def cancel_order(
        self,
        ctx: IntegrationContext,
        order_id: int,
        *,
        reason: str = "customer",
        email: bool = True,
        refund: bool,
        restock: bool,
    ) -> dict[str, Any]:
        """Pasa el pedido a `cancelled` y, con `refund`, reembolsa lo que quede por la
        misma ruta que `refund_partial`.

        WooCommerce repone el stock al cancelar (`restock` no lo cambia) y no avisa al
        cliente (`email` tampoco). Si la pasarela rechaza el reembolso, el pedido ya está
        cancelado: no se lanza `MutationNotApplied`, y el veredicto de la skill, al releer
        el pedido sin reembolso, lo da por fallido. Un reembolso del total pasa el pedido a
        `refunded`: se vuelve a dejar en `cancelled`, que es lo que se pidió.
        """
        client = self._client(ctx)
        try:
            order = await self._find(client, order_id)
            api_refund = await self._gateway_refunds(client, order.get("payment_method"))
        except (WooCommerceError, httpx.HTTPError) as exc:
            raise WooCommerceRejected(f"{type(exc).__name__}: {exc}") from exc
        response = await client.write("PUT", f"wc/v3/orders/{order['id']}", {"status": "cancelled"})
        self._raise_for_write(response, "order_cancel")
        cancelled: dict[str, Any] = response.json()
        if refund and cancelled.get("date_paid"):
            balance = refundable_balance(cancelled)
            if balance.remaining > 0:
                try:
                    await self._create_refund(
                        client,
                        cancelled,
                        amount=balance.remaining,
                        reason=f"Cancelación del pedido ({reason})",
                        api_refund=api_refund,
                    )
                except WooCommerceRejected as exc:
                    logger.error(
                        "woocommerce.cancel_refund_rejected order_id=%s error=%s",
                        order["id"],
                        exc,
                    )
            cancelled = await client.get(f"wc/v3/orders/{order['id']}")
            if cancelled.get("status") != "cancelled":
                response = await client.write(
                    "PUT", f"wc/v3/orders/{order['id']}", {"status": "cancelled"}
                )
                # Ya hubo cancelación y reembolso: un fallo aquí no es "no aplicado".
                response.raise_for_status()
                cancelled = response.json()
        return canonical_order(cancelled)

    async def update_shipping_address(
        self,
        ctx: IntegrationContext,
        order_id: int,
        *,
        address1: str,
        address2: str | None = None,
        city: str,
        province: str,
        zip_code: str,
        country: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> dict[str, Any]:
        """Cambia la dirección de envío. Sin `country` se conserva el del pedido; con él,
        se manda su código ISO-2 si se reconoce."""
        client = self._client(ctx)
        try:
            order = await self._find(client, order_id)
        except (WooCommerceError, httpx.HTTPError) as exc:
            raise WooCommerceRejected(f"{type(exc).__name__}: {exc}") from exc
        shipping: dict[str, Any] = {
            "address_1": address1,
            # Siempre se envía: no debe quedar el piso de la dirección vieja.
            "address_2": address2 or "",
            "city": city,
            "state": province,
            "postcode": zip_code,
        }
        if country:
            shipping["country"] = country_to_iso2(country) or country
        if first_name:
            shipping["first_name"] = first_name
        if last_name:
            shipping["last_name"] = last_name
        response = await client.write("PUT", f"wc/v3/orders/{order['id']}", {"shipping": shipping})
        self._raise_for_write(response, "address_update")
        return canonical_order(response.json())

    # ── refunds ────────────────────────────────────────────────────────────────

    async def get_refundable_balance(
        self, ctx: IntegrationContext, order_id: int
    ) -> RefundableBalance:
        return refundable_balance(await self._find(self._client(ctx), order_id))

    async def refund_partial(
        self,
        ctx: IntegrationContext,
        order_id: int,
        *,
        amount: Decimal,
        note: str = "",
        idempotency_key: str,
    ) -> IssuedRefund:
        """Reembolso parcial con la marca de la ejecución en `reason`. Tope y moneda salen
        del pedido: lo que falla antes de enviarlo es `WooCommerceRejected`."""
        client = self._client(ctx)
        try:
            order = await self._find(client, order_id)
            refundable_balance(order).require(amount)
            api_refund = await self._gateway_refunds(client, order.get("payment_method"))
        except (CommerceActionError, httpx.HTTPError) as exc:
            raise WooCommerceRejected(f"{type(exc).__name__}: {exc}") from exc
        reason = f"{note} {refund_marker(idempotency_key)}".strip()
        return await self._create_refund(
            client, order, amount=amount, reason=reason, api_refund=api_refund
        )

    async def find_refund(
        self, ctx: IntegrationContext, order_id: int, idempotency_key: str
    ) -> MarkedRefund | None:
        client = self._client(ctx)
        order = await self._find(client, order_id)
        marker = refund_marker(idempotency_key)
        refunds = await client.get(f"wc/v3/orders/{order['id']}/refunds", {"per_page": 100})
        gateway = order.get("payment_method") or None
        for refund in refunds:
            if marker in str(refund.get("reason") or ""):
                return MarkedRefund(
                    refund_id=int(refund["id"]),
                    amount=_money(refund.get("amount")),
                    currency=str(order.get("currency") or ""),
                    transactions=(refund_transaction(refund, gateway),),
                )
        return None

    # ── Fuera de capacidades: returns / exchanges ──────────────────────────────

    async def get_returnable_order(self, ctx: IntegrationContext, order_id: int) -> ReturnableOrder:
        raise WooCommerceRejected("capability_not_supported: returns")

    async def get_exchange_variants(
        self, ctx: IntegrationContext, variant_ids: list[int]
    ) -> tuple[ExchangeVariant, ...]:
        raise WooCommerceRejected("capability_not_supported: exchanges")

    async def calculate_return(
        self,
        ctx: IntegrationContext,
        order_id: int,
        *,
        lines: list[tuple[str, int]],
        exchange: list[tuple[int, int]],
    ) -> ReturnCalculation:
        raise WooCommerceRejected("capability_not_supported: returns")

    async def find_return(self, ctx: IntegrationContext, plan: ReturnPlan) -> CreatedReturn | None:
        raise WooCommerceRejected("capability_not_supported: returns")

    async def create_return(self, ctx: IntegrationContext, plan: ReturnPlan) -> CreatedReturn:
        raise WooCommerceRejected("capability_not_supported: returns")

    # ── Alta de la integración ─────────────────────────────────────────────────

    async def validate(self, ctx: IntegrationContext) -> dict[str, Any]:
        """Comprueba la tienda y que la clave sea `read_write` sin tocar nada.

        `GET /system_status` lee la tienda. `POST /orders/batch` vacío no crea nada,
        pero WooCommerce rechaza con 401 una clave sin permiso de escritura.
        """
        client = self._client(ctx)
        status = await client.get("wc/v3/system_status")
        response = await client.write("POST", "wc/v3/orders/batch", {})
        if response.status_code in (401, 403):
            error = _api_error(response)
            raise WooCommerceRejected(f"woocommerce_key_not_read_write: {error.message}")
        response.raise_for_status()
        environment = status.get("environment") or {}
        settings = status.get("settings") or {}
        return {
            "site_url": environment.get("site_url"),
            "wc_version": environment.get("version"),
            "currency": settings.get("currency"),
        }


_: CommerceAdapter = WooCommerceAdapter()
