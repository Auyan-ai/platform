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

import datetime as _dt
import logging
from collections import OrderedDict
from typing import Any
from uuid import UUID

import httpx
from apps.api.integrations.base import CommerceProvider, IntegrationContext
from apps.api.integrations.registry import IntegrationRegistry

logger = logging.getLogger(__name__)

_API_VERSION = "2024-10"
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
    "españa": "ES", "espana": "ES", "spain": "ES",
    "portugal": "PT",
    "francia": "FR", "france": "FR",
    "italia": "IT", "italy": "IT",
    "alemania": "DE", "germany": "DE", "deutschland": "DE",
    "andorra": "AD",
    "reino unido": "GB", "united kingdom": "GB", "uk": "GB",
    "irlanda": "IE", "ireland": "IE",
    "países bajos": "NL", "paises bajos": "NL", "holanda": "NL", "netherlands": "NL",
    "bélgica": "BE", "belgica": "BE", "belgium": "BE",
    "suiza": "CH", "switzerland": "CH",
    "estados unidos": "US", "united states": "US", "usa": "US",
    "méxico": "MX", "mexico": "MX",
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

    async def get_orders_by_email(
        self, email: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
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

    async def search_products(
        self, query: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
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

    async def get_customer_by_email(self, email: str) -> dict[str, Any] | None:
        """Busca un customer por email. Devuelve None si no existe."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/customers/search.json",
                headers=self._headers(),
                params={"query": f"email:{email}", "limit": 1},
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
        refund: bool = False,
    ) -> dict[str, Any]:
        """Cancela un pedido. Acción L3 — requiere supervisor Opus y aprobación humana."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/orders/{order_id}/cancel.json",
                headers=self._headers(),
                json={"reason": reason, "email": email, "refund": refund},
                timeout=15,
            )
            response.raise_for_status()
            return response.json()["order"]  # type: ignore[no-any-return]

    async def update_shipping_address(
        self,
        order_id: int,
        *,
        address1: str,
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
            response.raise_for_status()
            return response.json()["order"]  # type: ignore[no-any-return]

    async def refund_partial(
        self,
        order_id: int,
        *,
        amount: str,
        currency: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Crea un reembolso parcial en un pedido. Acción L3."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/orders/{order_id}/refunds.json",
                headers=self._headers(),
                json={
                    "refund": {
                        "currency": currency,
                        "note": note,
                        "transactions": [
                            {
                                "parent_id": None,
                                "amount": amount,
                                "kind": "refund",
                                "gateway": "manual",
                            }
                        ],
                    }
                },
                timeout=15,
            )
            response.raise_for_status()
            return response.json()["refund"]  # type: ignore[no-any-return]

    async def start_return(
        self,
        order_id: int,
        *,
        line_item_id: int,
        quantity: int,
        reason: str = "other",
    ) -> dict[str, Any]:
        """Inicia el proceso de devolución de un artículo. Acción L3.

        Usa la API de Returns de Shopify (REST Admin 2024-10+).
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/orders/{order_id}/returns.json",
                headers=self._headers(),
                json={
                    "return": {
                        "line_items": [
                            {
                                "line_item_id": line_item_id,
                                "quantity": quantity,
                                "return_reason_notes": reason,
                            }
                        ]
                    }
                },
                timeout=15,
            )
            response.raise_for_status()
            return response.json()["return"]  # type: ignore[no-any-return]


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

    async def get_customer_by_email(
        self, ctx: IntegrationContext, email: str
    ) -> dict[str, Any] | None:
        return await self._client(ctx).get_customer_by_email(email)

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
        refund: bool = False,
    ) -> dict[str, Any]:
        order_id = await self._resolve_order_id(ctx, order_id)
        return await self._client(ctx).cancel_order(
            order_id, reason=reason, email=email, refund=refund
        )

    async def update_shipping_address(
        self,
        ctx: IntegrationContext,
        order_id: int,
        *,
        address1: str,
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
            city=city,
            province=province,
            country=resolved_country,
            zip_code=zip_code,
            first_name=first_name,
            last_name=last_name,
        )

    async def refund_partial(
        self,
        ctx: IntegrationContext,
        order_id: int,
        *,
        amount: str,
        currency: str,
        note: str = "",
    ) -> dict[str, Any]:
        order_id = await self._resolve_order_id(ctx, order_id)
        return await self._client(ctx).refund_partial(
            order_id, amount=amount, currency=currency, note=note
        )

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
