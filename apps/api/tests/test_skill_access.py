"""Qué ve y qué puede ejecutar el turno (ADR 0013 §5): tools filtradas y veredicto del gate."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from apps.api.agents.nodes.reason import make_reason_node
from apps.api.services.identity import (
    Grant,
    IdentityContext,
    IdentityEvidence,
    order_claims,
    sender_identity,
)
from apps.api.services.skill_access import identity_verdict, skill_enabled, visible_skills
from apps.api.skills.base import Skill
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify.add_order_note import AddOrderNote
from apps.api.skills.shopify.cancel_order import CancelOrder
from apps.api.skills.shopify.get_order_status import GetOrderStatus
from apps.api.skills.shopify.get_product_info import GetProductInfo
from apps.api.skills.shopify.get_shop_policies import GetShopPolicies
from apps.api.skills.shopify.list_my_orders import ListMyOrders
from apps.api.skills.shopify.refund_partial import RefundPartial
from apps.api.skills.shopify.start_return import StartReturn
from apps.api.skills.shopify.tag_order import TagOrder
from apps.api.skills.shopify.update_shipping_address import UpdateShippingAddress

SALT = "s"
ALL_SKILLS: list[type[Skill]] = [
    GetProductInfo,
    GetShopPolicies,
    GetOrderStatus,
    ListMyOrders,
    TagOrder,
    AddOrderNote,
    CancelOrder,
    RefundPartial,
    StartReturn,
    UpdateShippingAddress,
]
SLUGS = [cls.slug for cls in ALL_SKILLS]
ENABLED = {slug: {"is_enabled": True} for slug in SLUGS}
PUBLIC = {GetProductInfo.slug, GetShopPolicies.slug}
VERIFIED = IdentityContext(
    sender_identity(IdentityEvidence(email="ana@example.com"), salt=SALT).grants
)
GUEST = IdentityContext((Grant("guest", "order_contact", order_id=1),))
NOBODY = IdentityContext()


@pytest.fixture(autouse=True)
def _real_skills() -> Any:
    SkillRegistry._reset()
    for cls in ALL_SKILLS:
        SkillRegistry.register(cls)
    yield
    SkillRegistry._reset()


def test_every_skill_that_touches_a_customer_declares_its_level() -> None:
    for cls in ALL_SKILLS:
        assert (cls.identity_scope == "public") == (cls.min_level is None), cls.slug


def test_registering_an_order_skill_without_level_is_rejected() -> None:
    class Broken(GetOrderStatus):
        slug = "test.broken"
        min_level = None

    with pytest.raises(ValueError, match="skill_without_min_level"):
        SkillRegistry.register(Broken)


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        (NOBODY, PUBLIC),
        (GUEST, set(SLUGS) - {ListMyOrders.slug}),
        (VERIFIED, set(SLUGS)),
    ],
    ids=["sin_identidad", "invitado", "verificado"],
)
def test_the_llm_only_sees_what_the_identity_allows(
    identity: IdentityContext, expected: set[str]
) -> None:
    assert set(visible_skills(SLUGS, ENABLED, identity)) == expected


def test_visible_skills_keep_the_aop_order() -> None:
    slugs = [CancelOrder.slug, GetProductInfo.slug, GetOrderStatus.slug]
    assert visible_skills(slugs, ENABLED, VERIFIED) == slugs


def test_a_switched_off_skill_is_not_visible_even_for_a_verified_sender() -> None:
    permissions = {**ENABLED, RefundPartial.slug: {"is_enabled": False}}
    visible = visible_skills(SLUGS, permissions, VERIFIED)
    assert RefundPartial.slug not in visible and CancelOrder.slug in visible


def test_a_skill_without_permission_row_is_not_visible() -> None:
    permissions = {k: v for k, v in ENABLED.items() if k != GetProductInfo.slug}
    assert GetProductInfo.slug not in visible_skills(SLUGS, permissions, VERIFIED)
    assert visible_skills(SLUGS, {}, VERIFIED) == []


def test_skill_enabled() -> None:
    assert skill_enabled({"is_enabled": True})
    assert not skill_enabled({"is_enabled": False})
    assert not skill_enabled({})
    assert not skill_enabled(None)


def test_unregistered_slugs_are_skipped() -> None:
    assert visible_skills(["test.ghost"], {"test.ghost": {"is_enabled": True}}, VERIFIED) == []


# ─── Veredicto del gate ───────────────────────────────────────────────────────

_ORDER = {"id": 1, "email": "ana@example.com"}
_CLAIMS = order_claims(_ORDER, salt=SALT)
_OTHER = order_claims({"id": 2, "email": "otra@example.com"}, salt=SALT)


@pytest.mark.parametrize(
    ("skill", "identity", "claims", "order_id", "expected"),
    [
        (GetProductInfo, NOBODY, None, None, None),
        (GetOrderStatus, VERIFIED, _CLAIMS, 1, None),
        (GetOrderStatus, VERIFIED, _OTHER, 2, "identity_required"),
        (GetOrderStatus, VERIFIED, None, None, "identity_required"),
        (GetOrderStatus, NOBODY, _CLAIMS, 1, "identity_required"),
        (CancelOrder, GUEST, _OTHER, 1, None),
        (CancelOrder, GUEST, _OTHER, 2, "identity_required"),
        (UpdateShippingAddress, GUEST, _OTHER, 1, "verified_required"),
        (UpdateShippingAddress, VERIFIED, _CLAIMS, 1, None),
        (ListMyOrders, VERIFIED, None, None, None),
        (ListMyOrders, GUEST, None, None, "identity_required"),
        (ListMyOrders, NOBODY, None, None, "identity_required"),
    ],
)
def test_gate_verdict(
    skill: type[Skill], identity: IdentityContext, claims: Any, order_id: int | None, expected: str
) -> None:
    assert identity_verdict(skill, identity, claims=claims, order_id=order_id) == expected


# ─── reason: las tools que llegan al LLM ──────────────────────────────────────


async def _tools_offered(
    fake_deps: Any,
    make_anthropic_response: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    permissions: dict[str, Any],
    identity: IdentityContext,
) -> list[str]:
    captured: dict[str, Any] = {}

    async def fake_call(**kwargs: Any) -> Any:
        captured["tools"] = kwargs["tools"]
        return make_anthropic_response(
            {"decision": "respond", "confidence": 0.9, "response_text": "x"}
        )

    monkeypatch.setattr(
        "apps.api.integrations.anthropic_client.call_claude_with_tools",
        AsyncMock(side_effect=fake_call),
    )
    state = {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "system_prompt": "Eres el agente de Acme.",
        "retrieved_chunks": [],
        "conversation_history": [{"role": "customer", "content": "hola"}],
        "model_used": "claude-sonnet-4-6",
        "tenant_config": {"escalation_threshold": 0.70},
        "allowed_skills": SLUGS,
        "tool_permissions": permissions,
        "identity": identity.to_state(),
        "tool_results": [],
    }
    out = await make_reason_node(fake_deps)(state)  # type: ignore[arg-type]
    assert "error" not in out
    return [tool["name"] for tool in captured["tools"]]


@pytest.mark.asyncio
async def test_a_switched_off_skill_never_reaches_the_tools_of_reason(
    fake_deps: Any, make_anthropic_response: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    permissions = {**ENABLED, RefundPartial.slug: {"is_enabled": False}}
    names = await _tools_offered(
        fake_deps, make_anthropic_response, monkeypatch, permissions=permissions, identity=VERIFIED
    )
    assert "shopify_refund_partial" not in names
    assert "shopify_cancel_order" in names and "respond_or_escalate" in names


@pytest.mark.asyncio
async def test_an_unverified_turn_only_gets_public_tools(
    fake_deps: Any, make_anthropic_response: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = await _tools_offered(
        fake_deps, make_anthropic_response, monkeypatch, permissions=ENABLED, identity=NOBODY
    )
    assert sorted(names) == sorted(
        ["respond_or_escalate", "shopify_get_product_info", "shopify_get_shop_policies"]
    )


@pytest.mark.asyncio
async def test_the_identity_note_reaches_the_prompt(
    fake_deps: Any, make_anthropic_response: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_call(**kwargs: Any) -> Any:
        captured["system"] = kwargs["system"]
        return make_anthropic_response(
            {"decision": "respond", "confidence": 0.9, "response_text": "x"}
        )

    monkeypatch.setattr(
        "apps.api.integrations.anthropic_client.call_claude_with_tools",
        AsyncMock(side_effect=fake_call),
    )
    state = {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "system_prompt": "Eres el agente de Acme.",
        "retrieved_chunks": [],
        "conversation_history": [{"role": "customer", "content": "hola"}],
        "model_used": "claude-sonnet-4-6",
        "tenant_config": {"escalation_threshold": 0.70},
        "allowed_skills": [],
        "tool_results": [],
        "identity_note": "Identidad: no verificada. NOTA-DE-PRUEBA",
    }
    await make_reason_node(fake_deps)(state)  # type: ignore[arg-type]
    assert "NOTA-DE-PRUEBA" in str(captured["system"])
