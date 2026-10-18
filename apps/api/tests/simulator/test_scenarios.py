"""Tests de los scenario definitions — validan estructura, no comportamiento."""

from __future__ import annotations

import re

import pytest
from apps.api.aops.canonical import CANONICAL_AOPS
from apps.api.simulator.runner import IDENTITY_MODES, scenario_identity_mode
from apps.api.simulator.scenarios import ALL_SCENARIOS, capabilities_by_name
from apps.api.simulator.scenarios.consulta_envio import SCENARIOS as CE
from apps.api.simulator.scenarios.default import SCENARIOS as DE
from apps.api.simulator.scenarios.edge_cases import SCENARIOS as EX
from apps.api.simulator.scenarios.identity import SCENARIOS as ID
from apps.api.simulator.scenarios.language import SCENARIOS as LG
from apps.api.simulator.scenarios.orders import SCENARIOS as OR
from apps.api.simulator.scenarios.profiles import PERSONAS
from apps.api.simulator.scenarios.returns import SCENARIOS as RE

ALL = CE + RE + DE + EX + ID + OR + LG
VALID_PROFILES = set(PERSONAS.keys())


class TestPersonas:
    def test_four_personas(self):
        assert len(PERSONAS) == 4

    def test_each_persona_has_required_fields(self):
        for key, p in PERSONAS.items():
            assert "tone" in p, f"{key} missing tone"
            assert "behavior" in p, f"{key} missing behavior"
            assert "give_up_after" in p, f"{key} missing give_up_after"
            assert isinstance(p["give_up_after"], int), f"{key}.give_up_after must be int"


class TestScenarioStructure:
    def test_total_count(self):
        assert len(ALL) == 43
        assert ALL == ALL_SCENARIOS

    def test_unique_ids(self):
        ids = [sc["id"] for sc in ALL]
        assert len(ids) == len(set(ids)), "Duplicate scenario IDs found"

    def test_all_have_required_fields(self):
        required = {"id", "name", "aop_slug", "profile", "goal", "initial_message", "expected_outcome"}
        for sc in ALL:
            missing = required - sc.keys()
            assert not missing, f"Scenario {sc.get('id')} missing: {missing}"

    def test_all_profiles_valid(self):
        for sc in ALL:
            assert sc["profile"] in VALID_PROFILES, (
                f"Scenario {sc['id']} references unknown profile '{sc['profile']}'"
            )

    def test_max_turns_positive(self):
        for sc in ALL:
            if "max_turns" in sc:
                assert sc["max_turns"] > 0, f"Scenario {sc['id']} has non-positive max_turns"

    def test_assertions_are_dicts(self):
        for sc in ALL:
            assert isinstance(sc.get("assertions", {}), dict), (
                f"Scenario {sc['id']} assertions must be dict"
            )

    def test_mock_fixtures_are_dicts(self):
        for sc in ALL:
            assert isinstance(sc.get("mock_fixtures", {}), dict), (
                f"Scenario {sc['id']} mock_fixtures must be dict"
            )


class TestScenarioGroups:
    def test_ce_group(self):
        assert len(CE) == 8
        for sc in CE:
            assert sc["id"].startswith("CE-")

    def test_re_group(self):
        assert len(RE) == 8
        for sc in RE:
            assert sc["id"].startswith("RE-")

    def test_de_group(self):
        assert len(DE) == 8
        for sc in DE:
            assert sc["id"].startswith("DE-")

    def test_ex_group(self):
        assert len(EX) == 5
        for sc in EX:
            assert sc["id"].startswith("EX-")

    def test_id_group(self):
        assert len(ID) == 6
        assert all(sc["id"].startswith("ID-") for sc in ID)

    def test_or_group(self):
        assert len(OR) == 3
        assert all(sc["id"].startswith("OR-") for sc in OR)


class TestCapabilityCatalogLinks:
    def test_every_scenario_points_to_a_canonical_aop(self):
        canonical = {a["slug"] for a in CANONICAL_AOPS}
        for sc in ALL:
            assert sc["aop_slug"] in canonical, f"{sc['id']}: aop_slug {sc['aop_slug']!r} no existe"

    def test_every_scenario_declares_capabilities_as_catalog_codes(self):
        for sc in ALL:
            assert isinstance(sc.get("capabilities"), list), f"{sc['id']}: falta capabilities"
            for code in sc["capabilities"]:
                assert re.fullmatch(r"[A-Z]{3}-\d\d", code), f"{sc['id']}: código {code!r}"

    def test_the_session_84_capabilities_each_have_a_scenario(self):
        covered = {code for sc in ALL for code in sc["capabilities"]}
        wanted = {
            "ORD-01", "ORD-04", "ORD-05", "ORD-06", "ORD-07", "IDN-01", "IDN-02",
            "IDN-03", "QLT-01", "QLT-02", "PRD-01",
        }
        assert wanted - covered == set()

    def test_capabilities_by_name_matches_the_scenarios(self):
        by_name = capabilities_by_name()
        assert by_name["ID-02: Email ajeno + número de pedido recibe el texto fijo"] == [
            "IDN-01",
            "IDN-02",
            "ORD-04",
        ]
        assert len(by_name) == len(ALL)

    def test_identity_mode_defaults_to_sender_and_rejects_unknown_values(self):
        assert scenario_identity_mode({}) == "sender"
        assert scenario_identity_mode({"shopify": {}}) == "sender"
        assert scenario_identity_mode({"identity": "chat"}) == "chat"
        assert set(IDENTITY_MODES) == {"sender", "chat"}
        with pytest.raises(ValueError):
            scenario_identity_mode({"identity": "guest"})

    def test_chat_scenarios_do_not_depend_on_the_simulated_sender_email(self):
        for sc in ALL:
            if sc["mock_fixtures"].get("identity") == "chat":
                order = sc["mock_fixtures"]["shopify"]["get_order_by_name"]
                assert order["email"], f"{sc['id']}: el pedido debe llevar su propio email"


_ORDER_LIST_METHODS = ("search_orders_by_email", "search_orders_by_phone", "get_orders_by_customer_id")


@pytest.mark.parametrize("sc", ALL, ids=lambda sc: sc["id"])
async def test_every_listed_order_has_its_shopify_name_and_resolves_by_it(sc):
    """`list_my_orders` muestra el `name` y el gate de identidad busca el pedido por él."""
    from apps.api.simulator.mocks import MockShopifyAdapter

    shopify = sc["mock_fixtures"].get("shopify", {})
    mock = MockShopifyAdapter(shopify)
    for method in _ORDER_LIST_METHODS:
        orders = shopify.get(method)
        for order in orders if isinstance(orders, list) else []:
            assert str(order.get("name", "")).startswith("#"), f"{sc['id']}: {order}"
            found = await mock.get_order_by_name(None, order["name"])
            assert found is not None and found["id"] == order["id"], sc["id"]


@pytest.mark.parametrize("sc", ALL, ids=lambda sc: sc["id"])
def test_every_policy_fixture_has_its_shopify_url(sc):
    """Shopify da el tipo de política en el URL y la skill filtra por él: sin URL, el
    filtro dejaba la lista vacía y el agente decía que la tienda no tenía política."""
    for policy in sc["mock_fixtures"].get("shopify", {}).get("get_policies") or []:
        assert "/policies/" in policy.get("url", ""), f"{sc['id']}: {policy.get('title')}"


@pytest.mark.parametrize("sc", ALL, ids=lambda sc: sc["id"])
def test_a_scenario_that_expects_an_l3_skill_expects_its_human_approval(sc):
    """RE-01 y DE-04 esperaban la devolución o el cambio de dirección ya hechos, pero
    `start_return` y `update_shipping_address` son L3: quedan pendientes de aprobación."""
    import apps.api.skills  # noqa: F401
    from apps.api.skills.registry import SkillRegistry

    assertions = sc.get("assertions", {})
    l3 = [s for s in assertions.get("skills_called", []) if SkillRegistry.get(s).tier == "L3"]
    if l3:
        assert assertions.get("must_have_pending_approval") is True, f"{sc['id']}: {l3}"
        assert assertions.get("outcome_is") in (None, "escalated"), sc["id"]


def _stale_row(name: str):
    from uuid import uuid4

    from apps.api.db.models import SimulationScenario

    return SimulationScenario(
        id=uuid4(), tenant_id=uuid4(), name=name, aop_slug="consulta_envio",
        user_profile_id=uuid4(), expected_outcome="viejo", mock_fixtures={"shopify": {}},
        assertions={}, max_turns=3,
    )


async def test_sync_brings_a_base_scenario_back_to_the_code(monkeypatch):
    """#358: CE-06 corría con el fixture guardado en staging, anterior al del código."""
    from unittest.mock import AsyncMock

    from apps.api.simulator import scenarios

    ce06 = next(sc for sc in ALL if sc["id"] == "CE-06")
    stale = _stale_row(ce06["name"])
    update = AsyncMock(side_effect=lambda conn, **kw: stale.model_copy(update=kw))
    monkeypatch.setattr(scenarios, "update_user_profile", AsyncMock())
    monkeypatch.setattr(scenarios, "update_simulation_scenario", update)

    synced = await scenarios.sync_scenario_from_code(object(), stale.tenant_id, stale)

    assert synced.mock_fixtures == ce06["mock_fixtures"]
    assert (synced.aop_slug, synced.max_turns) == ("order_status", 6)


async def test_sync_leaves_a_scenario_created_from_the_panel_alone(monkeypatch):
    from unittest.mock import AsyncMock

    from apps.api.simulator import scenarios

    update = AsyncMock()
    monkeypatch.setattr(scenarios, "update_simulation_scenario", update)
    custom = _stale_row("Mi escenario del panel")

    assert await scenarios.sync_scenario_from_code(object(), custom.tenant_id, custom) is custom
    assert update.await_count == 0
