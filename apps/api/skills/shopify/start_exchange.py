"""Skill L3: cambio en el mismo pedido (`returnCreate` con `exchangeLineItems`, ADR 0014 §7).

Siempre con aprobación humana: envía mercancía nueva.
"""

from __future__ import annotations

from apps.api.services.returns import RequestedExchange
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify.start_return import StartReturnInput, _ReturnSkill
from pydantic import Field


class StartExchangeInput(StartReturnInput):
    exchange_items: list[RequestedExchange] = Field(
        min_length=1,
        description="Lo que recibe a cambio: `variant_id` de get_product_info y cantidad.",
    )


@SkillRegistry.register
class StartExchange(_ReturnSkill):
    slug = "shopify.start_exchange"
    description = (
        "Abre un cambio en un pedido de Shopify: el cliente devuelve artículos y recibe otros "
        "en el mismo pedido. Úsala cuando el cliente haya confirmado qué devuelve, cuántos, "
        "el motivo y qué variante quiere a cambio (`variant_id` de get_product_info). "
        "`reason_code` es uno de los códigos de la política de la tienda que tienes en el "
        "turno. El sistema comprueba si la tienda admite ese cambio, la disponibilidad y la "
        "diferencia de precio, y siempre lo pasa a aprobación del equipo."
    )
    input_schema = StartExchangeInput

    def _exchange(self, inputs: StartReturnInput) -> tuple[RequestedExchange, ...]:
        assert isinstance(inputs, StartExchangeInput)
        return tuple(inputs.exchange_items)
