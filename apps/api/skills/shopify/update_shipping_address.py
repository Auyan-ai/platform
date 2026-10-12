"""Skill L3: actualiza la dirección de envío de un pedido.

Requiere aprobación humana. Un pedido cancelado o que ya salió se rechaza en código
antes de pedir aprobación y otra vez al ejecutar. Tras el cambio se relee el pedido:
solo se confirma la dirección que Shopify tiene guardada.
"""

from __future__ import annotations

from typing import Any

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._order_guard import (
    ActionOutcome,
    address_verdict,
    ensure_order_changeable,
)
from pydantic import computed_field


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
    order_id: int
    outcome: ActionOutcome
    detail: str | None = None
    # La dirección que Shopify tiene guardada tras el cambio, releída del pedido.
    new_address1: str | None = None
    new_address2: str | None = None
    new_zip: str | None = None
    new_city: str | None = None
    new_country: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success(self) -> bool:
        return self.outcome.settled


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
    identity_scope = "order"
    min_level = "verified"

    async def prepare_approval(
        self, ctx: SkillContext, raw_input: dict[str, Any]
    ) -> dict[str, Any]:
        inputs = UpdateShippingAddressInput.model_validate(raw_input)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        snapshot = await adapter.get_order_snapshot(ctx.integration_ctx, inputs.order_id)
        ensure_order_changeable(snapshot, "address")
        return raw_input

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, UpdateShippingAddressInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        # La aprobación puede llevar horas en cola: el pedido pudo salir entretanto.
        before = await adapter.get_order_snapshot(ctx.integration_ctx, inputs.order_id)
        ensure_order_changeable(before, "address")
        await adapter.update_shipping_address(
            ctx.integration_ctx,
            before.order_id,
            address1=inputs.address1,
            address2=inputs.address2,
            city=inputs.city,
            province=inputs.province,
            country=inputs.country,
            zip_code=inputs.zip_code,
            first_name=inputs.first_name,
            last_name=inputs.last_name,
        )
        after = await adapter.get_order_snapshot(ctx.integration_ctx, before.order_id)
        verdict = address_verdict(
            after, address1=inputs.address1, zip_code=inputs.zip_code, city=inputs.city
        )
        saved = after.shipping_address
        return UpdateShippingAddressOutput(
            order_id=after.order_id,
            outcome=verdict.outcome,
            detail=verdict.detail,
            new_address1=saved.get("address1"),
            new_address2=saved.get("address2"),
            new_zip=saved.get("zip"),
            new_city=saved.get("city"),
            new_country=saved.get("country"),
        )
