"""Eventos de estado de Zernio que no son mensajes entrantes.

- `message.sent` / `message.delivered` / `message.failed`: estado de los envíos.
- Cualquier otro evento: se reconoce con 200 `ignored` (nunca 4xx: Zernio reintentaría
  y acabaría desactivando el webhook).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

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
