"""Skill L3: cambio en el mismo pedido (`returnCreate` con `exchangeLineItems`, ADR 0014 §7).

Si pasa por aprobación humana lo decide la política del tenant (`exchanges.requires_approval`
y `evidence_requires_approval`), además del piso L3 de `tenant_tool_permissions`.
"""

from __future__ import annotations

from apps.api.integrations.commerce import CommerceCapability
from apps.api.services.returns import RequestedExchange
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify.start_return import StartReturnInput, _ReturnSkill
from pydantic import Field


class StartExchangeInput(StartReturnInput):
    exchange_items: list[RequestedExchange] = Field(
        min_length=1,
        description=(
            "Lo que recibe a cambio: `variant_id` de get_product_info y cantidad, cada "
            "variante una vez y como mucho tantas unidades como devuelve."
        ),
    )


@SkillRegistry.register
class StartExchange(_ReturnSkill):
    slug = "shopify.start_exchange"
    required_capability = CommerceCapability.EXCHANGES
    description = (
        "Abre un cambio en un pedido de la tienda: el cliente devuelve artículos y recibe otros "
        "en el mismo pedido. Úsala cuando el cliente haya confirmado qué devuelve, cuántos, "
        "el motivo y qué variante quiere a cambio (`variant_id` de get_product_info). "
        "`reason_code` es uno de los códigos de la política de la tienda que tienes en el "
        "turno. El sistema comprueba si la tienda admite ese cambio, la disponibilidad y la "
        "diferencia de precio, y decide si pasa por aprobación del equipo."
    )
    input_schema = StartExchangeInput

    def _exchange(self, inputs: StartReturnInput) -> tuple[RequestedExchange, ...]:
        assert isinstance(inputs, StartExchangeInput)
        return tuple(inputs.exchange_items)
