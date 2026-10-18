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
from apps.api.skills.base import (
    ReconcileUnknown,
    Skill,
    SkillContext,
    SkillInput,
    SkillOutput,
    SkillTier,
)
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._order_guard import (
    ActionOutcome,
    cancellation_verdict,
    ensure_order_changeable,
    refund_transactions_verdict,
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
    identity_scope = "order"
    min_level = "guest"

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
        ensure_order_changeable(snapshot, "cancel", ctx)
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
        ensure_order_changeable(before, "cancel", ctx)
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

    async def reconcile(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput | None:
        """`orderCancel` no admite clave de idempotencia: consta aplicada si el pedido
        figura cancelado. El reembolso se juzga por todas las transacciones de reembolso
        del pedido, porque no queda la foto de antes de cancelar."""
        assert isinstance(inputs, CancelOrderInput)
        if not ctx.integration_ctx:
            raise ReconcileUnknown("shopify_not_configured")
        snapshot = await ShopifyAdapter().get_order_snapshot(ctx.integration_ctx, inputs.order_id)
        if not snapshot.cancelled:
            return None
        route = snapshot.refund_route
        verdict = refund_transactions_verdict(
            route, tuple(t for t in snapshot.transactions if t.kind == "refund")
        )
        return CancelOrderOutput(
            order_id=snapshot.order_id,
            cancelled=True,
            outcome=verdict.outcome,
            detail=verdict.detail,
            refund_mode=route.mode,
            refund_gateway=route.gateway,
        )
