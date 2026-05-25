"""Tests del transcript.py del simulador."""

from __future__ import annotations

from uuid import uuid4

from apps.api.simulator.transcript import (
    SimulatorTranscript,
    TranscriptTurn,
    format_for_sim_judge,
    transcript_to_list,
)


def _make_scenario():

    from apps.api.db.models import SimulationScenario

    return SimulationScenario(
        id=uuid4(),
        tenant_id=uuid4(),
        name="CE-01",
        aop_slug="consulta_envio",
        user_profile_id=uuid4(),
        expected_outcome="El agente da el tracking.",
        mock_fixtures={},
        assertions={},
        max_turns=8,
    )


class TestTranscriptToList:
    def test_serializes_all_turns(self):
        scenario = _make_scenario()
        t = SimulatorTranscript(scenario=scenario, profile_name="cooperativo")
        t.turns.append(TranscriptTurn(role="customer", content="Hola", turn_number=0))
        t.turns.append(TranscriptTurn(role="agent", content="¿En qué ayudo?", turn_number=1))
        result = transcript_to_list(t)
        assert len(result) == 2
        assert result[0]["role"] == "customer"
        assert result[1]["role"] == "agent"
        assert result[0]["content"] == "Hola"

    def test_empty_transcript(self):
        scenario = _make_scenario()
        t = SimulatorTranscript(scenario=scenario, profile_name="vago")
        result = transcript_to_list(t)
        assert result == []


class TestFormatForSimJudge:
    def test_includes_scenario_metadata(self):
        scenario = _make_scenario()
        t = SimulatorTranscript(
            scenario=scenario,
            profile_name="cooperativo",
            termination_reason="goal_achieved",
        )
        t.turns.append(TranscriptTurn(role="customer", content="msg", turn_number=0))
        t.turns.append(TranscriptTurn(role="agent", content="respuesta", turn_number=1))
        text = format_for_sim_judge(t)
        assert "CE-01" in text
        assert "consulta_envio" in text
        assert "goal_achieved" in text
        assert "msg" in text
        assert "respuesta" in text

    def test_includes_aop_prompt_when_present(self):
        scenario = _make_scenario()
        t = SimulatorTranscript(
            scenario=scenario,
            profile_name="impaciente",
            aop_compiled_prompt="Sé amable con el cliente.",
        )
        text = format_for_sim_judge(t)
        assert "Sé amable" in text
