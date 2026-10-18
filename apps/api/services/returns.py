"""Decisión y liquidación de una devolución o un cambio (ADR 0014 §4-§5).

Funciones puras: reciben la política vigente, el pedido releído de Shopify y lo que pidió
el cliente, y devuelven un `Eligible`, un `Refused` (escala al equipo) o un `Rejected`
(vuelve al LLM para que el cliente lo corrija). Nada de aquí lo decide el LLM.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from apps.api.services.media_storage import listed_attachments
from apps.api.services.returns_policy import (
    ActivePolicy,
    Fault,
    HigherPrice,
    LowerPrice,
    Money,
    Payer,
    ReturnReason,
    ShipReplacement,
)
from pydantic import BaseModel, ConfigDict, Field, computed_field

RefusalCode = Literal[
    "policy_missing",
    "order_cancelled",
    "exchanges_disabled",
    "product_excluded",
    "product_unknown",
    "delivery_date_unknown",
    "outside_window",
    "evidence_unreadable",
]
RejectionCode = Literal[
    "reason_not_in_policy",
    "item_not_returnable",
    "quantity_exceeds_returnable",
    "evidence_missing",
    "exchange_kind_not_allowed",
    "exchange_variant_unavailable",
    "exchange_price_higher",
    "refund_preference_missing",
]
# Lo que elige el cliente cuando la política le deja elegir (`refund_method = customer_choice`).
RefundPreference = Literal["original_payment", "store_credit"]
# Cómo se salda la diferencia de precio de un cambio (`none`: devolución o mismo precio).
PriceRule = Literal[
    "none", "customer_pays", "store_absorbs", "refund_difference", "store_credit", "no_refund"
]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RequestedItem(_Frozen):
    line_item_id: int
    quantity: int = Field(ge=1)


class RequestedExchange(_Frozen):
    variant_id: int
    quantity: int = Field(ge=1)


class PhotoRef(_Frozen):
    """Adjunto de imagen de un mensaje del cliente (lo abre el panel)."""

    message_id: str
    index: int


def customer_photos(history: Iterable[Mapping[str, Any]]) -> tuple[PhotoRef, ...]:
    """Imágenes que el cliente mandó en los mensajes del historial del turno."""
    return tuple(
        PhotoRef(message_id=str(m["id"]), index=i)
        for m in history
        if m.get("role") == "customer"
        for i, a in enumerate(listed_attachments(m.get("attachments")))
        if a.get("kind") == "image" or str(a.get("mime_type") or "").startswith("image/")
    )


@dataclass(frozen=True)
class Evidence:
    photos: tuple[PhotoRef, ...]
    # El canal trae los adjuntos a Auyan (mensajería). En un helpdesk se quedan allí.
    readable: bool


@dataclass(frozen=True)
class ReturnableLine:
    line_item_id: int
    fulfillment_line_item_id: str
    title: str
    returnable_quantity: int
    product_id: int | None
    # None: producto borrado o línea personalizada, sin etiquetas que mirar.
    product_tags: frozenset[str] | None
    shipped_at: datetime
    delivered_at: datetime | None


@dataclass(frozen=True)
class ReturnableOrder:
    order_id: int
    name: str
    ordered_at: datetime
    currency: str
    taxes_included: bool
    cancelled: bool
    lines: tuple[ReturnableLine, ...]

    def line(self, line_item_id: int) -> ReturnableLine | None:
        return next((ln for ln in self.lines if ln.line_item_id == line_item_id), None)


@dataclass(frozen=True)
class ExchangeVariant:
    variant_id: int
    product_id: int
    title: str
    available: bool


@dataclass(frozen=True)
class Refused:
    code: RefusalCode
    team_reason: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Rejected:
    code: RejectionCode
    detail: str


class PlanLine(_Frozen):
    line_item_id: int
    fulfillment_line_item_id: str
    title: str
    quantity: int


class PlanExchangeLine(_Frozen):
    variant_id: int
    title: str
    quantity: int


@dataclass(frozen=True)
class Eligible:
    policy_version: int
    order_id: int
    order_name: str
    currency: str
    taxes_included: bool
    reason: ReturnReason
    lines: tuple[PlanLine, ...]
    exchange_lines: tuple[PlanExchangeLine, ...]
    evidence: tuple[PhotoRef, ...]
    shipping_method: Literal["customer_ships", "store_label"]
    return_address: str | None
    shipping_payer: Payer
    fee: Money | None
    refund_days: int
    refund_as: RefundPreference
    restocking_percent: Decimal
    higher_price: HigherPrice | None
    lower_price: LowerPrice | None
    ship_replacement: ShipReplacement | None
    requires_approval: bool


Decision = Eligible | Refused | Rejected

_ANCHOR_LABEL = {"delivery": "la entrega", "shipment": "el envío", "order": "la compra"}
_FAULT_LABEL: dict[Fault, str] = {"store": "de la tienda", "customer": "del cliente"}


def _deadline(
    order: ReturnableOrder, line: ReturnableLine, active: ActivePolicy
) -> datetime | None:
    window = active.policy.window
    anchor = {
        "delivery": line.delivered_at,
        "shipment": line.shipped_at,
        "order": order.ordered_at,
    }[window.starts_at]
    return anchor + timedelta(days=window.days) if anchor else None


def evaluate_return(
    active: ActivePolicy | None,
    order: ReturnableOrder,
    *,
    reason_code: str,
    items: tuple[RequestedItem, ...],
    exchange: tuple[RequestedExchange, ...],
    variants: tuple[ExchangeVariant, ...],
    evidence: Evidence,
    now: datetime,
    refund_preference: RefundPreference | None = None,
) -> Decision:
    """Aplica la política a una petición. El orden de las comprobaciones es el de la
    tabla del ADR: primero lo que escala sin remedio, luego lo que el cliente corrige."""
    if active is None:
        return Refused(
            "policy_missing",
            "La tienda no tiene configurada su política de devoluciones y cambios: el agente "
            "no abre ninguna. Revisad el caso y configurad la política en el panel.",
        )
    policy = active.policy
    if order.cancelled:
        return Refused(
            "order_cancelled",
            f"El cliente pidió devolver o cambiar artículos de {order.name}, pero Shopify lo "
            "tiene cancelado.",
        )
    if exchange and not policy.exchanges.enabled:
        return Refused(
            "exchanges_disabled",
            f"El cliente pidió un cambio en {order.name} y la política de la tienda no "
            "admite cambios.",
        )
    reason = policy.reason(reason_code)
    if reason is None:
        codes = ", ".join(r.code for r in policy.reasons)
        return Rejected(
            "reason_not_in_policy",
            f"Motivo '{reason_code}' fuera de la política. Códigos válidos: {codes}.",
        )

    lines: list[tuple[ReturnableLine, int]] = []
    for item in items:
        line = order.line(item.line_item_id)
        if line is None:
            returnable = "; ".join(
                f"{ln.line_item_id} '{ln.title}' (máx. {ln.returnable_quantity})"
                for ln in order.lines
            )
            return Rejected(
                "item_not_returnable",
                f"El artículo {item.line_item_id} no se puede devolver (sin enviar o ya "
                f"devuelto). Devolvibles: {returnable or 'ninguno'}.",
            )
        if item.quantity > line.returnable_quantity:
            return Rejected(
                "quantity_exceeds_returnable",
                f"Del artículo {line.line_item_id} '{line.title}' se pueden devolver como "
                f"máximo {line.returnable_quantity}.",
            )
        lines.append((line, item.quantity))

    excluded = policy.excluded_product_tags
    for line, _ in lines:
        if excluded and line.product_tags is None:
            return Refused(
                "product_unknown",
                f"'{line.title}' de {order.name} no tiene producto en Shopify y la política "
                "excluye productos por etiqueta: no se puede comprobar si admite devolución.",
            )
        hit = sorted(excluded & (line.product_tags or frozenset()))
        if hit:
            return Refused(
                "product_excluded",
                f"'{line.title}' de {order.name} tiene la etiqueta {', '.join(hit)}, que la "
                "política excluye de devolución.",
            )

    for line, _ in lines:
        deadline = _deadline(order, line, active)
        if deadline is None:
            return Refused(
                "delivery_date_unknown",
                f"La política cuenta el plazo desde la entrega y Shopify no tiene fecha de "
                f"entrega de '{line.title}' ({order.name}). Comprobad la entrega con el "
                "transportista.",
            )
        if now > deadline:
            starts = _ANCHOR_LABEL[policy.window.starts_at]
            return Refused(
                "outside_window",
                f"'{line.title}' de {order.name} está fuera de plazo: {policy.window.days} días "
                f"desde {starts}, terminó el {deadline:%d/%m/%Y}.",
                {"deadline": f"{deadline:%d/%m/%Y}"},
            )

    if "photo" in reason.required_evidence:
        if not evidence.readable:
            return Refused(
                "evidence_unreadable",
                f"El motivo '{reason.label}' exige foto y este canal no trae los adjuntos a "
                f"Auyan. Revisad las fotos en el ticket de {order.name}.",
            )
        if not evidence.photos:
            return Rejected(
                "evidence_missing",
                f"El motivo '{reason.code}' exige una foto del artículo y el cliente no ha "
                "enviado ninguna imagen en esta conversación.",
            )

    exchange_lines: list[PlanExchangeLine] = []
    returned_products = {line.product_id for line, _ in lines if line.product_id is not None}
    by_id = {v.variant_id: v for v in variants}
    for wanted in exchange:
        variant = by_id.get(wanted.variant_id)
        if variant is None or not variant.available:
            return Rejected(
                "exchange_variant_unavailable",
                f"La variante {wanted.variant_id} no existe o no está disponible.",
            )
        if "product" not in policy.exchanges.kinds and variant.product_id not in returned_products:
            return Rejected(
                "exchange_kind_not_allowed",
                "La tienda solo admite cambios por otra talla o color del mismo producto que "
                "se devuelve.",
            )
        exchange_lines.append(
            PlanExchangeLine(
                variant_id=variant.variant_id, title=variant.title, quantity=wanted.quantity
            )
        )

    terms = policy.exchanges
    if exchange_lines:
        refund_as: RefundPreference = (
            "store_credit" if terms.lower_price == "store_credit" else "original_payment"
        )
    elif policy.refund_method != "customer_choice":
        refund_as = policy.refund_method
    elif refund_preference is None:
        return Rejected(
            "refund_preference_missing",
            "La tienda deja elegir cómo se devuelve el dinero: pregunta al cliente si lo "
            "quiere en su método de pago original (`original_payment`) o en crédito de la "
            "tienda (`store_credit`) y pásalo en `refund_preference`.",
        )
    else:
        refund_as = refund_preference

    shipping = policy.shipping
    payer = shipping.payer_for(reason.fault)
    return Eligible(
        policy_version=active.version,
        order_id=order.order_id,
        order_name=order.name,
        currency=order.currency,
        taxes_included=order.taxes_included,
        reason=reason,
        lines=tuple(
            PlanLine(
                line_item_id=line.line_item_id,
                fulfillment_line_item_id=line.fulfillment_line_item_id,
                title=line.title,
                quantity=qty,
            )
            for line, qty in lines
        ),
        exchange_lines=tuple(exchange_lines),
        evidence=evidence.photos if "photo" in reason.required_evidence else (),
        shipping_method=shipping.method,
        return_address=shipping.return_address,
        shipping_payer=payer,
        fee=shipping.customer_fee if payer == "customer" else None,
        refund_days=policy.refund_days,
        refund_as=refund_as,
        restocking_percent=policy.restocking_fee_percent.for_fault(reason.fault),
        higher_price=terms.higher_price if exchange_lines else None,
        lower_price=terms.lower_price if exchange_lines else None,
        ship_replacement=terms.ship_replacement if exchange_lines else None,
        requires_approval=bool(terms.requires_approval)
        if exchange_lines
        else policy.returns_require_approval,
    )


# ─── Liquidación ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CalculatedLine:
    """Una línea de `returnCalculate`: `key` es el id del fulfillment line item (devuelta)
    o de la variante (cambio). Shopify da lo devuelto en negativo."""

    key: str
    quantity: int
    subtotal: Decimal
    tax: Decimal


@dataclass(frozen=True)
class ReturnCalculation:
    currency: str
    returned: tuple[CalculatedLine, ...]
    exchanged: tuple[CalculatedLine, ...]


class SettlementLine(_Frozen):
    title: str
    quantity: int
    amount: Decimal


class Settlement(BaseModel):
    # Los totales serializados (`returned_total`, `net`…) se recalculan al leerlo.
    model_config = ConfigDict(extra="ignore", frozen=True)

    currency: str
    returned: tuple[SettlementLine, ...]
    exchanged: tuple[SettlementLine, ...]
    shipping_payer: Payer
    fee: Decimal
    # Tarifa de la política en otra moneda que el pedido: no se resta, la decide el equipo.
    fee_pending: Money | None
    restocking_percent: Decimal
    restocking_fee: Decimal
    price_rule: PriceRule
    refund_as: RefundPreference

    @computed_field  # type: ignore[prop-decorator]
    @property
    def returned_total(self) -> Decimal:
        return sum((ln.amount for ln in self.returned), Decimal("0"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def exchanged_total(self) -> Decimal:
        return sum((ln.amount for ln in self.exchanged), Decimal("0"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def price_difference(self) -> Decimal:
        """Positivo: el artículo de cambio cuesta más que lo devuelto."""
        return self.exchanged_total - self.returned_total if self.exchanged else Decimal("0")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def balance(self) -> Decimal | None:
        """Lo que se le devuelve al cliente (positivo, en `refund_as`) o lo que debe
        (negativo), según la política. None si falta decidir la tarifa de envío."""
        if self.fee_pending is not None:
            return None
        diff = self.price_difference
        if not self.exchanged:
            items = self.returned_total
        elif diff < 0 and self.price_rule in ("refund_difference", "store_credit"):
            items = -diff
        elif diff > 0 and self.price_rule == "customer_pays":
            items = -diff
        else:
            items = Decimal("0")
        return items - self.restocking_fee - self.fee


class ReturnPlan(_Frozen):
    """Lo que el código decidió y el humano aprueba. Se guarda en la aprobación L3 y se
    ejecuta tal cual: la ventana se juzgó en `requested_at`."""

    policy_version: int
    requested_at: datetime
    order_id: int
    order_name: str
    reason_code: str
    reason_label: str
    fault: Fault
    shopify_reason: str | None
    lines: tuple[PlanLine, ...]
    exchange_lines: tuple[PlanExchangeLine, ...]
    evidence: tuple[PhotoRef, ...]
    shipping_method: Literal["customer_ships", "store_label"]
    return_address: str | None
    refund_days: int
    ship_replacement: ShipReplacement | None
    requires_approval: bool
    settlement: Settlement

    @property
    def shopify_fee(self) -> Money | None:
        """La tarifa que se registra en Shopify (`returnShippingFee`), si aplica."""
        s = self.settlement
        if s.fee_pending is not None or s.fee == 0:
            return None
        return Money(amount=s.fee, currency=s.currency)

    def team_note(self) -> str:
        """Resumen para el equipo: nota del pedido en Shopify y tarjeta de aprobación."""
        s = self.settlement
        kind = "cambio" if self.exchange_lines else "devolución"
        rows = [
            f"Auyan · {kind} {self.order_name} (política v{self.policy_version})",
            f"Motivo: {self.reason_label} [{self.reason_code}], culpa {_FAULT_LABEL[self.fault]}",
        ]
        rows += [
            f"Devuelve: {ln.quantity} x {ln.title} = {ln.amount} {s.currency}" for ln in s.returned
        ]
        rows += [
            f"Envía: {ln.quantity} x {ln.title} = {ln.amount} {s.currency}" for ln in s.exchanged
        ]
        method = (
            "etiqueta de la tienda"
            if self.shipping_method == "store_label"
            else "lo envía el cliente"
        )
        payer = "paga la tienda" if s.shipping_payer == "store" else "paga el cliente"
        if s.fee_pending is not None:
            fee = (
                f"; tarifa de la política {s.fee_pending.amount} {s.fee_pending.currency}, en "
                "otra moneda que el pedido: decidid el importe"
            )
        elif s.fee:
            fee = f"; tarifa {s.fee} {s.currency}"
        else:
            fee = ""
        rows.append(f"Envío de vuelta: {method}, {payer}{fee}")
        if s.restocking_fee:
            rows.append(f"Reposición: {s.restocking_percent}% = {s.restocking_fee} {s.currency}")
        if s.exchanged and s.price_difference:
            rule = _PRICE_RULE_LABEL[s.price_rule]
            rows.append(f"Diferencia de precio: {s.price_difference} {s.currency}, {rule}")
        if self.ship_replacement:
            rows.append(f"Artículo de cambio: {_SHIP_LABEL[self.ship_replacement]}")
        if self.evidence:
            rows.append(f"Fotos del cliente: {len(self.evidence)} en la conversación")
        if s.balance is None:
            rows.append("Saldo: pendiente de la tarifa de envío")
        elif s.balance >= 0:
            how = _REFUND_LABEL[s.refund_as]
            rows.append(f"A devolver al recibir: {s.balance} {s.currency}, {how}")
        else:
            rows.append(f"A cobrar al cliente: {-s.balance} {s.currency}")
        return "\n".join(rows)


_PRICE_RULE_LABEL: dict[PriceRule, str] = {
    "none": "sin diferencia",
    "customer_pays": "la paga el cliente",
    "store_absorbs": "la asume la tienda",
    "refund_difference": "se reembolsa",
    "store_credit": "en crédito de la tienda",
    "no_refund": "no se reembolsa",
}
_SHIP_LABEL: dict[ShipReplacement, str] = {
    "immediately": "sale al confirmar el cambio",
    "after_receipt": "sale al recibir lo devuelto",
}
_REFUND_LABEL: dict[RefundPreference, str] = {
    "original_payment": "al método de pago original",
    "store_credit": "en crédito de la tienda",
}
_CENT = Decimal("0.01")


def _price_rule(eligible: Eligible, difference: Decimal) -> PriceRule:
    if not eligible.exchange_lines or difference == 0:
        return "none"
    if difference > 0:
        return "store_absorbs" if eligible.higher_price == "store_absorbs" else "customer_pays"
    return eligible.lower_price or "none"


def _amount(line: CalculatedLine, *, taxes_included: bool) -> Decimal:
    total = abs(line.subtotal) + (Decimal("0") if taxes_included else abs(line.tax))
    return total.quantize(Decimal("0.01"))


def build_plan(
    eligible: Eligible, calculation: ReturnCalculation, *, requested_at: datetime
) -> ReturnPlan | Rejected:
    """Plan con la liquidación, a partir de los importes de `returnCalculate`. Rechaza el
    cambio a un artículo más caro si la política no lo admite."""
    returned = {c.key: c for c in calculation.returned}
    exchanged = {c.key: c for c in calculation.exchanged}
    fee_currency_matches = (
        eligible.fee is not None and eligible.fee.currency == calculation.currency
    )
    returned_lines = tuple(
        SettlementLine(
            title=ln.title,
            quantity=ln.quantity,
            amount=_amount(
                returned[ln.fulfillment_line_item_id], taxes_included=eligible.taxes_included
            ),
        )
        for ln in eligible.lines
    )
    exchanged_lines = tuple(
        SettlementLine(
            title=ln.title,
            quantity=ln.quantity,
            amount=_amount(
                exchanged[f"gid://shopify/ProductVariant/{ln.variant_id}"],
                taxes_included=eligible.taxes_included,
            ),
        )
        for ln in eligible.exchange_lines
    )
    returned_total = sum((ln.amount for ln in returned_lines), Decimal("0"))
    difference = sum((ln.amount for ln in exchanged_lines), Decimal("0")) - returned_total
    if eligible.exchange_lines and difference > 0 and eligible.higher_price == "not_allowed":
        return Rejected(
            "exchange_price_higher",
            f"El artículo de cambio cuesta {difference} {calculation.currency} más que lo "
            "devuelto y la tienda no admite cambios con diferencia a pagar. Ofrece una "
            "variante del mismo precio o más barata.",
        )
    rule = _price_rule(eligible, difference)
    restocking = (returned_total * eligible.restocking_percent / 100).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    settlement = Settlement(
        currency=calculation.currency,
        returned=returned_lines,
        exchanged=exchanged_lines,
        restocking_percent=eligible.restocking_percent,
        restocking_fee=restocking,
        price_rule=rule,
        refund_as=eligible.refund_as,
        shipping_payer=eligible.shipping_payer,
        fee=eligible.fee.amount if eligible.fee and fee_currency_matches else Decimal("0"),
        fee_pending=eligible.fee if eligible.fee and not fee_currency_matches else None,
    )
    return ReturnPlan(
        policy_version=eligible.policy_version,
        requested_at=requested_at,
        order_id=eligible.order_id,
        order_name=eligible.order_name,
        reason_code=eligible.reason.code,
        reason_label=eligible.reason.label,
        fault=eligible.reason.fault,
        shopify_reason=eligible.reason.shopify_reason,
        lines=eligible.lines,
        exchange_lines=eligible.exchange_lines,
        evidence=eligible.evidence,
        shipping_method=eligible.shipping_method,
        return_address=eligible.return_address,
        refund_days=eligible.refund_days,
        ship_replacement=eligible.ship_replacement,
        requires_approval=eligible.requires_approval,
        settlement=settlement,
    )
