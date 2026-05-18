"""Skill L2: añade/reemplaza la nota interna de un pedido de Shopify."""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyClient
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry


class AddOrderNoteInput(SkillInput):
    order_id: int
    note: str


class AddOrderNoteOutput(SkillOutput):
    success: bool
    order_id: int
    note: str


@SkillRegistry.register
class AddOrderNote(Skill):
    slug = "shopify.add_order_note"
    description = (
        "Añade o reemplaza la nota interna de un pedido de Shopify. "
        "Útil para registrar contexto operativo: incidencias, acuerdos con el cliente, "
        "instrucciones para el equipo de fulfillment. "
        "Requiere el ID numérico del pedido y el texto de la nota."
    )
    tier: SkillTier = "L2"
    input_schema = AddOrderNoteInput
    output_schema = AddOrderNoteOutput
    requires_idempotency = False
    default_threshold = 0.85

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, AddOrderNoteInput)
        if not ctx.shopify_domain or not ctx.shopify_token:
            raise ValueError("shopify_not_configured")
        shopify = ShopifyClient(ctx.shopify_domain, ctx.shopify_token)
        order = await shopify.add_order_note(inputs.order_id, inputs.note)
        return AddOrderNoteOutput(
            success=True,
            order_id=order["id"],
            note=order.get("note", inputs.note),
        )
