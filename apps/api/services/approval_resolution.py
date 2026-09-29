"""Cierre de la escalación de una aprobación L3 tras aprobar o rechazar.

El gate L3 crea una escalación `awaiting_human_approval:{approval_id}` y deja la
conversación 'escalated'. Al decidir el operador:
- Aprobada + ejecutada + confirmación entregada → la escalación se resuelve, la
  conversación vuelve a 'open' y se materializa la resolución autónoma
  (`services.agent_resolution.finalize_agent_resolution`: resolved + resolution
  event + cierre del ticket externo).
- Rechazada → la escalación se resuelve y la conversación vuelve a 'open' a la
  espera del cliente (sin resolución; si no contesta, la cierra el cleanup job).
- Ejecución fallida → nada: sigue escalada para que la gestione un humano.
Si el cliente vuelve a escribir, `reopen_if_resolved` reabre como en cualquier
resolución autónoma.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.db.queries import (
    get_open_escalation_for_conversation,
    reactivate_escalated_conversation,
    resolve_escalation_by_reason,
)
from apps.api.integrations.registry import IntegrationRegistry

if TYPE_CHECKING:
    import asyncpg


def approval_escalation_reason(approval_id: UUID) -> str:
    """Mismo formato con el que `execute_skill` crea la escalación del gate L3."""
    return f"awaiting_human_approval:{approval_id}"


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


def reply_delivered(channel: str, *, delivered: bool) -> bool:
    """¿Llegó la confirmación al cliente? En canales sin helpdesk (chat/widget de
    prueba) el mensaje persistido en DB es la entrega."""
    try:
        IntegrationRegistry.get("helpdesk", channel)
    except ValueError:
        return True
    return delivered
