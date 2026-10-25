"""Skill L2: añade/reemplaza la nota interna de un pedido de la tienda."""

from __future__ import annotations

from apps.api.integrations.commerce import CommerceCapability
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
    required_capability = CommerceCapability.ORDER_NOTES
    description = (
        "Añade o reemplaza la nota interna de un pedido de la tienda. "
        "Útil para registrar contexto operativo: incidencias, acuerdos con el cliente, "
        "instrucciones para el equipo de fulfillment. "
        "Requiere el ID numérico del pedido y el texto de la nota."
    )
    tier: SkillTier = "L2"
    input_schema = AddOrderNoteInput
    output_schema = AddOrderNoteOutput
    requires_idempotency = False
    default_threshold = 0.85
    identity_scope = "order"
    min_level = "guest"

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, AddOrderNoteInput)
        adapter = ctx.require_commerce()
        order = await adapter.add_order_note(ctx.integration_ctx, inputs.order_id, inputs.note)
        return AddOrderNoteOutput(
            success=True,
            order_id=order["id"],
            note=order.get("note", inputs.note),
        )
