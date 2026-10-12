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
from apps.api.simulator.scenarios.orders import SCENARIOS as OR
from apps.api.simulator.scenarios.profiles import PERSONAS
from apps.api.simulator.scenarios.returns import SCENARIOS as RE

ALL = CE + RE + DE + EX + ID + OR
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
        assert len(ALL) == 37
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
        assert len(RE) == 7
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
