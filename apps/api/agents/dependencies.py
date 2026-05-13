"""Inyección de dependencias del grafo.

Mantiene los nodos puros (no acceden a singletons globales para LLMs).
Esto facilita tests: inyectás mocks de `anthropic` y `openai` y listo.

La DB *sí* se accede vía singleton (`db.client.tenant_scope`) porque el pool
de asyncpg es global por proceso; testeás con conexión a una DB de tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic
    from openai import AsyncOpenAI

    from apps.api.core.config import Settings


@dataclass(frozen=True)
class AgentDependencies:
    """Bundle de clientes y config que necesitan los nodos."""

    anthropic: AsyncAnthropic
    openai: AsyncOpenAI
    settings: Settings
