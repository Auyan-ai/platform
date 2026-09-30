"""Eventos de estado de Zernio que no son mensajes entrantes.

- `message.sent` / `message.delivered` / `message.failed`: estado de los envíos.
- Cualquier otro evento: se reconoce con 200 `ignored` (nunca 4xx: Zernio reintentaría
  y acabaría desactivando el webhook).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.api.db.client import tenant_scope
from apps.api.db.queries import find_outbound_message_by_platform_id, merge_message_metadata

if TYPE_CHECKING:
    from uuid import UUID

    from apps.api.db.models import TenantIntegration
    from apps.api.integrations.zernio import ZernioEvent

logger = logging.getLogger(__name__)

STATUS_EVENTS = frozenset({"message.sent", "message.delivered", "message.failed"})


async def handle_zernio_status_event(
    event: ZernioEvent,
    *,
    tenant_id: UUID,
    integration: TenantIntegration,
) -> dict[str, Any]:
    """Procesa un evento de Zernio distinto de `message.received`. Nunca lanza por forma."""
    if event.event not in STATUS_EVENTS:
        logger.info(
            "zernio_event_ignored",
            extra={"tenant_id": str(tenant_id), "event": event.event},
        )
        return {"received": True, "processed": False, "ignored": "unhandled_event"}

    message = event.message
    if event.event == "message.failed":
        return await _mark_failed(event, tenant_id=tenant_id)
    logger.info(
        "zernio_status_event",
        extra={
            "tenant_id": str(tenant_id),
            "event": event.event,
            "platform_message_id": message.platform_message_id if message else None,
            "source": message.source if message else None,
            "sent_via": message.sent_via if message else None,
        },
    )
    return {"received": True, "processed": True, "event": event.event}


def _error_detail(error: dict[str, Any] | None) -> dict[str, Any]:
    if not error:
        return {}
    return {
        key: error.get(key)
        for key in ("code", "title", "message", "explanation")
        if error.get(key) is not None
    }


async def _mark_failed(event: ZernioEvent, *, tenant_id: UUID) -> dict[str, Any]:
    """`message.failed`: marca nuestro saliente como `failed` y alerta (`logger.error`).

    Así se ven `131056` (demasiados mensajes al mismo destinatario) y `131047` (fuera de
    la ventana de 24 h). Si el wamid no es nuestro (p. ej. un envío desde el móvil), solo
    se registra.
    """
    message = event.message
    platform_message_id = message.platform_message_id if message else None
    detail = _error_detail(event.error)
    found = None
    if platform_message_id:
        async with tenant_scope(tenant_id) as conn:
            found = await find_outbound_message_by_platform_id(conn, tenant_id, platform_message_id)
            if found is not None:
                await merge_message_metadata(
                    conn, tenant_id, found.id, {"delivery": "failed", "delivery_error": detail}
                )
    logger.error(
        "zernio_message_failed",
        extra={
            "tenant_id": str(tenant_id),
            "message_id": str(found.id) if found else None,
            "conversation_id": str(found.conversation_id) if found else None,
            "error_code": detail.get("code"),
            "error_explanation": detail.get("explanation") or detail.get("title"),
        },
    )
    return {"received": True, "processed": True, "event": event.event, "matched": bool(found)}
