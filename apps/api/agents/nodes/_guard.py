"""Decorador que envuelve cada nodo del grafo.

Garantiza dos propiedades:
1. Short-circuit: si `state['error']` ya está poblado por un nodo anterior,
   el nodo wrapped no hace nada (passthrough). Esto mantiene el diagrama del
   grafo limpio — no necesitamos una conditional edge después de cada nodo.
2. Captura de excepciones: si el nodo lanza, capturamos, logueamos con stack
   y seteamos `error` para que el grafo termine en `handle_error`.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable

from apps.api.agents.state import AgentState

logger = logging.getLogger(__name__)

NodeFn = Callable[[AgentState], Awaitable[dict]]


def guarded(name: str) -> Callable[[NodeFn], NodeFn]:
    """Decorador parametrizado por nombre del nodo (para logging legible)."""

    def decorator(node_fn: NodeFn) -> NodeFn:
        @functools.wraps(node_fn)
        async def wrapped(state: AgentState) -> dict:
            if state.get("error"):
                logger.debug("node %s skipped (prior error=%s)", name, state.get("error"))
                return {}
            try:
                return await node_fn(state)
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
