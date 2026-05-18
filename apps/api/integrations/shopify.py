"""Cliente HTTP para la Admin REST API de Shopify.

Cubre las operaciones L1 (read-only) de Sprint 6.
Las operaciones L2/L3 (write) se agregan en Sprints 9-10.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API_VERSION = "2024-10"


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
        country: str,
        zip_code: str,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> dict[str, Any]:
        """Actualiza la dirección de envío de un pedido. Acción L3."""
        shipping_address: dict[str, Any] = {
            "address1": address1,
            "city": city,
            "province": province,
            "country": country,
            "zip": zip_code,
        }
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
