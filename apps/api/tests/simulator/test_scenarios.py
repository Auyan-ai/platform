"""Tests de los scenario definitions — validan estructura, no comportamiento."""

from __future__ import annotations

from apps.api.simulator.scenarios.consulta_envio import SCENARIOS as CE
from apps.api.simulator.scenarios.default import SCENARIOS as DE
from apps.api.simulator.scenarios.edge_cases import SCENARIOS as EX
from apps.api.simulator.scenarios.profiles import PERSONAS
from apps.api.simulator.scenarios.returns import SCENARIOS as RE

ALL = CE + RE + DE + EX
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
        assert len(ALL) == 25

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
        assert len(DE) == 6
        for sc in DE:
            assert sc["id"].startswith("DE-")

    def test_ex_group(self):
        assert len(EX) == 4
        for sc in EX:
            assert sc["id"].startswith("EX-")
