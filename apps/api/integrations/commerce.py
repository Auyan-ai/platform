"""Contrato de comercio común a todos los proveedores (ADR 0016).

Las skills, el gate de identidad, el simulador y la demo hablan con la tienda solo a través
de `CommerceAdapter`. Cada proveedor (Shopify, WooCommerce…) es un adapter que se registra en
`IntegrationRegistry` con `kind="commerce"` y declara sus `capabilities`.

La forma canónica del pedido es la forma REST de la Admin API de Shopify (`orders.json`):
`id`, `name`, `email`, `phone`, `financial_status`, `fulfillment_status`, `fulfillments`,
`line_items`, `shipping_address`, `customer` y los `*_set.presentment_money`. Es la que leen
`get_order_status`, `list_my_orders` y `order_claims`, así que cada adapter la produce en su
frontera. Los productos siguen igual la forma de `products.json`.

Los tipos de aquí deciden una L3 sin depender del proveedor: `OrderSnapshot` (envío,
cancelación, transacciones), `RefundRoute` (por dónde vuelve el dinero), `RefundableBalance`
y los resultados de reembolsos y devoluciones.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.services.returns import (
    ExchangeVariant,
    ReturnableOrder,
    ReturnCalculation,
    ReturnPlan,
)


class CommerceCapability(StrEnum):
    """Lo que un proveedor sabe hacer. Cada skill de comercio exige una."""

    ORDER_READ = "order_read"
    PRODUCT_READ = "product_read"
    POLICIES = "policies"
    ORDER_NOTES = "order_notes"
    ORDER_TAGS = "order_tags"
    CANCEL = "cancel"
    SHIPPING_ADDRESS = "shipping_address"
    REFUNDS = "refunds"
    RETURNS = "returns"
    EXCHANGES = "exchanges"


ALL_CAPABILITIES = frozenset(CommerceCapability)


class CommerceActionError(RuntimeError):
    """El proveedor no permite la acción con el estado actual del pedido."""


# Transacciones que son un cobro al cliente.
PAYMENT_KINDS = ("sale", "capture")
# Fulfillments que no cuentan como envío: cancelados o fallidos.
_INACTIVE_FULFILLMENT = frozenset({"cancelled", "error", "failure"})
# Estado de envío de un pedido que ya salió, entero o en parte.
_SHIPPED_DISPLAY = frozenset({"fulfilled", "partially_fulfilled"})


@dataclass(frozen=True)
class RefundableBalance:
    """Lo que queda por reembolsar de un pedido, en la moneda en que pagó el cliente.

    Moneda y tope salen de las transacciones del pedido, nunca del input del LLM.
    """

    captured: Decimal
    refunded: Decimal
    currency: str

    @property
    def remaining(self) -> Decimal:
        return self.captured - self.refunded

    def require(self, amount: Decimal) -> None:
        if amount <= 0:
            raise CommerceActionError(f"refund_amount_not_positive: {amount}")
        if amount > self.remaining:
            raise CommerceActionError(
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


RefundMode = Literal["automatic", "manual"]


@dataclass(frozen=True)
class RefundRoute:
    """Por dónde vuelve el dinero si se reembolsa el pedido.

    `automatic`: todos los cobros son de una pasarela que devuelve el dinero al reembolsar
    en la tienda. `manual`: algún cobro es de pasarela manual (transferencia, contra
    reembolso, Bizum fuera de la tienda), donde la tienda solo apunta el reembolso, o no hay
    cobro registrado y no se puede saber si el cliente pagó por fuera. En ese caso devuelve
    la tienda.
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
        """La tienda lo da por enviado o algún envío vivo lleva tracking. No garantiza lo
        contrario: muchas tiendas preparan y etiquetan fuera de la plataforma."""
        return self.fulfillment_status in _SHIPPED_DISPLAY or any(
            f.active and f.tracking_numbers for f in self.fulfillments
        )

    @property
    def has_active_fulfillment(self) -> bool:
        return any(f.active for f in self.fulfillments)

    @property
    def payments(self) -> tuple[SnapshotTransaction, ...]:
        return tuple(
            t for t in self.transactions if t.kind in PAYMENT_KINDS and t.status == "success"
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


# Shopify rechaza un `country` en texto libre que no sea el nombre en inglés exacto
# ("España" → 422) y WooCommerce guarda el código ISO-3166-1 alfa-2. El agente recoge el
# país tal como lo escribe el cliente (normalmente en español). Auyan es ES-first:
# España y los destinos de envío habituales.
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


def country_to_iso2(country: str) -> str | None:
    """Resuelve un país en texto libre a su código ISO-2, o None si no se reconoce.

    Acepta un código de 2 letras tal cual (lo valida la tienda). Para nombres,
    mapea español/inglés comunes. Si devuelve None, el adapter manda el texto
    original (best-effort).
    """
    c = country.strip()
    if len(c) == 2 and c.isalpha():
        return c.upper()
    return _COUNTRY_TO_ISO2.get(c.lower())


@dataclass(frozen=True)
class CreatedReturn:
    return_id: int
    name: str
    status: str  # open, requested, closed, declined, canceled
    reason_handle: str


class CommerceAdapter(Protocol):
    """Superficie de la tienda que usan las skills. Stateless: las credenciales llegan en
    el `IntegrationContext` de cada llamada.

    `order_id` es el número visible del pedido o el id interno: el adapter resuelve uno al
    otro. Un método fuera de `capabilities` puede lanzar: la skill que lo usa no se ofrece
    al LLM y `execute_skill` la rechaza antes de ejecutarla.
    """

    capabilities: frozenset[CommerceCapability]
    # Nombre de la plataforma en los textos para el equipo ("Shopify", "WooCommerce").
    platform_name: str

    # ── order_read ─────────────────────────────────────────────────────────────
    async def get_order(self, ctx: IntegrationContext, order_id: str) -> dict[str, Any]: ...

    async def get_order_by_name(
        self, ctx: IntegrationContext, order_name: str
    ) -> dict[str, Any] | None: ...

    async def search_orders_by_email(
        self, ctx: IntegrationContext, email: str, *, limit: int = 10
    ) -> list[dict[str, Any]]: ...

    async def search_orders_by_phone(
        self, ctx: IntegrationContext, phone: str, *, limit: int = 10
    ) -> list[dict[str, Any]]: ...

    async def get_order_snapshot(self, ctx: IntegrationContext, order_id: int) -> OrderSnapshot: ...

    # ── product_read ───────────────────────────────────────────────────────────
    async def search_products(
        self, ctx: IntegrationContext, query: str, *, limit: int = 10
    ) -> list[dict[str, Any]]: ...

    async def get_shop_currency(self, ctx: IntegrationContext) -> str: ...

    # ── policies ───────────────────────────────────────────────────────────────
    async def get_policies(self, ctx: IntegrationContext) -> list[dict[str, Any]]: ...

    # ── order_notes / order_tags ───────────────────────────────────────────────
    async def add_order_note(
        self, ctx: IntegrationContext, order_id: int, note: str
    ) -> dict[str, Any]: ...

    async def append_order_note(
        self, ctx: IntegrationContext, order_id: int, text: str
    ) -> None: ...

    async def tag_order(
        self, ctx: IntegrationContext, order_id: int, tags_to_add: list[str]
    ) -> dict[str, Any]: ...

    # ── cancel / shipping_address ──────────────────────────────────────────────
    async def cancel_order(
        self,
        ctx: IntegrationContext,
        order_id: int,
        *,
        reason: str = "customer",
        email: bool = True,
        refund: bool,
        restock: bool,
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...

    # ── refunds ────────────────────────────────────────────────────────────────
    async def get_refundable_balance(
        self, ctx: IntegrationContext, order_id: int
    ) -> RefundableBalance: ...

    async def refund_partial(
        self,
        ctx: IntegrationContext,
        order_id: int,
        *,
        amount: Decimal,
        note: str = "",
        idempotency_key: str,
    ) -> IssuedRefund: ...

    async def find_refund(
        self, ctx: IntegrationContext, order_id: int, idempotency_key: str
    ) -> MarkedRefund | None: ...

    # ── returns / exchanges ────────────────────────────────────────────────────
    async def get_returnable_order(
        self, ctx: IntegrationContext, order_id: int
    ) -> ReturnableOrder: ...

    async def get_exchange_variants(
        self, ctx: IntegrationContext, variant_ids: list[int]
    ) -> tuple[ExchangeVariant, ...]: ...

    async def calculate_return(
        self,
        ctx: IntegrationContext,
        order_id: int,
        *,
        lines: list[tuple[str, int]],
        exchange: list[tuple[int, int]],
    ) -> ReturnCalculation: ...

    async def find_return(
        self, ctx: IntegrationContext, plan: ReturnPlan
    ) -> CreatedReturn | None: ...

    async def create_return(self, ctx: IntegrationContext, plan: ReturnPlan) -> CreatedReturn: ...


def platform_name(provider: str | None) -> str:
    """Nombre de la plataforma de comercio del tenant para los textos al equipo, o "la
    tienda" si no hay proveedor o no tiene adapter registrado."""
    adapter = dict(IntegrationRegistry.list_for_kind("commerce")).get(provider or "")
    return str(adapter.platform_name) if adapter is not None else "la tienda"
