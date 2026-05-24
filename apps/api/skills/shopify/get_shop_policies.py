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
        adapter = ShopifyAdapter()
        raw_policies = await adapter.get_policies(ctx.integration_ctx)

        policies: list[PolicyInfo] = []
        for raw in raw_policies:
            url: str = raw.get("url", "")
            # Filtra por tipo si se especificó (extrae tipo del URL)
            if inputs.policy_type and inputs.policy_type not in url:
                continue
            policies.append(
                PolicyInfo(
                    title=raw.get("title", ""),
                    body=strip_html(raw.get("body") or "")[:2000],
                    url=url,
                )
            )
        return GetShopPoliciesOutput(policies=policies)
