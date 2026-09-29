"""Skill L3: actualiza la dirección de envío de un pedido.

Solo aplica si el pedido aún no ha salido del almacén.
Requiere aprobación humana.
"""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry


class UpdateShippingAddressInput(SkillInput):
    order_id: int
    # address1: calle y número. address2: piso, puerta, portal, escalera…
    address1: str
    address2: str | None = None
    city: str
    province: str
    zip_code: str
    # País determinista: por defecto se conserva el del pedido (lo resuelve el
    # adapter). Solo se envía cuando el cliente cambia de país explícitamente; el
    # LLM NO debe rellenarlo en cambios domésticos.
    country: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class UpdateShippingAddressOutput(SkillOutput):
    success: bool
    order_id: int
    new_address1: str
    new_address2: str | None = None
    new_zip: str | None = None
    new_city: str
    new_country: str


@SkillRegistry.register
class UpdateShippingAddress(Skill):
    slug = "shopify.update_shipping_address"
    description = (
        "Actualiza la dirección de envío de un pedido de Shopify. "
        "Usa esta skill SOLO cuando el pedido no haya sido enviado todavía. "
        "Requiere el ID del pedido y la dirección completa nueva. "
        "Si el pedido ya tiene tracking activo, escala — no intentes cambiar la dirección."
    )
    tier: SkillTier = "L3"
    input_schema = UpdateShippingAddressInput
    output_schema = UpdateShippingAddressOutput
    requires_idempotency = True
    default_threshold = 0.95

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, UpdateShippingAddressInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        order = await adapter.update_shipping_address(
            ctx.integration_ctx,
            inputs.order_id,
            address1=inputs.address1,
            address2=inputs.address2,
            city=inputs.city,
            province=inputs.province,
            country=inputs.country,
            zip_code=inputs.zip_code,
            first_name=inputs.first_name,
            last_name=inputs.last_name,
        )
        shipping = order.get("shipping_address") or {}
        return UpdateShippingAddressOutput(
            success=True,
            order_id=order["id"],
            new_address1=shipping.get("address1", inputs.address1),
            new_address2=shipping.get("address2", inputs.address2),
            new_zip=shipping.get("zip", inputs.zip_code),
            new_city=shipping.get("city", inputs.city),
            new_country=(
                shipping.get("country") or shipping.get("country_code") or inputs.country or ""
            ),
        )
