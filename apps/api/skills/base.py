"""Skills framework — base abstractions.

Cada skill es una acción tipada del agente (L1 read, L2 write bajo riesgo, L3 write alto riesgo).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from pydantic import BaseModel

SkillTier = Literal["L1", "L2", "L3"]

# Confidence thresholds por tier — el grafo los usará para decidir si ejecutar.
TIER_THRESHOLDS: dict[SkillTier, float] = {"L1": 0.70, "L2": 0.85, "L3": 0.95}


class SkillInput(BaseModel):
    """Base para los inputs de cualquier skill. Subclasear por skill concreto."""


class SkillOutput(BaseModel):
    """Base para los outputs de cualquier skill. Subclasear por skill concreto."""


@dataclass(frozen=True)
class SkillContext:
    """Contexto inmutable que el grafo pasa a cada skill al ejecutar.

    Sprint 6.1: solo IDs universales.
    Sprint 6.3+: agregar credenciales de integración (shopify_domain, shopify_token, etc.)
    """

    tenant_id: str
    conversation_id: str


class Skill(ABC):
    """Clase base abstracta para todas las skills del agente.

    Las subclases deben definir todos los ClassVar sin default (slug, description,
    tier, input_schema, output_schema, default_threshold) y el método execute().
    """

    slug: ClassVar[str]
    description: ClassVar[str]
    tier: ClassVar[SkillTier]
    input_schema: ClassVar[type[SkillInput]]
    output_schema: ClassVar[type[SkillOutput]]
    requires_idempotency: ClassVar[bool] = False
    default_threshold: ClassVar[float]

    @abstractmethod
    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        """Ejecutar la skill. Debe ser idempotente si requires_idempotency=True."""
        ...

    def to_anthropic_tool(self) -> dict[str, Any]:
        """Serializa la skill como tool definition para la API de Anthropic."""
        return {
            "name": self.slug.replace(".", "_"),
            "description": self.description,
            "input_schema": self.input_schema.model_json_schema(),
        }
