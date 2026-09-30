"""Ventana de atención de los canales de mensajería (WhatsApp: 24 h de Meta).

Nombre y estructura agnósticos de canal: el omnicanal futuro (Instagram/Messenger/TikTok)
solo añade políticas a `WINDOW_POLICIES`. Hoy solo existe `whatsapp`.

La ventana se abre con cada mensaje del **comprador** en el chat (todas las sesiones de
Auyan del mismo `(channel, external_id)`) y dura 24 h. Por seguridad la damos por cerrada
10 min antes (a las 23 h 50 min): un envío en el límite lo rechazaría Meta (`131047`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from apps.api.db.queries import get_last_customer_inbound_at

if TYPE_CHECKING:
    from uuid import UUID

    import asyncpg
    from apps.api.db.models import ChannelType, Conversation


@dataclass(frozen=True)
class WindowPolicy:
    duration: timedelta
    safety_margin: timedelta
    # Qué se hace fuera de la ventana: WhatsApp → plantilla de re-enganche aprobada.
    out_of_window: Literal["reengagement_template"]


@dataclass(frozen=True)
class WindowState:
    open: bool
    closes_at: datetime | None


WINDOW_POLICIES: dict[ChannelType, WindowPolicy] = {
    "whatsapp": WindowPolicy(
        duration=timedelta(hours=24),
        safety_margin=timedelta(minutes=10),
        out_of_window="reengagement_template",
    ),
}


def window_policy(channel: str) -> WindowPolicy | None:
    return WINDOW_POLICIES.get(channel)  # type: ignore[call-overload]


def compute_window(
    last_customer_inbound_at: datetime | None,
    policy: WindowPolicy,
    now: datetime | None = None,
) -> WindowState:
    """Estado de la ventana a partir del último mensaje del comprador (función pura)."""
    if last_customer_inbound_at is None:
        return WindowState(open=False, closes_at=None)
    last = last_customer_inbound_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    closes_at = last + policy.duration
    current = now or datetime.now(UTC)
    return WindowState(open=current < closes_at - policy.safety_margin, closes_at=closes_at)


async def window_state(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    conversation: Conversation,
) -> WindowState:
    """Ventana del chat de la conversación. Canal sin política → siempre abierta."""
    policy = window_policy(conversation.channel)
    if policy is None:
        return WindowState(open=True, closes_at=None)
    if not conversation.external_id:
        return WindowState(open=False, closes_at=None)
    last = await get_last_customer_inbound_at(
        conn, tenant_id, conversation.channel, conversation.external_id
    )
    return compute_window(last, policy)
