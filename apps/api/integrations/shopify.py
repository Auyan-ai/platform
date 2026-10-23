"""Cliente HTTP para la Admin REST API de Shopify.

Expone tres capas:
- `exchange_client_credentials`: OAuth 2.0 Client Credentials Grant (server-to-server).
  Shopify deprecó los Custom Apps legacy con `shpat_` token permanente el 1-ene-2026.
  El flow nuevo: app creada en Dev Dashboard → merchant copia client_id+client_secret
  → Auyan los intercambia por access_token de 24h.
- `ShopifyClient`: cliente HTTP con estado (domain + access_token corto en __init__).
- `ShopifyAdapter`: adapter stateless. Recibe IntegrationContext por llamada con
  access_token ya válido. Quien construye el ctx (router connect, agente) es el
  responsable de refrescar el token via `ensure_shopify_access_token` antes.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import httpx
from apps.api.integrations.base import (
    CommerceProvider,
    IntegrationContext,
    MutationNotApplied,
)
from apps.api.integrations.registry import IntegrationRegistry

logger = logging.getLogger(__name__)

_API_VERSION = "2026-04"
# Refrescamos el access_token 5min antes de que expire para evitar race conditions
# entre "valido" en el check y "expirado" al hacer la llamada real a Shopify.
_TOKEN_REFRESH_BUFFER_SECONDS = 300

# Cache EN MEMORIA del access_token corto (24h) por tenant. A propósito NO se persiste
# en DB: el token es una credencial viva y guardarlo en `tenant_integrations.config` en
# claro rompía el cifrado en reposo. En memoria sólo vive en el proceso; cada worker
# re-deriva como mucho 1 vez por ventana del token. Acotado con maxsize (ver
# [[feedback_caches_bounded]]): nunca un dict sin tope.
_TOKEN_CACHE_MAXSIZE = 1024
_token_cache: OrderedDict[UUID, tuple[str, _dt.datetime]] = OrderedDict()


def _token_cache_get(tenant_id: UUID) -> tuple[str, _dt.datetime] | None:
    entry = _token_cache.get(tenant_id)
    if entry is not None:
        _token_cache.move_to_end(tenant_id)
    return entry


def _token_cache_set(tenant_id: UUID, token: str, expires_at: _dt.datetime) -> None:
    _token_cache[tenant_id] = (token, expires_at)
    _token_cache.move_to_end(tenant_id)
    while len(_token_cache) > _TOKEN_CACHE_MAXSIZE:
        _token_cache.popitem(last=False)


# Shopify rechaza el campo `country` en texto libre que no sea el nombre EN exacto
# (ej. "España" → 422 "Country/region not supported"). En su lugar mandamos
# `country_code` (ISO-3166-1 alfa-2), que sí resuelve. El agente recoge el país tal
# como lo escribe el cliente (normalmente en español), así que normalizamos aquí.
# Auyan es ES-first; cubrimos España + destinos de envío habituales (UE + comunes).
_COUNTRY_TO_ISO2: dict[str, str] = {
    "españa": "ES",
    "espana": "ES",
    "spain": "ES",
    "portugal": "PT",
    "francia": "FR",
    "france": "FR",
    "italia": "IT",
    "italy": "IT",
    "alemania": "DE",
    "germany": "DE",
    "deutschland": "DE",
    "andorra": "AD",
    "reino unido": "GB",
    "united kingdom": "GB",
    "uk": "GB",
    "irlanda": "IE",
    "ireland": "IE",
    "países bajos": "NL",
    "paises bajos": "NL",
    "holanda": "NL",
    "netherlands": "NL",
    "bélgica": "BE",
    "belgica": "BE",
    "belgium": "BE",
    "suiza": "CH",
    "switzerland": "CH",
    "estados unidos": "US",
    "united states": "US",
    "usa": "US",
    "méxico": "MX",
    "mexico": "MX",
}


def _country_to_iso2(country: str) -> str | None:
    """Resuelve un país en texto libre a su código ISO-2, o None si no se reconoce.

    Acepta un código de 2 letras tal cual (Shopify lo valida). Para nombres,
    mapea español/inglés comunes. Si devuelve None, el caller manda el texto
    original como `country` (best-effort).
    """
    c = country.strip()
    if len(c) == 2 and c.isalpha():
        return c.upper()
    return _COUNTRY_TO_ISO2.get(c.lower())


async def exchange_client_credentials(
    *,
    shop_domain: str,
    client_id: str,
    client_secret: str,
) -> tuple[str, int]:
    """OAuth 2.0 Client Credentials Grant contra Shopify.

    POST https://{shop}.myshopify.com/admin/oauth/access_token
    Body: client_id + client_secret + grant_type=client_credentials
    Returns: (access_token, expires_in_seconds). Shopify devuelve tokens de 24h
    (86400s) pero respetamos `expires_in` por si Shopify lo cambia.

    Doc: https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/client-credentials-grant
    """
    url = f"https://{shop_domain.rstrip('/')}/admin/oauth/access_token"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    return str(data["access_token"]), int(data.get("expires_in", 86400))


async def ensure_shopify_access_token(
    *,
    tenant_id: UUID,
    domain: str,
    client_id: str,
    client_secret: str,
) -> tuple[str, _dt.datetime]:
    """Devuelve un access_token válido, usando un cache EN MEMORIA por tenant.

    Si el token cacheado está vigente con margen (>5min), lo devuelve. Si expiró o
    falta, hace Client Credentials Grant, lo guarda en memoria y lo devuelve. El token
    NUNCA se persiste en DB (es una credencial viva): sólo los secretos durables
    (client_id/secret) viven cifrados en `credentials_encrypted`.

    Returns: (access_token, expires_at_utc).
    """
    now = _dt.datetime.now(_dt.UTC)
    cached = _token_cache_get(tenant_id)
    if cached is not None:
        token, expires_at = cached
        if (expires_at - now).total_seconds() > _TOKEN_REFRESH_BUFFER_SECONDS:
            return token, expires_at

    new_token, expires_in = await exchange_client_credentials(
        shop_domain=domain,
        client_id=client_id,
        client_secret=client_secret,
    )
    new_expires_at = now + _dt.timedelta(seconds=expires_in)
    _token_cache_set(tenant_id, new_token, new_expires_at)
    logger.info(
        "shopify.token_refreshed tenant_id=%s expires_at=%s",
        tenant_id,
        new_expires_at.isoformat(),
    )
    return new_token, new_expires_at


class ShopifyClient:
    def __init__(self, shop_domain: str, access_token: str) -> None:
        self._domain = shop_domain.rstrip("/")
        self._token = access_token

    @property
    def _base_url(self) -> str:
        return f"https://{self._domain}/admin/api/{_API_VERSION}"

    def _headers(self) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": self._token,
            "Content-Type": "application/json",
        }

    # ----------------------------------------------------------------
    # Validación de credenciales
    # ----------------------------------------------------------------

    async def validate(self) -> dict[str, Any]:
        """Verifica domain + token contra la tienda. Devuelve el objeto `shop`.

        Lanza httpx.HTTPStatusError si las credenciales son inválidas (401/403/404).
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/shop.json",
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["shop"]  # type: ignore[no-any-return]

    async def get_shop_currency(self) -> str:
        """Moneda de la tienda (ISO 4217): en la que Shopify da los precios de producto."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/shop.json",
                headers=self._headers(),
                params={"fields": "currency"},
                timeout=10,
            )
            response.raise_for_status()
            return str(response.json()["shop"]["currency"])

    # ----------------------------------------------------------------
    # Orders
    # ----------------------------------------------------------------

    async def get_order(self, order_id: int) -> dict[str, Any]:
        """Devuelve un pedido por su ID numérico."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/orders/{order_id}.json",
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["order"]  # type: ignore[no-any-return]

    async def get_order_by_name(self, order_name: str) -> dict[str, Any] | None:
        """Devuelve el pedido que coincide con el nombre (ej. '#1234' o '1234').

        Normaliza el prefijo '#' automáticamente. Devuelve None si no existe.
        """
        if not order_name.startswith("#"):
            order_name = f"#{order_name}"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/orders.json",
                headers=self._headers(),
                params={"name": order_name, "status": "any"},
                timeout=10,
            )
            response.raise_for_status()
            orders: list[dict[str, Any]] = response.json()["orders"]
            return orders[0] if orders else None

    async def get_orders_by_email(self, email: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Devuelve hasta `limit` pedidos del email dado (más recientes primero)."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/orders.json",
                headers=self._headers(),
                params={"email": email, "status": "any", "limit": limit},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["orders"]  # type: ignore[no-any-return]

    # ----------------------------------------------------------------
    # Products
    # ----------------------------------------------------------------

    async def search_products(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Busca productos activos por título/keyword."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/products.json",
                headers=self._headers(),
                params={"title": query, "limit": limit, "status": "active"},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["products"]  # type: ignore[no-any-return]

    # ----------------------------------------------------------------
    # Customers
    # ----------------------------------------------------------------

    async def get_customer_by_phone(self, phone: str) -> dict[str, Any] | None:
        """Busca un customer por teléfono E.164. Devuelve None si no existe."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/customers/search.json",
                headers=self._headers(),
                params={"query": f"phone:{phone}", "limit": 1},
                timeout=10,
            )
            response.raise_for_status()
            customers: list[dict[str, Any]] = response.json()["customers"]
            return customers[0] if customers else None

    async def get_orders_by_customer_id(
        self, customer_id: int, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Devuelve hasta `limit` pedidos de un customer por su ID."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/customers/{customer_id}/orders.json",
                headers=self._headers(),
                params={"status": "any", "limit": limit},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["orders"]  # type: ignore[no-any-return]

    # ----------------------------------------------------------------
    # Shop
    # ----------------------------------------------------------------

    async def get_policies(self) -> list[dict[str, Any]]:
        """Devuelve todas las políticas de la tienda."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/policies.json",
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["policies"]  # type: ignore[no-any-return]

    # ----------------------------------------------------------------
    # Write — L2 (Sprint 9)
    # ----------------------------------------------------------------

    async def add_order_note(self, order_id: int, note: str) -> dict[str, Any]:
        """Reemplaza la nota interna de un pedido. Acción L2."""
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self._base_url}/orders/{order_id}.json",
                headers=self._headers(),
                json={"order": {"id": order_id, "note": note}},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["order"]  # type: ignore[no-any-return]

    async def tag_order(self, order_id: int, tags_to_add: list[str]) -> dict[str, Any]:
        """Añade tags a un pedido (merge no-destructivo). Acción L2.

        Lee los tags actuales del pedido y añade los nuevos sin duplicar.
        """
        async with httpx.AsyncClient() as client:
            # Leer tags actuales
            get_resp = await client.get(
                f"{self._base_url}/orders/{order_id}.json",
                headers=self._headers(),
                params={"fields": "id,tags"},
                timeout=10,
            )
            get_resp.raise_for_status()
            order = get_resp.json()["order"]
            current_tags: set[str] = {
                t.strip() for t in order.get("tags", "").split(",") if t.strip()
            }
            merged = sorted(current_tags | set(tags_to_add))
            merged_str = ", ".join(merged)

            # Actualizar con tags fusionados
            put_resp = await client.put(
                f"{self._base_url}/orders/{order_id}.json",
                headers=self._headers(),
                json={"order": {"id": order_id, "tags": merged_str}},
                timeout=10,
            )
            put_resp.raise_for_status()
            return put_resp.json()["order"]  # type: ignore[no-any-return]

    # ----------------------------------------------------------------
    # Write — L3 (Sprint 10)
    # ----------------------------------------------------------------

    async def cancel_order(
        self,
        order_id: int,
        *,
        reason: str = "customer",
        email: bool = True,
        refund: bool,
        restock: bool,
    ) -> dict[str, Any]:
        """Cancela un pedido. Acción L3 — requiere supervisor Opus y aprobación humana.

        GraphQL `orderCancel`: el `cancel.json` de REST ignoraba en silencio
        `"refund": true` (espera un objeto) → cancelaba SIN devolver el pago (visto en
        A4). Con `refund` se reembolsa al método de pago original. `refund` y
        `restock` los decide la skill a partir del pedido, nunca el LLM. La mutación
        es asíncrona: se espera a que el pedido figure cancelado y se devuelve el
        pedido (REST) como antes.
        """
        reason_enum = reason.strip().upper()
        if reason_enum not in _CANCEL_REASONS:
            reason_enum = "OTHER"
        variables: dict[str, Any] = {
            "orderId": f"gid://shopify/Order/{order_id}",
            "reason": reason_enum,
            "restock": restock,
            "notifyCustomer": email,
            "refundMethod": {"originalPaymentMethodsRefund": True} if refund else None,
        }
        async with httpx.AsyncClient() as client:
            data = await self._graphql(client, _ORDER_CANCEL_MUTATION, variables)
            errors = data["orderCancel"]["orderCancelUserErrors"]
            if errors:
                raise ShopifyRejected(f"order_cancel_failed: {errors}")
            for attempt in range(_CANCEL_POLL_ATTEMPTS):
                response = await client.get(
                    f"{self._base_url}/orders/{order_id}.json",
                    headers=self._headers(),
                    timeout=15,
                )
                response.raise_for_status()
                order: dict[str, Any] = response.json()["order"]
                if order.get("cancelled_at"):
                    return order
                if attempt < _CANCEL_POLL_ATTEMPTS - 1:
                    await asyncio.sleep(_CANCEL_POLL_SECONDS)
            # El job sigue en curso: se devuelve el estado actual (cancelled=False)
            # para no afirmar al cliente algo que Shopify aún no confirmó.
            return order

    async def update_shipping_address(
        self,
        order_id: int,
        *,
        address1: str,
        address2: str | None = None,
        city: str,
        province: str,
        country: str | None,
        zip_code: str,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> dict[str, Any]:
        """Actualiza la dirección de envío de un pedido. Acción L3.

        `country` puede llegar None: la resolución determinista (conservar el del
        pedido / default del tenant) la hace el adapter; aquí solo lo mandamos si
        existe. Si es None no tocamos el país (Shopify conserva el actual).
        """
        shipping_address: dict[str, Any] = {
            "address1": address1,
            # Siempre se envía: si el cambio no trae address2, se limpia la anterior
            # (no debe quedar el piso de la dirección vieja).
            "address2": address2 or "",
            "city": city,
            "province": province,
            "zip": zip_code,
        }
        # Shopify quiere country_code (ISO-2) cuando se puede resolver; si no, el
        # nombre original como best-effort.
        iso2 = _country_to_iso2(country) if country else None
        if iso2:
            shipping_address["country_code"] = iso2
        elif country:
            shipping_address["country"] = country
        if first_name:
            shipping_address["first_name"] = first_name
        if last_name:
            shipping_address["last_name"] = last_name
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self._base_url}/orders/{order_id}.json",
                headers=self._headers(),
                json={"order": {"id": order_id, "shipping_address": shipping_address}},
                timeout=15,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # Un 4xx es Shopify rechazando el cambio; un 5xx no dice si se guardó.
                if exc.response.is_client_error:
                    raise ShopifyRejected(f"address_update_rejected: {exc}") from exc
                raise
            return response.json()["order"]  # type: ignore[no-any-return]

    async def _get_transactions(
        self, client: httpx.AsyncClient, order_id: int
    ) -> list[dict[str, Any]]:
        response = await client.get(
            f"{self._base_url}/orders/{order_id}/transactions.json",
            headers=self._headers(),
            timeout=15,
        )
        response.raise_for_status()
        return response.json()["transactions"]  # type: ignore[no-any-return]

    async def get_refundable_balance(self, order_id: int) -> RefundableBalance:
        """Lo que queda por reembolsar del pedido, en la moneda en que pagó el cliente."""
        async with httpx.AsyncClient() as client:
            return refundable_balance(await self._get_transactions(client, order_id))

    async def get_order_snapshot(self, order_id: int) -> OrderSnapshot:
        """Envío, cancelación, dirección y transacciones del pedido en una lectura.

        GraphQL porque REST no expone `manualPaymentGateway`, que distingue una
        pasarela que devuelve el dinero de una manual donde Shopify solo lo apunta.
        """
        async with httpx.AsyncClient() as client:
            data = await self._graphql(
                client, _ORDER_SNAPSHOT_QUERY, {"id": f"gid://shopify/Order/{order_id}"}
            )
        if data.get("order") is None:
            raise ShopifyActionError(f"order_not_found: {order_id}")
        return order_snapshot_from_graphql(data["order"])

    async def refund_partial(
        self,
        order_id: int,
        *,
        amount: Decimal,
        note: str = "",
        idempotency_key: str,
    ) -> IssuedRefund:
        """Crea un reembolso parcial en un pedido. Acción L3.

        Moneda y tope salen de las transacciones del pedido, no de quien llama: un
        importe por encima de lo que queda por reembolsar se rechaza sin llamar a
        Shopify. La transacción de reembolso cuelga (`parentId`) de la de cobro
        (`sale`/`capture`) y usa su mismo gateway: sin padre el reembolso de un pedido
        cobrado se rechaza.

        GraphQL `refundCreate` con `@idempotent`: en 2026-04 la clave es obligatoria y,
        durante 24 h, repetir la misma petición devuelve el reembolso original en vez de
        crear otro. La nota lleva `refund_marker(idempotency_key)` para encontrarlo
        después (`find_refund`), pasadas las 24 h incluso.
        """
        order_gid = f"gid://shopify/Order/{order_id}"
        async with httpx.AsyncClient() as client:
            try:
                transactions = await self._get_transactions(client, order_id)
                balance = refundable_balance(transactions)
                balance.require(amount)
            except ShopifyActionError as exc:
                # Antes de `refundCreate`: el reembolso no llegó a pedirse.
                raise ShopifyRejected(str(exc)) from exc
            except httpx.HTTPError as exc:
                raise ShopifyRejected(f"{type(exc).__name__}: {exc}") from exc
            parent = _successful(transactions, _PAYMENT_KINDS)[-1]
            refund_input = {
                "orderId": order_gid,
                "currency": balance.currency,
                "note": f"{note} {refund_marker(idempotency_key)}".strip(),
                "transactions": [
                    {
                        "orderId": order_gid,
                        "parentId": f"gid://shopify/OrderTransaction/{parent['id']}",
                        "amount": str(amount),
                        "gateway": parent.get("gateway") or "",
                        "kind": "REFUND",
                    }
                ],
            }
            data = await self._idempotent_graphql(
                client,
                _REFUND_CREATE_MUTATION,
                {"input": refund_input, "idempotencyKey": idempotency_key},
            )
        result = data["refundCreate"]
        if result["userErrors"]:
            raise ShopifyRejected(f"refund_create_failed: {result['userErrors']}")
        return IssuedRefund(
            refund_id=int(result["refund"]["legacyResourceId"]),
            amount=amount,
            currency=balance.currency,
        )

    async def find_refund(self, order_id: int, idempotency_key: str) -> MarkedRefund | None:
        """El reembolso que creó `refund_partial` con esta clave, o None si no existe."""
        marker = refund_marker(idempotency_key)
        async with httpx.AsyncClient() as client:
            data = await self._graphql(
                client, _ORDER_REFUNDS_QUERY, {"id": f"gid://shopify/Order/{order_id}"}
            )
        if data.get("order") is None:
            raise ShopifyActionError(f"order_not_found: {order_id}")
        for refund in data["order"]["refunds"]:
            if marker in (refund.get("note") or ""):
                money = refund["totalRefundedSet"]["presentmentMoney"]
                return MarkedRefund(
                    refund_id=int(refund["legacyResourceId"]),
                    amount=Decimal(str(money["amount"])),
                    currency=str(money["currencyCode"]),
                    transactions=tuple(
                        snapshot_transaction(t) for t in refund["transactions"]["nodes"]
                    ),
                )
        return None

    async def _idempotent_graphql(
        self, client: httpx.AsyncClient, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        """Una mutación con `@idempotent`. Ante un corte de red o un 5xx no se sabe si
        llegó: se repite con la misma clave y Shopify devuelve el resultado original."""
        for attempt in range(1, _IDEMPOTENT_ATTEMPTS + 1):
            try:
                return await self._graphql(client, query, variables)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 or attempt == _IDEMPOTENT_ATTEMPTS:
                    raise
            except httpx.TransportError:
                if attempt == _IDEMPOTENT_ATTEMPTS:
                    raise
            logger.warning("shopify.idempotent_retry attempt=%d", attempt)
            await asyncio.sleep(_IDEMPOTENT_RETRY_SECONDS * attempt)
        raise AssertionError("unreachable")

    async def _graphql(
        self, client: httpx.AsyncClient, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        response = await client.post(
            f"{self._base_url}/graphql.json",
            headers=self._headers(),
            json={"query": query, "variables": variables},
            timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("errors"):
            raise ShopifyActionError(f"graphql_errors: {body['errors']}")
        return body["data"]  # type: ignore[no-any-return]

    async def start_return(
        self,
        order_id: int,
        *,
        line_item_id: int,
        quantity: int,
        reason: str = "other",
    ) -> dict[str, Any]:
        """Inicia la devolución de un artículo. Acción L3.

        Returns solo existe en GraphQL (`returnCreate`; no hay recurso REST). La
        devolución se hace sobre el *fulfillment line item* → se busca el del
        `line_item_id` entre los returnable fulfillments del pedido (solo artículos
        ya enviados y aún no devueltos). El motivo se mapea a una definición de la
        librería de Shopify (`returnReasonDefinitionId`) + `returnReasonNote` libre.
        Scopes: `read_returns` + `write_returns`.
        Devuelve `{"id": int, "status": str, "name": str}`.
        """
        order_gid = f"gid://shopify/Order/{order_id}"
        line_item_gid = f"gid://shopify/LineItem/{line_item_id}"
        async with httpx.AsyncClient() as client:
            data = await self._graphql(client, _RETURNABLE_QUERY, {"orderId": order_gid})
            match = None
            for fulfillment in data["returnableFulfillments"]["nodes"]:
                for item in fulfillment["returnableFulfillmentLineItems"]["nodes"]:
                    if item["fulfillmentLineItem"]["lineItem"]["id"] == line_item_gid:
                        match = item
                        break
                if match:
                    break
            if match is None:
                raise ShopifyActionError("line_item_not_returnable")
            if quantity > int(match["quantity"]):
                raise ShopifyActionError("return_quantity_exceeds_returnable")

            handle = return_reason_handle(reason)
            reasons = await self._graphql(
                client, _RETURN_REASON_QUERY, {"handles": [handle, _FALLBACK_REASON_HANDLE]}
            )
            ids = {n["handle"]: n["id"] for n in reasons["returnReasonDefinitions"]["nodes"]}
            reason_id = ids.get(handle) or ids.get(_FALLBACK_REASON_HANDLE)
            if reason_id is None:
                raise ShopifyActionError("return_reason_definition_not_found")
            data = await self._graphql(
                client,
                _RETURN_CREATE_MUTATION,
                {
                    "input": {
                        "orderId": order_gid,
                        "returnLineItems": [
                            {
                                "fulfillmentLineItemId": match["fulfillmentLineItem"]["id"],
                                "quantity": quantity,
                                # Shopify exige motivo: `returnReason` (enum) está
                                # deprecado → definición de su librería + nota libre.
                                "returnReasonDefinitionId": reason_id,
                                "returnReasonNote": reason[:255],
                            }
                        ],
                    }
                },
            )
            result = data["returnCreate"]
            if result["userErrors"]:
                raise ShopifyActionError(f"return_create_failed: {result['userErrors']}")
            ret = result["return"]
            return {
                "id": int(str(ret["id"]).rsplit("/", 1)[-1]),
                "status": str(ret["status"]).lower(),
                "name": ret.get("name"),
            }


class ShopifyActionError(RuntimeError):
    """Shopify no permite la acción con el estado actual del pedido."""


class ShopifyRejected(ShopifyActionError, MutationNotApplied):
    """La mutación no se aplicó: Shopify la rechazó o no llegó a enviarse."""


_PAYMENT_KINDS = ("sale", "capture")


def _successful(transactions: list[dict[str, Any]], kinds: tuple[str, ...]) -> list[dict[str, Any]]:
    return [t for t in transactions if t.get("kind") in kinds and t.get("status") == "success"]


@dataclass(frozen=True)
class RefundableBalance:
    """Lo que queda por reembolsar de un pedido, en la moneda en que pagó el cliente.

    Las transacciones de Shopify van en la moneda de presentación (la del cliente con
    Shopify Markets), así que moneda y tope salen de ellas, nunca del input del LLM.
    """

    captured: Decimal
    refunded: Decimal
    currency: str

    @property
    def remaining(self) -> Decimal:
        return self.captured - self.refunded

    def require(self, amount: Decimal) -> None:
        if amount <= 0:
            raise ShopifyActionError(f"refund_amount_not_positive: {amount}")
        if amount > self.remaining:
            raise ShopifyActionError(
                f"refund_amount_exceeds_refundable: se pidió reembolsar {amount} "
                f"{self.currency} y solo quedan {self.remaining} {self.currency} "
                f"(cobrado {self.captured}, ya reembolsado {self.refunded})"
            )


@dataclass(frozen=True)
class IssuedRefund:
    refund_id: int | None
    amount: Decimal
    currency: str


def refund_marker(idempotency_key: str) -> str:
    """Marca en la nota del reembolso (solo la ve el staff) que lo ata a su ejecución."""
    return f"[auyan:{idempotency_key}]"


def refundable_balance(transactions: list[dict[str, Any]]) -> RefundableBalance:
    """Cobrado menos reembolsado, a partir de las transacciones exitosas del pedido."""
    payments = _successful(transactions, _PAYMENT_KINDS)
    if not payments:
        raise ShopifyActionError("order_has_no_refundable_payment")
    refunds = _successful(transactions, ("refund",))
    currencies = {t.get("currency") for t in payments + refunds}
    if len(currencies) != 1 or None in currencies:
        raise ShopifyActionError(f"order_transactions_currency_ambiguous: {currencies}")
    return RefundableBalance(
        captured=sum((Decimal(str(t["amount"])) for t in payments), Decimal(0)),
        refunded=sum((Decimal(str(t["amount"])) for t in refunds), Decimal(0)),
        currency=str(currencies.pop()),
    )


RefundMode = Literal["automatic", "manual"]

# Fulfillments que no cuentan como envío: cancelados o fallidos.
_INACTIVE_FULFILLMENT = frozenset({"cancelled", "error", "failure"})
# `displayFulfillmentStatus` de un pedido que ya salió, entero o en parte.
_SHIPPED_DISPLAY = frozenset({"fulfilled", "partially_fulfilled"})


@dataclass(frozen=True)
class RefundRoute:
    """Por dónde vuelve el dinero si se reembolsa el pedido.

    `automatic`: todos los cobros son de una pasarela que devuelve el dinero al
    reembolsar en Shopify. `manual`: algún cobro es de pasarela manual
    (transferencia, contra reembolso, Bizum fuera de Shopify), donde Shopify solo
    apunta el reembolso, o no hay cobro registrado y no se puede saber si el
    cliente pagó por fuera. En ese caso devuelve la tienda.
    """

    mode: RefundMode
    gateway: str | None


@dataclass(frozen=True)
class SnapshotTransaction:
    id: str
    kind: str  # sale, capture, authorization, refund, void…
    status: str  # success, pending, failure, error, awaiting_response, unknown
    gateway: str | None
    manual_gateway: bool
    error_code: str | None


@dataclass(frozen=True)
class MarkedRefund:
    """Un reembolso del pedido encontrado por su `refund_marker`."""

    refund_id: int
    amount: Decimal
    currency: str
    transactions: tuple[SnapshotTransaction, ...]


@dataclass(frozen=True)
class SnapshotFulfillment:
    status: str
    tracking_numbers: tuple[str, ...]

    @property
    def active(self) -> bool:
        return self.status not in _INACTIVE_FULFILLMENT


@dataclass(frozen=True)
class OrderSnapshot:
    """Lo que decide si una L3 puede tocar un pedido y cómo acabó la acción."""

    order_id: int
    name: str  # número visible, "#1431"
    cancelled: bool
    fulfillment_status: str
    fulfillments: tuple[SnapshotFulfillment, ...]
    transactions: tuple[SnapshotTransaction, ...]
    shipping_address: dict[str, str | None]

    @property
    def shipped(self) -> bool:
        """Shopify lo da por enviado o algún envío vivo lleva tracking. No garantiza
        lo contrario: muchas tiendas preparan y etiquetan fuera de Shopify."""
        return self.fulfillment_status in _SHIPPED_DISPLAY or any(
            f.active and f.tracking_numbers for f in self.fulfillments
        )

    @property
    def has_active_fulfillment(self) -> bool:
        return any(f.active for f in self.fulfillments)

    @property
    def payments(self) -> tuple[SnapshotTransaction, ...]:
        return tuple(
            t for t in self.transactions if t.kind in _PAYMENT_KINDS and t.status == "success"
        )

    @property
    def paid(self) -> bool:
        return bool(self.payments)

    @property
    def refund_route(self) -> RefundRoute:
        payments = self.payments
        manual = [t for t in payments if t.manual_gateway]
        if payments and not manual:
            return RefundRoute(mode="automatic", gateway=payments[-1].gateway)
        return RefundRoute(mode="manual", gateway=manual[-1].gateway if manual else None)

    def refunds_since(self, before: OrderSnapshot) -> tuple[SnapshotTransaction, ...]:
        """Transacciones de reembolso que no estaban en `before`."""
        seen = {t.id for t in before.transactions}
        return tuple(t for t in self.transactions if t.kind == "refund" and t.id not in seen)


def snapshot_transaction(t: dict[str, Any]) -> SnapshotTransaction:
    """Una `OrderTransaction` de GraphQL. Enums de Shopify a minúsculas."""
    return SnapshotTransaction(
        id=str(t["id"]),
        kind=str(t.get("kind") or "").lower(),
        status=str(t.get("status") or "").lower(),
        gateway=t.get("gateway") or None,
        manual_gateway=bool(t.get("manualPaymentGateway")),
        error_code=t.get("errorCode") or None,
    )


def order_snapshot_from_graphql(node: dict[str, Any]) -> OrderSnapshot:
    """Parsea el `order` de `_ORDER_SNAPSHOT_QUERY`. Enums de Shopify a minúsculas."""
    address = node.get("shippingAddress") or {}
    return OrderSnapshot(
        order_id=int(str(node["id"]).rsplit("/", 1)[-1]),
        name=str(node.get("name") or ""),
        cancelled=node.get("cancelledAt") is not None,
        fulfillment_status=str(node.get("displayFulfillmentStatus") or "").lower(),
        fulfillments=tuple(
            SnapshotFulfillment(
                status=str(f.get("status") or "").lower(),
                tracking_numbers=tuple(
                    str(t["number"]) for t in f.get("trackingInfo") or [] if t.get("number")
                ),
            )
            for f in node.get("fulfillments") or []
        ),
        transactions=tuple(snapshot_transaction(t) for t in node.get("transactions") or []),
        shipping_address={
            key: address.get(key) for key in ("address1", "address2", "city", "zip", "country")
        },
    )


# Motivo libre del agente → handle de la librería de motivos de Shopify.
_REASON_HANDLES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("small", "pequeñ", "corto", "estrech"), "too-small"),
    (("large", "big", "grande", "largo", "ancho"), "too-big"),
    (
        ("defect", "damag", "broken", "roto", "rota", "dañad", "mancha", "tara"),
        "damaged-or-defective",
    ),
    (("wrong", "equivocad", "incorrect"), "received-the-wrong-item"),
    (("described", "descri", "different", "distint"), "item-not-as-described"),
    (("unwanted", "changed", "mind", "no lo quiero", "arrepent", "cambi"), "changed-my-mind"),
    (("style", "estilo"), "style"),
    (("color", "colour"), "color"),
    (("late", "tarde", "retras"), "arrived-late"),
)
_FALLBACK_REASON_HANDLE = "other-reason"


def return_reason_handle(reason: str) -> str:
    """Handle de la librería de motivos de devolución para un motivo en texto libre."""
    text = reason.strip().lower().replace("_", " ")
    for needles, handle in _REASON_HANDLES:
        if any(n in text for n in needles):
            return handle
    return _FALLBACK_REASON_HANDLE


_CANCEL_REASONS = frozenset({"CUSTOMER", "DECLINED", "FRAUD", "INVENTORY", "STAFF", "OTHER"})
_CANCEL_POLL_ATTEMPTS = 8
_CANCEL_POLL_SECONDS = 1.0

_ORDER_CANCEL_MUTATION = """
mutation OrderCancel(
  $orderId: ID!, $reason: OrderCancelReason!, $restock: Boolean!,
  $notifyCustomer: Boolean, $refundMethod: OrderCancelRefundMethodInput
) {
  orderCancel(
    orderId: $orderId, reason: $reason, restock: $restock,
    notifyCustomer: $notifyCustomer, refundMethod: $refundMethod
  ) {
    job { id done }
    orderCancelUserErrors { field message code }
  }
}
"""

_IDEMPOTENT_ATTEMPTS = 3
_IDEMPOTENT_RETRY_SECONDS = 1.0

_REFUND_CREATE_MUTATION = """
mutation RefundCreate($input: RefundInput!, $idempotencyKey: String!) {
  refundCreate(input: $input) @idempotent(key: $idempotencyKey) {
    refund { id legacyResourceId }
    userErrors { field message }
  }
}
"""

_ORDER_REFUNDS_QUERY = """
query OrderRefunds($id: ID!) {
  order(id: $id) {
    refunds(first: 50) {
      legacyResourceId
      note
      totalRefundedSet { presentmentMoney { amount currencyCode } }
      transactions(first: 10) {
        nodes { id kind status gateway manualPaymentGateway errorCode }
      }
    }
  }
}
"""

_ORDER_SNAPSHOT_QUERY = """
query OrderSnapshot($id: ID!) {
  order(id: $id) {
    id
    name
    cancelledAt
    displayFulfillmentStatus
    shippingAddress { address1 address2 city zip country }
    fulfillments(first: 20) { status trackingInfo(first: 5) { number } }
    transactions(first: 100) { id kind status gateway manualPaymentGateway errorCode }
  }
}
"""

_RETURN_REASON_QUERY = """
query ReturnReasons($handles: [String!]) {
  returnReasonDefinitions(handles: $handles, first: 5) { nodes { id handle } }
}
"""

_RETURNABLE_QUERY = """
query Returnable($orderId: ID!) {
  returnableFulfillments(orderId: $orderId, first: 20) {
    nodes {
      returnableFulfillmentLineItems(first: 100) {
        nodes {
          quantity
          fulfillmentLineItem { id lineItem { id } }
        }
      }
    }
  }
}
"""

_RETURN_CREATE_MUTATION = """
mutation ReturnCreate($input: ReturnInput!) {
  returnCreate(returnInput: $input) {
    return { id name status }
    userErrors { field message }
  }
}
"""


# ─── Adapter stateless — implementa CommerceProvider ──────────────────────────


@IntegrationRegistry.register(kind="commerce", provider="shopify")
class ShopifyAdapter:
    """CommerceProvider stateless para Shopify.

    Crea un ShopifyClient por llamada con un access_token YA VÁLIDO. Quien construye
    el IntegrationContext (router connect, build_skill_context del agente) debe llamar
    `ensure_shopify_access_token` antes — el adapter no refresca; eso requeriría conn
    + lógica que ensucia los 10+ métodos del adapter.

    Credentials esperadas:
        - domain: shop.myshopify.com
        - access_token: token válido (24h max), obtenido vía Client Credentials Grant

    Compatibilidad legacy: si viene 'token' en lugar de 'access_token' (Custom App
    legacy pre-2026), se acepta. Esos tenants se migran al nuevo flow cuando
    re-conectan vía el wizard.
    """

    def _client(self, ctx: IntegrationContext) -> ShopifyClient:
        creds = ctx.credentials
        token = creds.get("access_token") or creds.get("token")
        if not token:
            raise ValueError("shopify credentials missing access_token / token")
        return ShopifyClient(creds["domain"], token)

    # ── CommerceProvider protocol ──────────────────────────────────────────────

    async def get_order(self, ctx: IntegrationContext, order_id: str) -> dict[str, Any]:
        return await self._client(ctx).get_order(int(order_id))

    async def search_orders_by_email(
        self, ctx: IntegrationContext, email: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        return await self._client(ctx).get_orders_by_email(email, limit=limit)

    async def search_orders_by_phone(
        self, ctx: IntegrationContext, phone: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Pedidos del customer de Shopify con ese teléfono E.164 ([] si no hay customer).

        Shopify no filtra pedidos por teléfono: se busca el customer y se leen los suyos.
        """
        client = self._client(ctx)
        customer = await client.get_customer_by_phone(phone)
        if customer is None:
            return []
        return await client.get_orders_by_customer_id(customer["id"], limit=limit)

    # ── Métodos extendidos usados por las skills ───────────────────────────────

    async def _resolve_order_id(self, ctx: IntegrationContext, order_ref: int) -> int:
        """Resuelve el número de pedido visible para el cliente (p.ej. 1181) al
        order_id interno de Shopify (p.ej. 7133866033432).

        El cliente y el LLM solo conocen el número visible (#1181), pero los
        endpoints de mutación de Shopify exigen el id interno. Si order_ref ya es
        un id interno (ningún pedido tiene ese 'name'), se devuelve tal cual, así
        que la resolución es segura tanto si llega el número visible como el id.
        """
        found = await self._client(ctx).get_order_by_name(str(order_ref))
        if found and found.get("id"):
            return int(found["id"])
        return order_ref

    async def get_order_by_name(
        self, ctx: IntegrationContext, order_name: str
    ) -> dict[str, Any] | None:
        return await self._client(ctx).get_order_by_name(order_name)

    async def get_orders_by_customer_id(
        self, ctx: IntegrationContext, customer_id: int, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        return await self._client(ctx).get_orders_by_customer_id(customer_id, limit=limit)

    async def search_products(
        self, ctx: IntegrationContext, query: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        return await self._client(ctx).search_products(query, limit=limit)

    async def get_shop_currency(self, ctx: IntegrationContext) -> str:
        return await self._client(ctx).get_shop_currency()

    async def get_policies(self, ctx: IntegrationContext) -> list[dict[str, Any]]:
        return await self._client(ctx).get_policies()

    async def add_order_note(
        self, ctx: IntegrationContext, order_id: int, note: str
    ) -> dict[str, Any]:
        order_id = await self._resolve_order_id(ctx, order_id)
        return await self._client(ctx).add_order_note(order_id, note)

    async def tag_order(
        self, ctx: IntegrationContext, order_id: int, tags_to_add: list[str]
    ) -> dict[str, Any]:
        order_id = await self._resolve_order_id(ctx, order_id)
        return await self._client(ctx).tag_order(order_id, tags_to_add)

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
        order_id = await self._resolve_order_id(ctx, order_id)
        return await self._client(ctx).cancel_order(
            order_id, reason=reason, email=email, refund=refund, restock=restock
        )

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
        """Actualiza la dirección de envío conservando el país de forma determinista.

        El país NO lo inventa el LLM: si no llega `country` (cambio doméstico, lo
        normal), se conserva el del pedido actual; si el pedido no lo tuviera, se
        cae al `default_country_code` de la config del tenant. Solo se manda un país
        distinto cuando el cliente cambia de país explícitamente (`country` no nulo).
        """
        client = self._client(ctx)
        # Resolver el id interno y, de paso, quedarnos con el pedido para leer su país.
        found = await client.get_order_by_name(str(order_id))
        if found and found.get("id"):
            resolved_id = int(found["id"])
            order: dict[str, Any] | None = found
        else:
            resolved_id = order_id
            order = None

        resolved_country = country
        if resolved_country is None:
            if order is None:
                order = await client.get_order(resolved_id)
            shipping = (order or {}).get("shipping_address") or {}
            resolved_country = shipping.get("country_code") or shipping.get("country")
        if resolved_country is None:
            resolved_country = (ctx.config or {}).get("default_country_code")

        return await client.update_shipping_address(
            resolved_id,
            address1=address1,
            address2=address2,
            city=city,
            province=province,
            country=resolved_country,
            zip_code=zip_code,
            first_name=first_name,
            last_name=last_name,
        )

    async def get_order_snapshot(self, ctx: IntegrationContext, order_id: int) -> OrderSnapshot:
        order_id = await self._resolve_order_id(ctx, order_id)
        return await self._client(ctx).get_order_snapshot(order_id)

    async def get_refundable_balance(
        self, ctx: IntegrationContext, order_id: int
    ) -> RefundableBalance:
        order_id = await self._resolve_order_id(ctx, order_id)
        return await self._client(ctx).get_refundable_balance(order_id)

    async def refund_partial(
        self,
        ctx: IntegrationContext,
        order_id: int,
        *,
        amount: Decimal,
        note: str = "",
        idempotency_key: str,
    ) -> IssuedRefund:
        order_id = await self._resolve_order_id(ctx, order_id)
        return await self._client(ctx).refund_partial(
            order_id, amount=amount, note=note, idempotency_key=idempotency_key
        )

    async def find_refund(
        self, ctx: IntegrationContext, order_id: int, idempotency_key: str
    ) -> MarkedRefund | None:
        order_id = await self._resolve_order_id(ctx, order_id)
        return await self._client(ctx).find_refund(order_id, idempotency_key)

    async def start_return(
        self,
        ctx: IntegrationContext,
        order_id: int,
        *,
        line_item_id: int,
        quantity: int,
        reason: str = "other",
    ) -> dict[str, Any]:
        order_id = await self._resolve_order_id(ctx, order_id)
        return await self._client(ctx).start_return(
            order_id, line_item_id=line_item_id, quantity=quantity, reason=reason
        )


# Satisface el type-checker: ShopifyAdapter implementa CommerceProvider structuralmente.
_: CommerceProvider = ShopifyAdapter()  # type: ignore[assignment]
