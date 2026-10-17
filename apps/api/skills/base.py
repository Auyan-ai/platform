"""Skills framework — base abstractions.

Cada skill es una acción tipada del agente (L1 read, L2 write bajo riesgo, L3 write alto riesgo).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from apps.api.integrations.base import IntegrationContext
from apps.api.services.identity import (
    ClaimHash,
    IdentityContext,
    Level,
    order_claims,
)
from apps.api.services.identity_guest import GuestPolicy
from pydantic import BaseModel

SkillTier = Literal["L1", "L2", "L3"]
# Qué toca la skill (ADR 0013 §5): nada de un cliente, un pedido concreto o "mis pedidos".
IdentityScope = Literal["public", "order", "own_orders"]

# Confidence thresholds por tier — el grafo los usará para decidir si ejecutar.
TIER_THRESHOLDS: dict[SkillTier, float] = {"L1": 0.70, "L2": 0.85, "L3": 0.95}


class SkillRefusal(Exception):
    """La skill se niega, por una regla en código, a actuar sobre el estado actual.

    No vuelve al LLM: el cliente recibe `customer_message` tal cual y el caso se
    escala al equipo con `team_reason` como motivo.
    """

    def __init__(self, code: str, *, customer_message: str, team_reason: str) -> None:
        super().__init__(f"{code}: {team_reason}")
        self.code = code
        self.customer_message = customer_message
        self.team_reason = team_reason


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
    # Contacto VERIFICADO del remitente del mensaje (ADR 0013): el email solo si el
    # mensaje llega por correo o formulario web, el teléfono E.164 solo por WhatsApp.
    # Nunca lo que teclee el cliente o el LLM. Es el que usa `list_my_orders` para buscar.
    customer_email: str | None = field(default=None)
    customer_phone: str | None = field(default=None)
    # Grants del turno y sal con la que se hashean los claims. Qué pedidos puede ver y tocar
    # lo decide `identity.level_for(order_claims(...))`, no un email que llegue a la skill.
    identity: IdentityContext = field(default_factory=IdentityContext)
    claim_salt: str = field(default="", repr=False)
    # Canal de la conversación: en mensajería el gate L3 ofrece pasar el caso a una persona.
    channel: str | None = field(default=None)
    # Región por defecto para teléfonos sin prefijo (tenant_config/tenant_facts, "ES").
    phone_region: str = field(default="ES")
    # Límites del nivel `guest` y textos fijos del tenant (ADR 0013 §4 y §10).
    guest_policy: GuestPolicy = field(default_factory=GuestPolicy)
    tenant_facts: dict[str, Any] = field(default_factory=dict, repr=False)
    # Idioma de la conversación y defecto del tenant: los textos fijos al cliente
    # (`services/fixed_texts.py`) salen en este idioma.
    language: str = field(default="es")
    default_language: str = field(default="es")

    def order_claims(self, order: dict[str, Any]) -> frozenset[ClaimHash]:
        return order_claims(order, salt=self.claim_salt, region=self.phone_region)

    def level_for(self, order: dict[str, Any]) -> Level | None:
        """Nivel de la identidad del turno sobre este pedido (None = no es suyo)."""
        order_id = order.get("id")
        return self.identity.level_for(
            self.order_claims(order), int(order_id) if order_id is not None else None
        )


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
    # Identidad que exige (ADR 0013 §5). `public` no toca datos de un cliente. `order` actúa
    # sobre el pedido que indica `order_input_field` y `own_orders` lista los del propio
    # cliente. Toda skill que no es `public` declara `min_level`.
    identity_scope: ClassVar[IdentityScope] = "public"
    min_level: ClassVar[Level | None] = None
    order_input_field: ClassVar[str] = "order_id"
    # Skill del propio sistema: la ofrece el código a todo tenant con commerce, sin pasar por
    # el AOP ni por `tenant_tool_permissions`. Solo para skills de identidad, de tier L1.
    core: ClassVar[bool] = False

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
        pedido). Si lanza, no se crea la aprobación: un `SkillRefusal` escala con su
        mensaje fijo y cualquier otro error vuelve al LLM.
        """
        return raw_input

    def to_anthropic_tool(self) -> dict[str, Any]:
        """Serializa la skill como tool definition para la API de Anthropic."""
        return {
            "name": self.slug.replace(".", "_"),
            "description": self.description,
            "input_schema": self.input_schema.model_json_schema(),
        }
