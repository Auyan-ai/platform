"""Política de devoluciones y cambios del tenant (ADR 0014 §1).

La decide cada tienda: ningún campo de negocio tiene valor por defecto. Sin política
guardada, las skills de devolución y cambio rechazan y escalan (fail-closed).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

Fault = Literal["store", "customer"]
Payer = Literal["store", "customer"]
Evidence = Literal["photo"]
WindowStart = Literal["delivery", "shipment", "order"]
ExchangeKind = Literal["variant", "product"]
# Cómo se devuelve el dinero de una devolución sin cambio.
RefundMethod = Literal["original_payment", "store_credit", "customer_choice"]
# Qué pasa si el artículo de cambio cuesta más o menos que el devuelto.
HigherPrice = Literal["customer_pays", "store_absorbs", "not_allowed"]
LowerPrice = Literal["refund_difference", "store_credit", "no_refund"]
# Cuándo sale el artículo de cambio.
ShipReplacement = Literal["immediately", "after_receipt"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# Límites técnicos, no de negocio: evitan valores absurdos (un plazo de siglos, una lista
# que no cabe en el prompt). Dentro de ellos, la tienda decide.
MAX_DAYS = 3650
MAX_REASONS = 50


class Money(_Strict):
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=3)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class ReturnWindow(_Strict):
    days: int = Field(ge=1, le=MAX_DAYS)
    starts_at: WindowStart


class ReturnReason(_Strict):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    label: str = Field(min_length=1, max_length=80)
    fault: Fault
    required_evidence: frozenset[Evidence]
    # Handle de la librería de motivos de Shopify (`returnReasonDefinitions`).
    shopify_reason: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,59}$")


class ShippingPayer(_Strict):
    store_fault: Payer
    customer_fault: Payer


class ReturnShipping(_Strict):
    method: Literal["customer_ships", "store_label"]
    return_address: str | None = Field(default=None, min_length=5, max_length=300)
    payer: ShippingPayer
    # Cuando paga el cliente y la tienda pone la etiqueta: una tarifa fija (`fixed`, con
    # `customer_fee`) o el coste real de la etiqueta (`label_cost`, lo pone el equipo).
    customer_fee_mode: Literal["fixed", "label_cost"] | None = None
    customer_fee: Money | None = None

    @model_validator(mode="after")
    def _coherent(self) -> ReturnShipping:
        customer_pays = "customer" in (self.payer.store_fault, self.payer.customer_fault)
        charges = self.method == "store_label" and customer_pays
        if self.method == "customer_ships" and not self.return_address:
            raise ValueError("customer_ships exige return_address")
        if not charges:
            if self.customer_fee_mode is not None or self.customer_fee is not None:
                raise ValueError(
                    "la tarifa solo existe con store_label y el cliente pagando: con "
                    "customer_ships el cliente paga el transporte directamente"
                )
        elif self.customer_fee_mode is None:
            raise ValueError("store_label con el cliente pagando exige customer_fee_mode")
        elif (self.customer_fee_mode == "fixed") != (self.customer_fee is not None):
            raise ValueError("customer_fee va con customer_fee_mode=fixed y solo con él")
        return self

    def payer_for(self, fault: Fault) -> Payer:
        return self.payer.store_fault if fault == "store" else self.payer.customer_fault


class RestockingFee(_Strict):
    """Porcentaje del precio devuelto que se queda la tienda, según la culpa (0 = nada)."""

    store_fault: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    customer_fault: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)

    def for_fault(self, fault: Fault) -> Decimal:
        return self.store_fault if fault == "store" else self.customer_fault


_EXCHANGE_TERMS = ("requires_approval", "higher_price", "lower_price", "ship_replacement")


class ExchangePolicy(_Strict):
    enabled: bool
    kinds: frozenset[ExchangeKind] = frozenset()
    # Obligatorios con `enabled`; sin cambios, no se rellenan.
    requires_approval: bool | None = None
    higher_price: HigherPrice | None = None
    lower_price: LowerPrice | None = None
    ship_replacement: ShipReplacement | None = None

    @model_validator(mode="after")
    def _terms_when_enabled(self) -> ExchangePolicy:
        missing = [t for t in _EXCHANGE_TERMS if getattr(self, t) is None]
        if self.enabled:
            if not self.kinds:
                raise ValueError("exchanges.enabled exige al menos un tipo de cambio")
            if missing:
                raise ValueError(f"exchanges.enabled exige {', '.join(missing)}")
        elif self.kinds or len(missing) < len(_EXCHANGE_TERMS):
            raise ValueError("sin cambios (enabled=false) sobran los tipos y las condiciones")
        return self


class ReturnsPolicy(_Strict):
    schema_version: Literal[1]
    window: ReturnWindow
    reasons: tuple[ReturnReason, ...] = Field(min_length=1, max_length=MAX_REASONS)
    shipping: ReturnShipping
    refund_days: int = Field(ge=1, le=MAX_DAYS)
    refund_method: RefundMethod
    restocking_fee_percent: RestockingFee
    excluded_product_tags: frozenset[str]
    exchanges: ExchangePolicy
    returns_require_approval: bool
    # Una devolución o un cambio con un motivo que exige foto pasa por aprobación (alguien
    # mira la foto antes de que la tienda pague el envío o reembolse).
    evidence_requires_approval: bool

    @field_validator("excluded_product_tags")
    @classmethod
    def _casefold_tags(cls, tags: frozenset[str]) -> frozenset[str]:
        # Shopify no distingue mayúsculas en las etiquetas: "Final-Sale" = "final-sale".
        return frozenset(t.strip().casefold() for t in tags if t.strip())

    @model_validator(mode="after")
    def _unique_codes(self) -> ReturnsPolicy:
        seen: set[str] = set()
        for reason in self.reasons:
            if reason.code in seen:
                raise ValueError(f"motivo repetido: {reason.code}")
            seen.add(reason.code)
        return self

    def reason(self, code: str) -> ReturnReason | None:
        return next((r for r in self.reasons if r.code == code), None)


@dataclass(frozen=True)
class ActivePolicy:
    """La versión vigente de la política: las skills citan `version` en cada plan."""

    version: int
    policy: ReturnsPolicy

    def to_state(self) -> dict[str, Any]:
        return {"version": self.version, "policy": self.policy.model_dump(mode="json")}

    @classmethod
    def from_state(cls, raw: Mapping[str, Any] | None) -> ActivePolicy | None:
        if not raw:
            return None
        policy = parse_stored_policy(raw.get("policy") or {})
        return cls(version=int(raw["version"]), policy=policy) if policy else None


_WINDOW_START_LABEL: dict[WindowStart, str] = {
    "delivery": "la entrega",
    "shipment": "el envío",
    "order": "la compra",
}
_REFUND_METHOD_LABEL: dict[RefundMethod, str] = {
    "original_payment": "al método de pago original",
    "store_credit": "en crédito de la tienda",
    "customer_choice": (
        "a elegir por el cliente entre su método de pago y crédito de la tienda (pregúntale "
        "y pásalo en `refund_preference`)"
    ),
}
_EXCHANGE_KIND_LABEL: dict[ExchangeKind, str] = {
    "variant": "otra talla o color del mismo producto",
    "product": "otro producto",
}


def policy_note(active: ActivePolicy | None) -> str:
    """Resumen para el LLM del turno: qué códigos de motivo existen y qué pide cada uno.

    Lo genera el código desde la política; quién puede devolver, el plazo y el envío los
    decide `services/returns.evaluate_return`, no el LLM.
    """
    if active is None:
        return (
            "Política de devoluciones y cambios: la tienda no la ha configurado. El sistema no "
            "abre devoluciones ni cambios; si el cliente quiere uno, pásalo al equipo."
        )
    policy = active.policy
    reasons = "\n".join(
        f"  - `{r.code}`: {r.label}"
        + (" (exige foto del cliente)" if "photo" in r.required_evidence else "")
        for r in policy.reasons
    )
    starts = _WINDOW_START_LABEL[policy.window.starts_at]
    terms = policy.exchanges
    if terms.enabled:
        kinds = " o ".join(_EXCHANGE_KIND_LABEL[k] for k in sorted(terms.kinds))
        dearer = (
            "no se admite si el nuevo cuesta más"
            if terms.higher_price == "not_allowed"
            else "se admite aunque el nuevo cueste más"
        )
        exchanges = f"Cambios: sí, por {kinds}; {dearer}."
    else:
        exchanges = "Cambios: no."
    refund = _REFUND_METHOD_LABEL[policy.refund_method]
    return (
        f"Política de devoluciones y cambios de la tienda (versión {active.version}):\n"
        f"- Plazo: {policy.window.days} días desde {starts}.\n"
        f"- Motivos (usa el código en `reason_code`):\n{reasons}\n"
        f"- Reembolso: {refund}.\n"
        f"- {exchanges}\n"
        "Plazo, pruebas, envío e importes los comprueba el sistema al pedir la acción."
    )


def parse_stored_policy(raw: Mapping[str, Any]) -> ReturnsPolicy | None:
    """La política guardada, o None si no se puede leer con este código.

    None equivale a no tener política: las skills rechazan y escalan. Nunca se adivina
    una versión de esquema desconocida.
    """
    try:
        return ReturnsPolicy.model_validate(raw)
    except ValidationError:
        logger.error(
            "returns_policy_unreadable",
            extra={"schema_version": raw.get("schema_version")},
            exc_info=True,
        )
        return None
