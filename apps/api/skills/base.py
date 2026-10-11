"""Skills framework — base abstractions.

Cada skill es una acción tipada del agente (L1 read, L2 write bajo riesgo, L3 write alto riesgo).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from apps.api.integrations.base import IntegrationContext
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
    """Contexto inmutable que el grafo pasa a cada skill al ejecutar."""

    tenant_id: str
    conversation_id: str
    # IntegrationContext para skills de commerce (Shopify). None si no hay integración activa.
    integration_ctx: IntegrationContext | None = field(default=None)
    # Mock del adapter commerce, solo poblado en modo simulación (Sub-PR 0.10).
    # Tipo Any porque las skills llaman métodos fuera del protocolo CommerceProvider
    # (get_order_by_name, get_policies, etc.) y solo existe un provider commerce.
    commerce_mock: Any = field(default=None)
    # Email del cliente final de la conversación (end_customer). Las skills que
    # exponen datos personales del pedido (p. ej. la dirección) lo comparan con
    # el email del pedido: solo el dueño ve esos datos.
    customer_email: str | None = field(default=None)
    # Teléfono E.164 del cliente (WhatsApp) y canal de la conversación: el ownership de
    # un pedido pasa por email O teléfono (`services.identity.check_order_ownership`).
    customer_phone: str | None = field(default=None)
    channel: str | None = field(default=None)
    # Región por defecto para teléfonos sin prefijo (tenant_config/tenant_facts, "ES").
    phone_region: str = field(default="ES")


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

    async def prepare_approval(
        self, ctx: SkillContext, raw_input: dict[str, Any]
    ) -> dict[str, Any]:
        """Inputs que se guardan en la aprobación L3 y ve el humano. Por defecto, los
        del LLM tal cual.

        Una skill la sobrescribe para rechazar antes de pedir aprobación lo que fallaría
        al ejecutar, o para añadir datos derivados en código (p. ej. la moneda del
        pedido). Si lanza, el error vuelve al LLM y no se crea la aprobación.
        """
        return raw_input

    def to_anthropic_tool(self) -> dict[str, Any]:
        """Serializa la skill como tool definition para la API de Anthropic."""
        return {
            "name": self.slug.replace(".", "_"),
            "description": self.description,
            "input_schema": self.input_schema.model_json_schema(),
        }
