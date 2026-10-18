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

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

Fault = Literal["store", "customer"]
Payer = Literal["store", "customer"]
Evidence = Literal["photo"]
WindowStart = Literal["delivery", "shipment", "order"]
ExchangeKind = Literal["variant", "product"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Money(_Strict):
    amount: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class ReturnWindow(_Strict):
    days: int = Field(ge=1, le=365)
    starts_at: WindowStart


class ReturnReason(_Strict):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    label: str = Field(min_length=1, max_length=80)
    fault: Fault
    required_evidence: frozenset[Evidence] = frozenset()
    # Handle de la librería de motivos de Shopify (`returnReasonDefinitions`).
    shopify_reason: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,59}$")


class ShippingPayer(_Strict):
    store_fault: Payer
    customer_fault: Payer


class ReturnShipping(_Strict):
    method: Literal["customer_ships", "store_label"]
    return_address: str | None = Field(default=None, min_length=5, max_length=300)
    payer: ShippingPayer
    # Lo que se descuenta del reembolso cuando paga el cliente y la tienda pone la etiqueta.
    customer_fee: Money | None = None

    @model_validator(mode="after")
    def _coherent(self) -> ReturnShipping:
        customer_pays = "customer" in (self.payer.store_fault, self.payer.customer_fault)
        if self.method == "customer_ships":
            if not self.return_address:
                raise ValueError("customer_ships exige return_address")
            if self.customer_fee is not None:
                raise ValueError(
                    "customer_fee solo vale con store_label: con customer_ships el cliente "
                    "paga el transporte directamente"
                )
        elif customer_pays and self.customer_fee is None:
            raise ValueError("store_label con el cliente pagando exige customer_fee")
        elif not customer_pays and self.customer_fee is not None:
            raise ValueError("customer_fee sobra: la tienda paga siempre el envío de vuelta")
        return self

    def payer_for(self, fault: Fault) -> Payer:
        return self.payer.store_fault if fault == "store" else self.payer.customer_fault


class ExchangePolicy(_Strict):
    enabled: bool
    kinds: frozenset[ExchangeKind] = frozenset()

    @model_validator(mode="after")
    def _kinds_when_enabled(self) -> ExchangePolicy:
        if self.enabled and not self.kinds:
            raise ValueError("exchanges.enabled exige al menos un tipo de cambio")
        return self


class ReturnsPolicy(_Strict):
    schema_version: Literal[1]
    window: ReturnWindow
    reasons: tuple[ReturnReason, ...] = Field(min_length=1, max_length=20)
    shipping: ReturnShipping
    refund_days: int = Field(ge=1, le=60)
    excluded_product_tags: frozenset[str]
    exchanges: ExchangePolicy
    returns_require_approval: bool

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
    if policy.exchanges.enabled:
        kinds = " o ".join(_EXCHANGE_KIND_LABEL[k] for k in sorted(policy.exchanges.kinds))
        exchanges = f"Cambios: sí, por {kinds}."
    else:
        exchanges = "Cambios: no."
    return (
        f"Política de devoluciones y cambios de la tienda (versión {active.version}):\n"
        f"- Plazo: {policy.window.days} días desde {_WINDOW_START_LABEL[policy.window.starts_at]}.\n"
        f"- Motivos (usa el código en `reason_code`):\n{reasons}\n"
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
