"""Mock del adapter commerce para simulaciones.

`MockShopifyAdapter` es un drop-in del `ShopifyAdapter` real: implementa la misma
superficie de métodos pero devuelve respuestas predefinidas (fixtures) en vez de
llamar a la API de Shopify. Se inyecta en `SkillContext.commerce_mock` desde
`execute_skill` cuando el state tiene `simulation_mode=True`.

Las fixtures se indexan por NOMBRE DE MÉTODO del adapter (no por skill slug),
porque una skill puede hacer varias llamadas y el mock opera a nivel de método:

    {
        "get_order_by_name": {"found": true, "order_number": "#1234", ...},
        "search_orders_by_email": [{...}, {...}],
        "search_orders_by_phone": {"_error": "SHOPIFY_API_UNAVAILABLE"},
        "get_policies": [{...}]
    }

Un fixture con la clave `_error` hace que el método lance `MockShopifyError`,
para probar que el agente maneja fallos de integración correctamente.

Defaults cuando no hay fixture para un método:
- lecturas que devuelven un objeto opcional → None ("no encontrado")
- lecturas que devuelven listas → []
- escrituras (cancel/return/update/note/tag) → dict de éxito genérico
- `get_shop_currency` → None (la skill de productos falla: la moneda nunca se supone)
- `get_refundable_balance` → error `order_has_no_refundable_payment`. Un reembolso
  necesita la fixture `{"captured": "45.00", "refunded": "0", "currency": "GBP"}`;
  `refund_partial` aplica el mismo tope y la misma moneda que el adapter real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from apps.api.integrations.shopify import IssuedRefund, RefundableBalance


class MockShopifyError(Exception):
    """Error simulado de la API de Shopify. execute_skill lo captura como is_error."""


_WRITE_DEFAULT: dict[str, Any] = {"ok": True, "simulated": True}


@dataclass
class MockShopifyAdapter:
    """Implementa la superficie de ShopifyAdapter con respuestas predefinidas."""

    fixtures: dict[str, Any] = field(default_factory=dict)

    def _resolve(self, method: str, default: Any) -> Any:
        if method not in self.fixtures:
            return default
        data = self.fixtures[method]
        if isinstance(data, dict) and "_error" in data:
            raise MockShopifyError(data["_error"])
        return data

    # ── CommerceProvider protocol ──────────────────────────────────────────────

    async def get_order(self, ctx: Any, order_id: str) -> dict[str, Any] | None:
        return self._resolve("get_order", None)

    async def search_orders_by_email(
        self, ctx: Any, email: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        return self._resolve("search_orders_by_email", [])

    async def search_orders_by_phone(
        self, ctx: Any, phone: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        return self._resolve("search_orders_by_phone", [])

    # ── Métodos extendidos usados por las skills ───────────────────────────────

    async def get_order_by_name(
        self, ctx: Any, order_name: str
    ) -> dict[str, Any] | None:
        return self._resolve("get_order_by_name", None)

    async def get_orders_by_customer_id(
        self, ctx: Any, customer_id: int, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        return self._resolve("get_orders_by_customer_id", [])

    async def search_products(
        self, ctx: Any, query: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        return self._resolve("search_products", [])

    async def get_shop_currency(self, ctx: Any) -> str | None:
        return self._resolve("get_shop_currency", None)  # type: ignore[no-any-return]

    async def get_policies(self, ctx: Any) -> list[dict[str, Any]]:
        return self._resolve("get_policies", [])

    async def add_order_note(
        self, ctx: Any, order_id: int, note: str
    ) -> dict[str, Any]:
        return self._resolve("add_order_note", dict(_WRITE_DEFAULT))

    async def tag_order(
        self, ctx: Any, order_id: int, tags_to_add: list[str]
    ) -> dict[str, Any]:
        return self._resolve("tag_order", dict(_WRITE_DEFAULT))

    async def cancel_order(
        self,
        ctx: Any,
        order_id: int,
        *,
        reason: str = "customer",
        email: bool = True,
        refund: bool = False,
    ) -> dict[str, Any]:
        return self._resolve("cancel_order", dict(_WRITE_DEFAULT))

    async def update_shipping_address(
        self,
        ctx: Any,
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
        return self._resolve("update_shipping_address", dict(_WRITE_DEFAULT))

    async def get_refundable_balance(self, ctx: Any, order_id: int) -> RefundableBalance:
        data = self._resolve("get_refundable_balance", None)
        if data is None:
            raise MockShopifyError("order_has_no_refundable_payment")
        return RefundableBalance(
            captured=Decimal(str(data["captured"])),
            refunded=Decimal(str(data.get("refunded", "0"))),
            currency=data["currency"],
        )

    async def refund_partial(
        self,
        ctx: Any,
        order_id: int,
        *,
        amount: Decimal,
        note: str = "",
    ) -> IssuedRefund:
        refund = self._resolve("refund_partial", {})
        balance = await self.get_refundable_balance(ctx, order_id)
        balance.require(amount)
        return IssuedRefund(refund_id=refund.get("id"), amount=amount, currency=balance.currency)

    async def start_return(
        self,
        ctx: Any,
        order_id: int,
        *,
        line_item_id: int,
        quantity: int,
        reason: str = "other",
    ) -> dict[str, Any]:
        return self._resolve("start_return", dict(_WRITE_DEFAULT))
