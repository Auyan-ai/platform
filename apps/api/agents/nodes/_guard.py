"""Decorador que `build_graph` aplica a cada nodo del turno (`TURN_NODES`).

Si el nodo lanza, captura, loguea con stack y setea `error`; la arista de salida
del nodo lleva entonces a `handle_error`, que escala con razón explícita.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable

from apps.api.agents.state import AgentState
from apps.api.integrations.anthropic_client import (
    PROVIDER_UNAVAILABLE_CATEGORY,
    LLMProviderUnavailable,
)
from apps.api.services.llm_alert import report_provider_unavailable

logger = logging.getLogger(__name__)

NodeFn = Callable[[AgentState], Awaitable[dict]]


def guarded(name: str) -> Callable[[NodeFn], NodeFn]:
    """Decorador parametrizado por nombre del nodo (para logging legible)."""

    def decorator(node_fn: NodeFn) -> NodeFn:
        @functools.wraps(node_fn)
        async def wrapped(state: AgentState) -> dict:
            try:
                return await node_fn(state)
            except LLMProviderUnavailable as exc:
                # Caída total del proveedor: log + alerta deduplicada; el error lleva la
                # categoría para que `handle_error` escale con razón explícita.
                await report_provider_unavailable(
                    reason=exc.reason,
                    status_code=exc.status_code,
                    detail=exc.detail,
                    tenant_id=state.get("tenant_id"),
                    conversation_id=state.get("conversation_id"),
                )
                return {"error": f"{PROVIDER_UNAVAILABLE_CATEGORY}: {exc.reason} (node {name})"}
            except Exception as exc:
                logger.exception(
                    "node %s raised %s",
                    name,
                    type(exc).__name__,
                    extra={
                        "tenant_id": state.get("tenant_id"),
                        "conversation_id": state.get("conversation_id"),
                    },
                )
                return {"error": f"{name}: {type(exc).__name__}: {exc!s}"}

        return wrapped

    return decorator
