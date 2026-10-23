"""Decisión y liquidación de una devolución o un cambio (ADR 0014 §4-§5).

Funciones puras: reciben la política vigente, el pedido releído de Shopify y lo que pidió
el cliente, y devuelven un `Eligible`, un `Refused` (escala al equipo) o un `Rejected`
(vuelve al LLM para que el cliente lo corrija). Nada de aquí lo decide el LLM.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal
from uuid import uuid4

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
    "fees_exceed_refund",
]
RejectionCode = Literal[
    "reason_not_in_policy",
    "item_not_returnable",
    "quantity_exceeds_returnable",
    "evidence_missing",
    "exchange_kind_not_allowed",
    "exchange_variant_unavailable",
    "exchange_price_higher",
    "exchange_variant_repeated",
    "exchange_quantity_exceeds_returned",
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
    # Unidades que se pueden vender si la tienda no vende sin stock; None = sin tope.
    stock: int | None = None


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
    # De `quantity`, las unidades que se devuelven a cambio de otra; el resto se reembolsa.
    exchanged_quantity: int = Field(default=0, ge=0)


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
    # La tarifa es el coste real de la etiqueta: la pone el equipo al tramitarla.
    fee_label_cost: bool
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


def _last_day(
    order: ReturnableOrder, line: ReturnableLine, active: ActivePolicy, tz: tzinfo
) -> date | None:
    """Último día del plazo, en el calendario de la tienda: el plazo acaba a medianoche."""
    window = active.policy.window
    anchor = {
        "delivery": line.delivered_at,
        "shipment": line.shipped_at,
        "order": order.ordered_at,
    }[window.starts_at]
    return anchor.astimezone(tz).date() + timedelta(days=window.days) if anchor else None


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
    tz: tzinfo = UTC,
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
        tags = frozenset(t.casefold() for t in line.product_tags or ())
        hit = sorted(excluded & tags)
        if hit:
            return Refused(
                "product_excluded",
                f"'{line.title}' de {order.name} tiene la etiqueta {', '.join(hit)}, que la "
                "política excluye de devolución.",
            )

    for line, _ in lines:
        last_day = _last_day(order, line, active, tz)
        if last_day is None:
            return Refused(
                "delivery_date_unknown",
                f"La política cuenta el plazo desde la entrega y Shopify no tiene fecha de "
                f"entrega de '{line.title}' ({order.name}). Comprobad la entrega con el "
                "transportista.",
            )
        if now > datetime.combine(last_day, time.max, tzinfo=tz):
            starts = _ANCHOR_LABEL[policy.window.starts_at]
            return Refused(
                "outside_window",
                f"'{line.title}' de {order.name} está fuera de plazo: {policy.window.days} días "
                f"desde {starts}, terminó el {last_day:%d/%m/%Y}.",
                {"deadline": last_day.isoformat()},
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

    wanted_ids = [w.variant_id for w in exchange]
    if len(wanted_ids) != len(set(wanted_ids)):
        return Rejected(
            "exchange_variant_repeated",
            "Cada variante de cambio va una sola vez, con su cantidad total.",
        )
    returned_units = sum(qty for _, qty in lines)
    wanted_units = sum(w.quantity for w in exchange)
    if wanted_units > returned_units:
        # Recibir más unidades de las que se devuelven es una venta, no un cambio.
        return Rejected(
            "exchange_quantity_exceeds_returned",
            f"Se devuelven {returned_units} unidad(es) y se piden {wanted_units} a cambio: "
            "como máximo tantas como se devuelven.",
        )
    exchange_lines: list[PlanExchangeLine] = []
    returned_products = {line.product_id for line, _ in lines if line.product_id is not None}
    by_id = {v.variant_id: v for v in variants}
    for wanted in exchange:
        variant = by_id.get(wanted.variant_id)
        stock = variant.stock if variant is not None else None
        short = stock is not None and stock < wanted.quantity
        if variant is None or not variant.available or short:
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
    # Las unidades que solo se devuelven se reembolsan como en una devolución
    # (`refund_method`); en un cambio completo solo queda la diferencia (`lower_price`).
    if exchange_lines and wanted_units == returned_units:
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
                exchanged_quantity=swapped,
            )
            for (line, qty), swapped in zip(
                lines, _exchanged_units(lines, exchange_lines, by_id), strict=True
            )
        ),
        exchange_lines=tuple(exchange_lines),
        evidence=evidence.photos if "photo" in reason.required_evidence else (),
        shipping_method=shipping.method,
        return_address=shipping.return_address,
        shipping_payer=payer,
        fee=shipping.customer_fee if payer == "customer" else None,
        fee_label_cost=payer == "customer" and shipping.customer_fee_mode == "label_cost",
        refund_days=policy.refund_days,
        refund_as=refund_as,
        restocking_percent=policy.restocking_fee_percent.for_fault(reason.fault),
        higher_price=terms.higher_price if exchange_lines else None,
        lower_price=terms.lower_price if exchange_lines else None,
        ship_replacement=terms.ship_replacement if exchange_lines else None,
        requires_approval=(
            bool(terms.requires_approval) if exchange_lines else policy.returns_require_approval
        )
        or ("photo" in reason.required_evidence and policy.evidence_requires_approval),
    )


def _exchanged_units(
    lines: list[tuple[ReturnableLine, int]],
    exchange_lines: list[PlanExchangeLine],
    variants: Mapping[int, ExchangeVariant],
) -> list[int]:
    """Cuántas unidades de cada línea devuelta van a cambio de las pedidas: primero las
    del mismo producto que la variante, luego el resto en el orden del pedido."""
    left = [qty for _, qty in lines]
    for wanted in exchange_lines:
        product = variants[wanted.variant_id].product_id
        need = wanted.quantity
        for i in sorted(range(len(lines)), key=lambda i: lines[i][0].product_id != product):
            take = min(need, left[i])
            left[i] -= take
            need -= take
    return [qty - rest for (_, qty), rest in zip(lines, left, strict=True)]


# ─── Liquidación ──────────────────────────────────────────────────────────────

# Decimales de las monedas que no usan 2 (ISO 4217).
_CURRENCY_DECIMALS: dict[str, int] = {
    **dict.fromkeys(
        "BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX UYI VND VUV XAF XOF XPF".split(), 0
    ),
    **dict.fromkeys("BHD IQD JOD KWD LYD OMR TND".split(), 3),
    **dict.fromkeys("CLF UYW".split(), 4),
}


def currency_decimals(currency: str) -> int:
    return _CURRENCY_DECIMALS.get(currency.upper(), 2)


def round_money(amount: Decimal, currency: str) -> Decimal:
    """`amount` redondeado a los decimales de la moneda (JPY 0, EUR 2, KWD 3)."""
    return amount.quantize(Decimal(1).scaleb(-currency_decimals(currency)), ROUND_HALF_UP)


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
    # Solo en lo devuelto: unidades que van a cambio de otra (el resto se reembolsa).
    exchanged_quantity: int = 0


def _exchanged_value(returned: Iterable[SettlementLine], currency: str) -> Decimal:
    return sum(
        (
            round_money(ln.amount * ln.exchanged_quantity / ln.quantity, currency)
            for ln in returned
            if ln.exchanged_quantity
        ),
        Decimal("0"),
    )


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
    fee_label_cost: bool
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
    def exchanged_value(self) -> Decimal:
        """Lo que vale lo devuelto que va a cambio de otra cosa."""
        return _exchanged_value(self.returned, self.currency)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def price_difference(self) -> Decimal:
        """Positivo: lo que se recibe a cambio cuesta más que lo que se da por ello."""
        return self.exchanged_total - self.exchanged_value if self.exchanged else Decimal("0")

    @property
    def difference_as(self) -> RefundPreference:
        """Cómo se devuelve la diferencia de un cambio más barato (`lower_price`)."""
        return "store_credit" if self.price_rule == "store_credit" else "original_payment"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def balance(self) -> Decimal | None:
        """Lo que se le devuelve al cliente (positivo) o lo que debe (negativo), según la
        política. None si falta decidir la tarifa de envío. Cómo se le devuelve, en
        `payouts`."""
        payouts = self._pots()
        return None if payouts is None else sum(payouts.values(), Decimal("0"))

    @property
    def payouts(self) -> dict[RefundPreference, Decimal]:
        """El saldo por forma de devolverlo: las unidades que solo se devuelven en
        `refund_as` y la diferencia de un cambio más barato en `difference_as`. Vacío si el
        saldo no es positivo o está pendiente."""
        pots = self._pots()
        if pots is None or sum(pots.values(), Decimal("0")) <= 0:
            return {}
        return {form: amount for form, amount in pots.items() if amount}

    def _pots(self) -> dict[RefundPreference, Decimal] | None:
        if self.fee_pending is not None or self.fee_label_cost:
            return None
        diff = self.price_difference
        owed = diff if diff > 0 and self.price_rule == "customer_pays" else Decimal("0")
        refunded = self.returned_total - self.exchanged_value
        pots = {self.refund_as: refunded - owed - self.restocking_fee - self.fee}
        if diff < 0 and self.price_rule in ("refund_difference", "store_credit"):
            pots[self.difference_as] = pots.get(self.difference_as, Decimal("0")) - diff
        # Los gastos salen primero del reembolso; si no alcanza, de la diferencia.
        if len(pots) == 2 and pots[self.refund_as] < 0:
            pots[self.difference_as] += pots[self.refund_as]
            pots[self.refund_as] = Decimal("0")
        return pots


class ReturnPlan(_Frozen):
    """Lo que el código decidió y el humano aprueba. Se guarda en la aprobación L3 y se
    ejecuta tal cual: la ventana se juzgó en `requested_at`."""

    # Marca la devolución en Shopify: un reintento tras un timeout la encuentra y no duplica.
    plan_id: str = Field(pattern=r"^[0-9a-f]{32}$")
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
            f"Devuelve: {ln.quantity} x {ln.title} = {ln.amount} {s.currency}"
            + (f" ({ln.exchanged_quantity} a cambio)" if ln.exchanged_quantity else "")
            for ln in s.returned
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
        if s.fee_label_cost:
            fee = "; tarifa = coste real de la etiqueta: ponedlo al tramitarla"
        elif s.fee_pending is not None:
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
            for form, amount in (s.payouts or {s.refund_as: s.balance}).items():
                how = _REFUND_LABEL[form]
                rows.append(f"A devolver al recibir: {amount} {s.currency}, {how}")
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


def _price_rule(eligible: Eligible, difference: Decimal) -> PriceRule:
    if not eligible.exchange_lines or difference == 0:
        return "none"
    if difference > 0:
        return "store_absorbs" if eligible.higher_price == "store_absorbs" else "customer_pays"
    return eligible.lower_price or "none"


def _amount(line: CalculatedLine, *, taxes_included: bool) -> Decimal:
    return abs(line.subtotal) + (Decimal("0") if taxes_included else abs(line.tax))


def build_plan(
    eligible: Eligible,
    calculation: ReturnCalculation,
    *,
    requested_at: datetime,
    plan_id: str | None = None,
) -> ReturnPlan | Rejected | Refused:
    """Plan con la liquidación, a partir de los importes de `returnCalculate`. Rechaza el
    cambio a un artículo más caro si la política no lo admite. Una devolución sin cambio
    cuyos gastos superan lo que se devuelve no se abre: pasa al equipo."""
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
            exchanged_quantity=ln.exchanged_quantity,
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
    difference = sum((ln.amount for ln in exchanged_lines), Decimal("0")) - _exchanged_value(
        returned_lines, calculation.currency
    )
    if eligible.exchange_lines and difference > 0 and eligible.higher_price == "not_allowed":
        return Rejected(
            "exchange_price_higher",
            f"El artículo de cambio cuesta {difference} {calculation.currency} más que lo "
            "devuelto y la tienda no admite cambios con diferencia a pagar. Ofrece una "
            "variante del mismo precio o más barata.",
        )
    rule = _price_rule(eligible, difference)
    restocking = round_money(
        returned_total * eligible.restocking_percent / 100, calculation.currency
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
        fee_label_cost=eligible.fee_label_cost,
    )
    if not exchanged_lines and settlement.balance is not None and settlement.balance < 0:
        cur = calculation.currency
        costs = settlement.fee + settlement.restocking_fee
        return Refused(
            "fees_exceed_refund",
            f"La devolución de {eligible.order_name} devuelve {returned_total} {cur} y los "
            f"gastos suman {costs} {cur} (tarifa de envío {settlement.fee} {cur}, reposición "
            f"{settlement.restocking_fee} {cur}): el saldo sería negativo. No se abrió la "
            "devolución; hablad con el cliente y decidid si se tramita igualmente.",
        )
    return ReturnPlan(
        plan_id=plan_id or uuid4().hex,
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
