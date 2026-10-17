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

    def test_the_judge_sees_the_agent_sources(self):
        # Sin las fuentes, el judge tomaba por inventado el contacto de tenant_facts (OR-03).
        t = SimulatorTranscript(
            scenario=_make_scenario(),
            profile_name="cooperativo",
            tenant_facts={"support_email": "hola@tienda.es"},
            knowledge={"Envíos": "Península 24-48 h."},
        )
        text = format_for_sim_judge(t)
        assert "hola@tienda.es" in text
        assert "Envíos: Península 24-48 h." in text

    def test_the_judge_sees_why_a_skill_did_not_run(self):
        """RE-01: el judge leía `rejected_by_permissions` sin motivo y tomaba la puerta L3
        (aprobación humana pendiente) por una devolución rechazada."""
        from datetime import UTC, datetime

        from apps.api.db.models import SkillAuditLog

        def entry(slug: str, tier: str, error: str) -> SkillAuditLog:
            return SkillAuditLog(
                id=uuid4(), tenant_id=uuid4(), conversation_id=uuid4(), aop_slug="returns",
                aop_version=1, skill_slug=slug, skill_tier=tier, inputs_redacted={},
                inputs_hash="h", status="rejected_by_permissions", error_message=error,
                created_at=datetime.now(UTC),
            )

        t = SimulatorTranscript(scenario=_make_scenario(), profile_name="cooperativo")
        t.skill_log = [
            entry("shopify.start_return", "L3", "awaiting_human_approval"),
            entry("shopify.get_order_status", "L1", "identity_required"),
        ]
        lines = format_for_sim_judge(t).splitlines()
        assert (
            "- `shopify.start_return` (L3) → pendiente de aprobación humana: la puerta L3 "
            "del producto, no un rechazo"
        ) in lines
        assert "- `shopify.get_order_status` (L1) → rejected_by_permissions: identity_required" in lines
