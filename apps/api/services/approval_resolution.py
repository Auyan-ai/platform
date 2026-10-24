"""La escalación de una aprobación L3: se abre en el gate y se cierra al decidir.

El gate L3 abre la escalación `awaiting_human_approval:{approval_id}` en la misma
transacción que crea la aprobación, y deja la conversación 'escalated'
(`open_gate_escalation`, #390). Al decidir el operador:
- Aprobada + ejecutada → se resuelven TODAS las escalaciones abiertas de la
  conversación (no solo la del gate): si el agente ya había escalado antes por la
  misma petición (error, "pedido no entregado"…), el gate reutilizó esa escalación
  y el ticket quedaba 'pending' para siempre (tickets #29/#31 del E2E A4). La
  conversación vuelve a 'open' y, con la confirmación entregada, se materializa la
  resolución autónoma
  (`services.agent_resolution.finalize_agent_resolution`: resolved + resolution
  event + cierre del ticket externo).
- Rechazada → la escalación se resuelve y la conversación vuelve a 'open' a la
  espera del cliente (sin resolución; si no contesta, la cierra el cleanup job).
- Ejecución fallida → nada: sigue escalada para que la gestione un humano.
- Ejecutada pero sin cerrar (reembolso manual o fallido, cambio que no aparece al
  releer el pedido) → la aprobación queda aprobada, sus escalaciones se cierran y se
  abre una nueva con el motivo para el equipo; la conversación sigue 'escalated' y
  no hay resolución autónoma (`hand_approval_to_team`).
- Rechazada al ejecutar por una regla en código, o sin saber si se aplicó (#376) → la
  aprobación queda 'failed' y el caso pasa al equipo con la razón (`hand_approval_to_team`).
Si el cliente vuelve a escribir, `reopen_if_resolved` reabre como en cualquier
resolución autónoma.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apps.api.db.queries import (
    get_open_escalation_by_reason,
    get_open_escalation_for_conversation,
    insert_escalation,
    lock_approval_status,
    reactivate_escalated_conversation,
    resolve_escalation_by_reason,
    resolve_open_escalations_for_conversation,
    update_conversation_status,
)
from apps.api.services.channel_routing import delivery_route
from apps.api.skills.shopify._order_guard import ActionOutcome

if TYPE_CHECKING:
    import asyncpg


def approval_escalation_reason(approval_id: UUID) -> str:
    """Mismo formato con el que `execute_skill` crea la escalación del gate L3."""
    return f"awaiting_human_approval:{approval_id}"


@dataclass(frozen=True)
class ApprovalGate:
    """La aprobación vista con su fila bloqueada y la escalación del gate, si sigue viva."""

    status: str | None
    escalation_id: UUID | None = None
    escalation_created: bool = False


async def open_gate_escalation(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    approval_id: UUID,
    triggered_by_message_id: UUID | None,
    metadata: dict[str, Any],
) -> ApprovalGate:
    """Abre o reutiliza la escalación del gate de la aprobación, en la transacción del
    caller, solo si la aprobación sigue `pending` o `executing` (#377, #390).

    Bloquea la fila de la aprobación: aprobar, rechazar y cerrar una ejecución la
    actualizan y cierran su escalación en esa misma transacción. O ven la escalación
    que se abre aquí, o esta función ve la aprobación ya resuelta y no abre nada."""
    status = await lock_approval_status(conn, tenant_id, approval_id)
    if status not in ("pending", "executing"):
        return ApprovalGate(status)
    reason = approval_escalation_reason(approval_id)
    existing = await get_open_escalation_by_reason(conn, tenant_id, conversation_id, reason)
    if existing is not None:
        return ApprovalGate(status, existing.id)
    escalation = await insert_escalation(
        conn,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        reason=reason,
        triggered_by_message_id=triggered_by_message_id,
        metadata={**metadata, "pending_approval_id": str(approval_id)},
    )
    await update_conversation_status(conn, tenant_id, conversation_id, "escalated")
    return ApprovalGate(status, escalation.id, escalation_created=True)


async def release_approval_escalation(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    approval_id: UUID,
) -> bool:
    """Resuelve la escalación de la aprobación y reactiva la conversación si no
    queda otra escalación abierta. True si había escalación que cerrar."""
    released = await resolve_escalation_by_reason(
        conn, tenant_id, conversation_id, approval_escalation_reason(approval_id)
    )
    if not released:
        return False
    if await get_open_escalation_for_conversation(conn, tenant_id, conversation_id) is None:
        await reactivate_escalated_conversation(conn, tenant_id, conversation_id)
    return True


async def release_escalations_after_executed_action(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> int:
    """Acción L3 aprobada y ejecutada: el humano revisó la conversación y la petición
    quedó atendida → se cierran todas sus escalaciones abiertas y vuelve a 'open'.
    Devuelve cuántas escalaciones cerró."""
    closed = await resolve_open_escalations_for_conversation(conn, tenant_id, conversation_id)
    await reactivate_escalated_conversation(conn, tenant_id, conversation_id)
    return closed


_ACTION_NAME: dict[str, str] = {
    "shopify.update_shipping_address": "El cambio de dirección",
    "shopify.cancel_order": "La cancelación",
    "shopify.refund_partial": "El reembolso parcial",
    "shopify.start_return": "La devolución",
    "shopify.start_exchange": "El cambio",
}


def team_followup_reason(skill_slug: str, output: dict[str, Any]) -> str | None:
    """Motivo para el equipo cuando la acción aprobada se ejecutó pero no quedó
    cerrada. None si no hace falta nadie (sin `outcome` o resultado ya resuelto)."""
    raw = output.get("outcome")
    if raw is not None and output.get("note_written") is False:
        action = _ACTION_NAME.get(skill_slug, f"La acción {skill_slug}")
        return (
            f"{action} del pedido {output.get('order_id')} se abrió en Shopify "
            f"({output.get('return_name') or 'sin nombre'}), pero no se pudo escribir la "
            "liquidación en la nota del pedido. Copiadla desde la aprobación."
        )
    if raw is None or ActionOutcome(raw).settled:
        return None
    outcome = ActionOutcome(raw)
    action = _ACTION_NAME.get(skill_slug, f"La acción {skill_slug}")
    order = output.get("order_id")
    gateway = output.get("refund_gateway") or "sin nombre"
    detail = output.get("detail") or "sin detalle"
    if outcome is ActionOutcome.REFUND_MANUAL:
        return (
            f"{action} del pedido {order} se ejecutó en Shopify, pero el cobro es de una "
            f"pasarela manual ({gateway}) o no consta en Shopify: Shopify no devuelve el "
            "dinero. Haced el reembolso a mano si el cliente pagó y confirmádselo."
        )
    if outcome is ActionOutcome.REFUND_FAILED:
        return (
            f"{action} del pedido {order} se ejecutó en Shopify, pero el reembolso no se "
            f"completó ({detail}). Revisad el pago y devolvedlo a mano si hace falta."
        )
    return (
        f"{action} del pedido {order} se aprobó y se ejecutó, pero al releer el pedido "
        f"en Shopify el cambio no aparece ({detail}). Revisad el pedido."
    )


def unknown_outcome_reason(
    skill_slug: str, inputs: dict[str, Any], error: str, *, approved: bool = True
) -> str:
    """Motivo para el equipo cuando no se puede saber si la acción se aplicó: tras una
    aprobación, o lanzada sin ella en el turno (`approved=False`)."""
    action = _ACTION_NAME.get(skill_slug, f"La acción {skill_slug}")
    how = "se aprobó" if approved else "se lanzó sin aprobación humana"
    return (
        f"{action} del pedido {inputs.get('order_id')} {how}, pero no se pudo "
        f"comprobar en Shopify si se aplicó ({error}). No se reintentó: revisad el pedido "
        "en Shopify antes de volver a hacerlo y contestad al cliente."
    )


async def hand_approval_to_team(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    approval_id: UUID,
    reason: str,
) -> UUID:
    """El equipo tiene que rematar la aprobación (ejecutada sin cerrar, rechazada por una
    regla o con resultado desconocido): se cierran las escalaciones abiertas (la del gate
    ya no aplica) y se abre una con `reason`. La conversación queda 'escalated'. Devuelve
    el id de la escalación nueva."""
    await resolve_open_escalations_for_conversation(conn, tenant_id, conversation_id)
    escalation = await insert_escalation(
        conn,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        reason=reason,
        metadata={"approval_id": str(approval_id)},
    )
    await update_conversation_status(conn, tenant_id, conversation_id, "escalated")
    return escalation.id


def reply_delivered(channel: str, *, delivered: bool) -> bool:
    """¿Llegó la confirmación al cliente? En canales sin ruta de entrega (chat/widget de
    prueba) el mensaje persistido en DB es la entrega. En los que la tienen (helpdesk o
    mensajería como WhatsApp) solo cuenta la entrega confirmada."""
    if delivery_route(channel) is None:
        return True
    return delivered
