"""Nodo: finalize_trace.

Cierre simbólico del trace dentro del grafo. La integración real con Langfuse
(cerrar trace, set score, attrs finales) la hace el servicio que orquesta el
grafo, ANTES de retornar al caller del webhook. Esto mantiene los nodos
desacoplados del provider de observabilidad.

Por ahora es un no-op pero existe como nodo para que el diagrama sea explícito
y para tener un punto donde, si queremos, podemos agregar lógica de cierre
(ej: notificar métricas internas).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.state import AgentState


def make_finalize_trace_node(
    deps: AgentDependencies,  # noqa: ARG001
) -> Callable[[AgentState], Awaitable[dict]]:
    async def _node(state: AgentState) -> dict:  # noqa: ARG001
        return {}

    return _node
