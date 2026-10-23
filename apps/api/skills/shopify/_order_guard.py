"""Defensas en código de las L3 que tocan un pedido ya hecho (issue #318).

Antes de pedir aprobación y otra vez al ejecutar, `ensure_order_changeable` rechaza un
pedido cancelado o que ya salió. Tras ejecutar, el pedido se relee y el resultado se
clasifica en un `ActionOutcome`: nunca se da por hecho lo que Shopify no confirma.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from apps.api.integrations.base import MutationNotApplied
from apps.api.integrations.shopify import OrderSnapshot, RefundRoute, SnapshotTransaction
from apps.api.services.fixed_texts import fixed_text
from apps.api.skills.base import SkillContext, SkillRefusal

OrderAction = Literal["address", "cancel"]


class ActionOutcome(StrEnum):
    """Cómo acabó una L3 sobre un pedido, releído de Shopify."""

    CONFIRMED = "confirmed"
    # El reembolso automático existe pero la pasarela aún no lo completó.
    REFUND_PENDING = "refund_pending"
    # Pasarela manual o sin cobro registrado: devuelve la tienda, no Shopify.
    REFUND_MANUAL = "refund_manual"
    REFUND_FAILED = "refund_failed"
    # Releído el pedido, el cambio no aparece.
    NOT_CONFIRMED = "not_confirmed"

    @property
    def settled(self) -> bool:
        """Hecho sin que el equipo tenga que intervenir."""
        return self in (ActionOutcome.CONFIRMED, ActionOutcome.REFUND_PENDING)


@dataclass(frozen=True)
class Verdict:
    outcome: ActionOutcome
    # Motivo para el equipo cuando no se confirma (código de error de la pasarela…).
    detail: str | None = None


_ACTION_LABEL: dict[OrderAction, str] = {
    "address": "cambiar la dirección de envío del pedido",
    "cancel": "cancelar el pedido",
}


async def snapshot_before_mutation(adapter: Any, ctx: SkillContext, order_id: int) -> OrderSnapshot:
    """El pedido antes de mutarlo. Si no se puede leer, la mutación no llegó a enviarse."""
    try:
        snapshot: OrderSnapshot = await adapter.get_order_snapshot(ctx.integration_ctx, order_id)
    except Exception as exc:
        raise MutationNotApplied(
            f"lectura previa a la mutación: {type(exc).__name__}: {exc}"
        ) from exc
    return snapshot


def ensure_order_changeable(
    snapshot: OrderSnapshot, action: OrderAction, ctx: SkillContext
) -> None:
    """Lanza `SkillRefusal` si el pedido está cancelado o ya salió.

    El texto al cliente sale en el idioma de la conversación; `team_reason` va en español.
    """
    if snapshot.cancelled:
        code = "order_cancelled"
        why = "Shopify ya lo tiene cancelado"
        next_step = "revisad el estado del pedido y del reembolso"
    elif snapshot.shipped:
        code = "order_shipped"
        tracking = sum(len(f.tracking_numbers) for f in snapshot.fulfillments if f.active)
        why = (
            f"Shopify lo marca como enviado (estado {snapshot.fulfillment_status or 'n/d'}, "
            f"{tracking} número(s) de seguimiento)"
        )
        next_step = "revisad el caso con el almacén o el transportista"
    else:
        return
    order = snapshot.name or snapshot.order_id
    raise SkillRefusal(
        code,
        customer_message=fixed_text(
            f"refusal.{code}.{action}", ctx.language, tenant_default=ctx.default_language
        ),
        team_reason=(
            f"El cliente pidió {_ACTION_LABEL[action]} {order}, pero {why}. "
            f"No se pidió aprobación: {next_step}."
        ),
    )


def refund_verdict(route: RefundRoute, before: OrderSnapshot, after: OrderSnapshot) -> Verdict:
    """Estado del reembolso emitido entre `before` y `after`.

    Con pasarela manual Shopify marca el REFUND como SUCCESS sin mover dinero (visto
    en Marea), así que su estado no dice nada: devuelve la tienda.
    """
    return refund_transactions_verdict(route, after.refunds_since(before))


def refund_transactions_verdict(
    route: RefundRoute, refunds: tuple[SnapshotTransaction, ...]
) -> Verdict:
    """Estado de un reembolso a partir de sus transacciones de tipo `refund`."""
    if route.mode == "manual":
        return Verdict(ActionOutcome.REFUND_MANUAL)
    if not refunds:
        return Verdict(ActionOutcome.REFUND_FAILED, "refund_transaction_missing")
    failed = [t for t in refunds if t.status in ("failure", "error")]
    if failed:
        return Verdict(ActionOutcome.REFUND_FAILED, failed[0].error_code or failed[0].status)
    if any(t.status != "success" for t in refunds):
        return Verdict(ActionOutcome.REFUND_PENDING)
    return Verdict(ActionOutcome.CONFIRMED)


def cancellation_verdict(before: OrderSnapshot, after: OrderSnapshot) -> Verdict:
    if not after.cancelled:
        return Verdict(ActionOutcome.NOT_CONFIRMED, "order_not_cancelled")
    return refund_verdict(before.refund_route, before, after)


def _normalized(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def address_verdict(after: OrderSnapshot, *, address1: str, zip_code: str, city: str) -> Verdict:
    saved = after.shipping_address
    expected = {"address1": address1, "zip": zip_code, "city": city}
    mismatched = [k for k, v in expected.items() if _normalized(saved.get(k)) != _normalized(v)]
    if mismatched:
        return Verdict(ActionOutcome.NOT_CONFIRMED, f"address_mismatch: {', '.join(mismatched)}")
    return Verdict(ActionOutcome.CONFIRMED)
