"""Skill L1: recupera el historial de pedidos de un cliente por email."""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._models import CustomerInfo, OrderSummary, map_order_summary


class GetCustomerHistoryInput(SkillInput):
    email: str


class GetCustomerHistoryOutput(SkillOutput):
    customer: CustomerInfo | None
    orders: list[OrderSummary]


@SkillRegistry.register
class GetCustomerHistory(Skill):
    slug = "shopify.get_customer_history"
    description = (
        "Devuelve el historial completo de pedidos de un cliente dado su email. "
        "Incluye datos del perfil (total gastado, número de pedidos) y lista de órdenes."
    )
    tier: SkillTier = "L1"
    input_schema = GetCustomerHistoryInput
    output_schema = GetCustomerHistoryOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, GetCustomerHistoryInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        raw_customer = await adapter.get_customer_by_email(ctx.integration_ctx, inputs.email)

        if raw_customer is None:
            return GetCustomerHistoryOutput(customer=None, orders=[])

        customer = CustomerInfo(
            customer_id=raw_customer["id"],
            email=raw_customer.get("email", inputs.email),
            first_name=raw_customer.get("first_name", ""),
            last_name=raw_customer.get("last_name", ""),
            orders_count=raw_customer.get("orders_count", 0),
            total_spent=raw_customer.get("total_spent", "0.00"),
        )
        raw_orders = await adapter.get_orders_by_customer_id(
            ctx.integration_ctx, raw_customer["id"]
        )
        orders = [map_order_summary(o) for o in raw_orders]
        return GetCustomerHistoryOutput(customer=customer, orders=orders)
