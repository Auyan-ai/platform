"""ReasoningTracker — emite eventos de razonamiento del agente de forma fire-and-forget.

Los nodos del grafo llaman `await tracker.emit(...)` que internamente crea un
asyncio.Task para no bloquear el grafo. Si la inserción en DB falla, se loguea
y se ignora — la observabilidad no debe afectar la respuesta al cliente.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar
from uuid import UUID

from apps.api.db.client import tenant_scope
from apps.api.db.models import ReasoningEventType, ReasoningPhase, ReasoningStatus
from apps.api.db.queries import insert_reasoning_event

logger = logging.getLogger(__name__)


class ReasoningTracker:
    """Servicio stateless de emisión de eventos de razonamiento.

    Instanciar una vez en startup y pasar vía AgentDependencies.
    """

    # Guardamos refs fuertes a las tasks en vuelo para que asyncio no las pueda
    # recolectar antes de que terminen (ver RUF006). Se limpian solas al terminar.
    _pending_tasks: ClassVar[set[asyncio.Task[None]]] = set()

    def emit(
        self,
        *,
        tenant_id: str | UUID,
        conversation_id: str | UUID,
        phase: ReasoningPhase,
        event_type: ReasoningEventType,
        label: str,
        detail: dict[str, Any] | None = None,
        status: ReasoningStatus = "done",
    ) -> None:
        """Emite un evento de razonamiento de forma fire-and-forget.

        Crea un asyncio.Task internamente — el caller no espera el resultado.
        Si no hay event loop activo (tests síncronos), lo ignora silenciosamente.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # sin event loop activo — contexto de test síncrono

        task = loop.create_task(
            self._insert(
                tenant_id=UUID(str(tenant_id)),
                conversation_id=UUID(str(conversation_id)),
                phase=phase,
                event_type=event_type,
                label=label,
                detail=detail,
                status=status,
            ),
            name=f"reasoning_event_{phase}_{event_type}",
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _insert(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        phase: ReasoningPhase,
        event_type: ReasoningEventType,
        label: str,
        detail: dict[str, Any] | None,
        status: ReasoningStatus,
    ) -> None:
        try:
            async with tenant_scope(tenant_id) as conn:
                await insert_reasoning_event(
                    conn,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    phase=phase,
                    event_type=event_type,
                    label=label,
                    detail=detail,
                    status=status,
                )
        except Exception:
            logger.exception(
                "reasoning_event_insert_failed",
                extra={
                    "tenant_id": str(tenant_id),
                    "conversation_id": str(conversation_id),
                    "phase": phase,
                    "label": label,
                },
            )
