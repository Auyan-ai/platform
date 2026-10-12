"""Skill L3: cancela un pedido en Shopify.

Requiere aprobación humana (human_approval_required=True en tenant_tool_permissions).
El supervisor usa Opus antes de crear la solicitud de aprobación.

Todo lo que decide el resultado sale del pedido, no del LLM: un pedido cancelado o que
ya salió se rechaza antes de pedir aprobación y otra vez al ejecutar; se reembolsa si
hay cobro; se repone stock solo si no hay envío. Tras cancelar se relee el pedido y
el reembolso se clasifica por pasarela y estado (`ActionOutcome`).
"""

from __future__ import annotations

from typing import Any

from apps.api.integrations.shopify import RefundMode, ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._order_guard import (
    ActionOutcome,
    cancellation_verdict,
    ensure_order_changeable,
)
from pydantic import computed_field


class CancelOrderInput(SkillInput):
    order_id: int
    reason: str = "customer"
    send_email: bool = True


class CancelOrderOutput(SkillOutput):
    order_id: int
    cancelled: bool
    outcome: ActionOutcome
    detail: str | None = None
    refund_mode: RefundMode
    refund_gateway: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success(self) -> bool:
        return self.outcome.settled


@SkillRegistry.register
class CancelOrder(Skill):
    slug = "shopify.cancel_order"
    description = (
        "Cancela un pedido de Shopify. "
        "Usa esta skill SOLO cuando el cliente haya confirmado explícitamente que quiere cancelar "
        "y el pedido no haya sido enviado todavía. "
        "Requiere el ID numérico del pedido. "
        "El reembolso y la reposición de stock los decide el sistema según el pedido. "
        "NUNCA uses esta skill si el pedido está parcialmente enviado — escala en ese caso."
    )
    tier: SkillTier = "L3"
    input_schema = CancelOrderInput
    output_schema = CancelOrderOutput
    requires_idempotency = True
    default_threshold = 0.95

    async def prepare_approval(
        self, ctx: SkillContext, raw_input: dict[str, Any]
    ) -> dict[str, Any]:
        """Rechaza un pedido cancelado o enviado y añade a la tarjeta por dónde vuelve
        el dinero. `refund_payment`, si el LLM lo manda, no llega a la aprobación."""
        inputs = CancelOrderInput.model_validate(raw_input)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        snapshot = await adapter.get_order_snapshot(ctx.integration_ctx, inputs.order_id)
        ensure_order_changeable(snapshot, "cancel")
        route = snapshot.refund_route
        return {
            **inputs.model_dump(),
            "refund_mode": route.mode,
            "refund_gateway": route.gateway,
        }

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, CancelOrderInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        # La aprobación puede llevar horas en cola: el pedido pudo salir entretanto.
        before = await adapter.get_order_snapshot(ctx.integration_ctx, inputs.order_id)
        ensure_order_changeable(before, "cancel")
        await adapter.cancel_order(
            ctx.integration_ctx,
            before.order_id,
            reason=inputs.reason,
            email=inputs.send_email,
            refund=before.paid,
            restock=not before.has_active_fulfillment,
        )
        after = await adapter.get_order_snapshot(ctx.integration_ctx, before.order_id)
        verdict = cancellation_verdict(before, after)
        route = before.refund_route
        return CancelOrderOutput(
            order_id=after.order_id,
            cancelled=after.cancelled,
            outcome=verdict.outcome,
            detail=verdict.detail,
            refund_mode=route.mode,
            refund_gateway=route.gateway,
        )
