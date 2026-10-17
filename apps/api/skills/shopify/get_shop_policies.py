"""Skill L1: devuelve las políticas de la tienda (devolución, envío, privacidad, etc.)."""

from __future__ import annotations

from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify._models import PolicyInfo, strip_html


class GetShopPoliciesInput(SkillInput):
    policy_type: str | None = None  # ej. "refund-policy", None = todas


class GetShopPoliciesOutput(SkillOutput):
    policies: list[PolicyInfo]


@SkillRegistry.register
class GetShopPolicies(Skill):
    slug = "shopify.get_shop_policies"
    description = (
        "Devuelve las políticas oficiales de la tienda (devolución, envío, privacidad, términos). "
        "Úsala cuando el cliente pregunte por garantías, devoluciones o condiciones de compra. "
        "Puedes filtrar por tipo pasando policy_type (ej. 'refund-policy')."
    )
    tier: SkillTier = "L1"
    input_schema = GetShopPoliciesInput
    output_schema = GetShopPoliciesOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, GetShopPoliciesInput)
        if not ctx.integration_ctx:
            raise ValueError("shopify_not_configured")
        adapter = ctx.commerce_mock or ShopifyAdapter()
        raw_policies = await adapter.get_policies(ctx.integration_ctx)

        policies = [
            PolicyInfo(
                title=raw.get("title", ""),
                body=strip_html(raw.get("body") or "")[:2000],
                url=raw.get("url", ""),
            )
            for raw in raw_policies
        ]
        # Filtra por tipo (va en el URL de Shopify: .../policies/refund-policy). Si el tipo
        # no coincide con ninguna, devuelve todas: mejor de más que un "no hay política".
        wanted = [p for p in policies if inputs.policy_type and inputs.policy_type in p.url]
        return GetShopPoliciesOutput(policies=wanted or policies)
