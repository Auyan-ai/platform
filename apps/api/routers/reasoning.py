"""Router: Agent Reasoning Events.

Endpoints:
  GET /conversations/{conversation_id}/reasoning
    → historial completo (REST, para cargar al abrir el panel)
  GET /conversations/{conversation_id}/reasoning/stream
    → SSE — stream de eventos en tiempo real mientras el agente trabaja
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.core.errors import ForbiddenError, NotFoundError
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id
from apps.api.db.client import tenant_scope
from apps.api.db.queries import get_conversation, list_reasoning_events
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["reasoning"])

SSE_POLL_INTERVAL = 1.0   # segundos entre polls en el stream SSE
SSE_MAX_DURATION  = 300   # segundos máximos del stream (5 min)


def _check_access(auth: AuthContext, tenant_id: UUID) -> None:
    """Verifica que el auth context tenga acceso a este tenant."""
    if auth.role == "super_admin":
        return
    if auth.tenant_id != tenant_id:
        raise ForbiddenError("tenant_mismatch")


async def _get_conversation_or_404(tenant_id: UUID, conversation_id: UUID) -> None:
    async with tenant_scope(tenant_id) as conn:
        conv = await get_conversation(conn, tenant_id, conversation_id)
    if conv is None:
        raise NotFoundError("conversation_not_found")


@router.get("/{conversation_id}/reasoning")
async def get_reasoning_events(
    conversation_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Historial completo de eventos de razonamiento para una conversación."""
    _check_access(auth, tenant_id)
    await _get_conversation_or_404(tenant_id, conversation_id)

    async with tenant_scope(tenant_id) as conn:
        events = await list_reasoning_events(
            conn,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )

    return {
        "conversation_id": str(conversation_id),
        "events": [
            {
                "id": str(e.id),
                "phase": e.phase,
                "event_type": e.event_type,
                "label": e.label,
                "detail": e.detail,
                "status": e.status,
                "seq": e.seq,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    }


@router.get("/{conversation_id}/reasoning/stream")
async def stream_reasoning_events(
    conversation_id: UUID,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    tenant_id: UUID = Depends(get_tenant_id),
) -> StreamingResponse:
    """SSE stream de eventos de razonamiento en tiempo real.

    Hace polling a DB cada SSE_POLL_INTERVAL segundos y emite solo los eventos
    nuevos (mayor seq que el último enviado). El cliente puede reconectar y
    reanudar desde donde quedó via Last-Event-ID.
    El stream se cierra automáticamente tras SSE_MAX_DURATION segundos o cuando
    el cliente se desconecta.
    """
    _check_access(auth, tenant_id)
    await _get_conversation_or_404(tenant_id, conversation_id)

    last_seq = -1
    # Soporte para reconexión SSE — el cliente puede enviar Last-Event-ID
    if last_event_id := request.headers.get("last-event-id"):
        try:
            last_seq = int(last_event_id)
        except ValueError:
            pass

    async def _event_generator():
        nonlocal last_seq
        elapsed = 0.0

        while elapsed < SSE_MAX_DURATION:
            if await request.is_disconnected():
                break

            async with tenant_scope(tenant_id) as conn:
                all_events = await list_reasoning_events(
                    conn,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                )

            new_events = [e for e in all_events if e.seq > last_seq]
            for event in new_events:
                payload = json.dumps({
                    "id": str(event.id),
                    "phase": event.phase,
                    "event_type": event.event_type,
                    "label": event.label,
                    "detail": event.detail,
                    "status": event.status,
                    "seq": event.seq,
                    "created_at": event.created_at.isoformat(),
                })
                yield f"id: {event.seq}\ndata: {payload}\n\n"
                last_seq = event.seq

            await asyncio.sleep(SSE_POLL_INTERVAL)
            elapsed += SSE_POLL_INTERVAL

        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
