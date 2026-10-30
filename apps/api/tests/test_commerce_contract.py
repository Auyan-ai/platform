"""Contrato de comercio (ADR 0016): las skills no conocen el proveedor y cada una declara la
capacidad que necesita; lo que la tienda del turno no sabe hacer ni se ofrece ni se ejecuta."""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
from collections.abc import Generator
from pathlib import Path
from typing import Any

import apps.api.skills.shopify as shopify_skills
import pytest
from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes.execute_skill import make_execute_skill_node
from apps.api.agents.nodes.reason import _visible_skills
from apps.api.integrations.commerce import ALL_CAPABILITIES, CommerceCapability
from apps.api.integrations.demo_catalog import DemoCatalogAdapter
from apps.api.integrations.shopify import ShopifyAdapter
from apps.api.integrations.woocommerce import WooCommerceAdapter
from apps.api.services.fixed_texts import fixed_text
from apps.api.services.identity import IdentityContext
from apps.api.services.skill_access import visible_skills
from apps.api.simulator.mocks import MockShopifyAdapter
from apps.api.simulator.scenarios.returns import SCENARIOS as RETURN_SCENARIOS
from apps.api.skills.base import Skill
from apps.api.skills.identity.check_order_contact import CheckOrderContact
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify.get_order_status import GetOrderStatus
from apps.api.skills.shopify.get_product_info import GetProductInfo
from apps.api.skills.shopify.get_shop_policies import GetShopPolicies
from apps.api.skills.shopify.start_exchange import StartExchange
from apps.api.skills.shopify.start_return import StartReturn
from apps.api.skills.shopify.tag_order import TagOrder
from apps.api.tests.identity_support import identity_state

SKILLS_DIR = Path(shopify_skills.__file__).parent
# Módulos de adapters concretos: una skill solo habla con `ctx.commerce`.
CONCRETE_ADAPTER_MODULES = (
    "apps.api.integrations.shopify",
    "apps.api.integrations.demo_catalog",
    "apps.api.integrations.woocommerce",
    "apps.api.simulator.mocks",
)
TENANT = "11111111-1111-1111-1111-111111111111"


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def _shopify_skill_classes() -> list[type[Skill]]:
    classes: list[type[Skill]] = []
    for info in pkgutil.iter_modules([str(SKILLS_DIR)]):
        module = importlib.import_module(f"{shopify_skills.__name__}.{info.name}")
        classes.extend(
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, Skill) and obj.__module__ == module.__name__ and "slug" in vars(obj)
        )
    return classes


@pytest.mark.parametrize("path", sorted(SKILLS_DIR.glob("*.py")), ids=lambda p: p.name)
def test_no_commerce_skill_imports_a_concrete_adapter(path: Path) -> None:
    concrete = _imported_modules(path) & set(CONCRETE_ADAPTER_MODULES)
    assert concrete == set(), f"{path.name} importa un adapter concreto: {concrete}"


def test_every_commerce_skill_declares_its_capability() -> None:
    classes = _shopify_skill_classes()
    assert len(classes) == 11
    missing = [cls.slug for cls in classes if cls.required_capability is None]
    assert missing == []


def test_capability_of_each_skill() -> None:
    required = {cls.slug: cls.required_capability for cls in _shopify_skill_classes()}
    assert required == {
        "shopify.get_order_status": CommerceCapability.ORDER_READ,
        "shopify.list_my_orders": CommerceCapability.ORDER_READ,
        "shopify.get_product_info": CommerceCapability.PRODUCT_READ,
        "shopify.get_shop_policies": CommerceCapability.POLICIES,
        "shopify.add_order_note": CommerceCapability.ORDER_NOTES,
        "shopify.tag_order": CommerceCapability.ORDER_TAGS,
        "shopify.cancel_order": CommerceCapability.CANCEL,
        "shopify.update_shipping_address": CommerceCapability.SHIPPING_ADDRESS,
        "shopify.refund_partial": CommerceCapability.REFUNDS,
        "shopify.start_return": CommerceCapability.RETURNS,
        "shopify.start_exchange": CommerceCapability.EXCHANGES,
    }
    assert CheckOrderContact.required_capability is CommerceCapability.ORDER_READ


def test_adapters_declare_their_capabilities() -> None:
    assert ShopifyAdapter.capabilities == ALL_CAPABILITIES
    assert MockShopifyAdapter().capabilities == ALL_CAPABILITIES
    assert WooCommerceAdapter.capabilities == ALL_CAPABILITIES - {
        CommerceCapability.ORDER_TAGS,
        CommerceCapability.RETURNS,
        CommerceCapability.EXCHANGES,
    }
    assert MockShopifyAdapter({"_provider": "woocommerce"}).capabilities == (
        WooCommerceAdapter.capabilities
    )
    assert DemoCatalogAdapter.capabilities == frozenset({CommerceCapability.PRODUCT_READ})


SLUGS = [GetOrderStatus.slug, GetProductInfo.slug, GetShopPolicies.slug]
ENABLED = {slug: {"is_enabled": True} for slug in SLUGS}


@pytest.fixture
def _registry() -> Generator[None, None, None]:
    saved = dict(SkillRegistry._by_slug)
    for cls in (GetOrderStatus, GetProductInfo, GetShopPolicies, CheckOrderContact):
        SkillRegistry.register(cls)
    yield
    SkillRegistry._by_slug.clear()
    SkillRegistry._by_slug.update(saved)


@pytest.mark.usefixtures("_registry")
def test_skills_the_store_cannot_do_are_not_offered() -> None:
    demo = DemoCatalogAdapter.capabilities

    assert visible_skills(SLUGS, ENABLED, IdentityContext(), capabilities=demo) == [
        GetProductInfo.slug
    ]
    # Sin tienda no se filtra: la skill se ofrece y falla con `commerce_not_configured`.
    assert visible_skills(SLUGS, ENABLED, IdentityContext(), capabilities=None) == [
        GetProductInfo.slug,
        GetShopPolicies.slug,
    ]


def _demo_state(**extra: Any) -> dict[str, Any]:
    return identity_state(
        email="cliente@example.com",
        tenant_id=TENANT,
        commerce_mode="demo_catalog",
        demo_catalog_domain="thinkingmu.com",
        allowed_skills=SLUGS,
        tool_permissions={
            slug: {"is_enabled": True, "human_approval_required": False} for slug in SLUGS
        },
        tool_results=[],
        tool_iterations=0,
        **extra,
    )


@pytest.mark.usefixtures("_registry")
def test_the_turn_offers_only_what_its_adapter_can_do() -> None:
    assert _visible_skills(_demo_state()) == [GetProductInfo.slug]


@pytest.mark.usefixtures("_registry")
async def test_a_call_without_the_capability_escalates_with_its_reason(
    fake_deps: AgentDependencies,
) -> None:
    pending = {"id": "toolu_1", "slug": GetOrderStatus.slug, "input": {"order_identifier": "1001"}}

    out = await make_execute_skill_node(fake_deps)(_demo_state(pending_tool_call=pending))

    assert out["decision"] == "escalate"
    assert out["agent_response"] == fixed_text("commerce_capability_missing", "es")
    assert out["escalation_reason"] == (
        "commerce_capability_missing: la tienda no admite `order_read`, que necesita "
        "shopify.get_order_status. Hay que gestionarlo a mano en la tienda."
    )
    assert out["tool_results"][-1]["error"] == "skill_refused: commerce_capability_missing"
    audit = fake_deps.audit_logger.entries[-1]  # type: ignore[attr-defined]
    assert audit["status"] == "rejected_by_permissions"
    assert audit["error_message"] == "skill_refused: commerce_capability_missing"
    event = fake_deps.reasoning_tracker.events[-1]  # type: ignore[attr-defined]
    assert event["detail"]["refused"] == "commerce_capability_missing"


def test_a_skill_that_touches_an_order_also_needs_order_read() -> None:
    from apps.api.services.skill_access import capability_missing
    from apps.api.skills.shopify.cancel_order import CancelOrder

    only_cancel = frozenset({CommerceCapability.CANCEL})
    both = frozenset({CommerceCapability.CANCEL, CommerceCapability.ORDER_READ})

    assert capability_missing(CancelOrder, only_cancel) == CommerceCapability.ORDER_READ
    assert capability_missing(CancelOrder, both) is None
    assert capability_missing(GetProductInfo, frozenset({CommerceCapability.PRODUCT_READ})) is None


# ─── Tenant WooCommerce en el simulador (RE-09): sin devoluciones, escala ─────

_WC_SCENARIO = next(sc for sc in RETURN_SCENARIOS if sc["id"] == "RE-09")
_RETURN_SLUGS = [GetOrderStatus.slug, StartReturn.slug, StartExchange.slug, TagOrder.slug]


@pytest.fixture
def _return_registry() -> Generator[None, None, None]:
    saved = dict(SkillRegistry._by_slug)
    for cls in (GetOrderStatus, StartReturn, StartExchange, TagOrder, CheckOrderContact):
        SkillRegistry.register(cls)
    yield
    SkillRegistry._by_slug.clear()
    SkillRegistry._by_slug.update(saved)


def _woocommerce_sim_state(**extra: Any) -> dict[str, Any]:
    return identity_state(
        email="cliente@example.com",
        tenant_id=TENANT,
        simulation_mode=True,
        simulation_fixtures=_WC_SCENARIO["mock_fixtures"],
        allowed_skills=_RETURN_SLUGS,
        tool_permissions={
            slug: {"is_enabled": True, "human_approval_required": False} for slug in _RETURN_SLUGS
        },
        tool_results=[],
        tool_iterations=0,
        **extra,
    )


@pytest.mark.usefixtures("_return_registry")
def test_a_woocommerce_tenant_is_not_offered_returns_exchanges_or_tags() -> None:
    assert _visible_skills(_woocommerce_sim_state()) == [GetOrderStatus.slug]


@pytest.mark.usefixtures("_return_registry")
async def test_a_return_on_woocommerce_escalates_with_its_reason(
    fake_deps: AgentDependencies,
) -> None:
    pending = {
        "id": "toolu_1",
        "slug": StartReturn.slug,
        "input": {"order_id": 1234, "lines": [], "reason_code": "talla"},
    }

    out = await make_execute_skill_node(fake_deps)(
        _woocommerce_sim_state(pending_tool_call=pending)
    )

    assert out["decision"] == "escalate"
    assert out["agent_response"] == fixed_text("commerce_capability_missing", "es")
    assert out["escalation_reason"].startswith(
        "commerce_capability_missing: la tienda no admite `returns`, que necesita "
        "shopify.start_return."
    )
