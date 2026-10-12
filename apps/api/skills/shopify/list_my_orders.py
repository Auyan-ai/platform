"""Skill L1: lista los pedidos del remitente verificado del mensaje (ADR 0013)."""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.services.identity import normalize_phone
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._models import OrderSummary, map_order_summary


class ListMyOrdersInput(SkillInput):
    """Sin input: el contacto lo pone el código, nunca el LLM."""


class ListMyOrdersOutput(SkillOutput):
    verified_sender: bool
    orders: list[OrderSummary]
    total_found: int
    # Solo sin remitente verificado: qué decirle al cliente.
    note: str | None = None


NO_VERIFIED_SENDER_NOTE = (
    "No se pueden listar pedidos: este mensaje no llega desde un email o teléfono "
    "verificados. No busques pedidos con un email o teléfono que escriba el cliente. "
    "Explícale con amabilidad que, para ver sus pedidos, escriba desde el email con el "
    "que hizo la compra (o por WhatsApp desde el teléfono de la compra), u ofrécele "
    "pasar el caso a una persona del equipo."
)


@SkillRegistry.register
class ListMyOrders(Skill):
    slug = "shopify.list_my_orders"
    description = (
        "Lista los pedidos de Shopify de quien escribe, buscados con el email o el "
        "teléfono desde el que llega el mensaje. No recibe parámetros: nunca busca con "
        "un email que escriba el cliente. Devuelve hasta 10 pedidos recientes con "
        "estado, total y tracking. El total viene en la moneda en que pagó el cliente: "
        "úsala tal cual."
    )
    tier: SkillTier = "L1"
    input_schema = ListMyOrdersInput
    output_schema = ListMyOrdersOutput
    default_threshold = 0.70
    identity_scope = "own_orders"
    min_level = "verified"

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, ListMyOrdersInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        phone = normalize_phone(ctx.customer_phone, ctx.phone_region)
        if ctx.customer_email:
            raw_orders = await adapter.search_orders_by_email(
                ctx.integration_ctx, ctx.customer_email
            )
        elif phone:
            raw_orders = await adapter.search_orders_by_phone(ctx.integration_ctx, phone)
        else:
            return ListMyOrdersOutput(
                verified_sender=False, orders=[], total_found=0, note=NO_VERIFIED_SENDER_NOTE
            )
        # La búsqueda de Shopify no es la garantía: cada pedido pasa por los claims.
        own_orders = [
            map_order_summary(order) for order in raw_orders if ctx.level_for(order) == "verified"
        ]
        return ListMyOrdersOutput(
            verified_sender=True, orders=own_orders, total_found=len(own_orders)
        )
