"""Transcript del simulador para el judge.

Estructura diferente al slow_agent: incluye goal, expected_outcome y metadata
de cada turno (tokens, reasoning del simulador) además del texto de mensajes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from apps.api.db.models import SimulationScenario, SkillAuditLog

TurnRole = Literal["customer", "agent"]


@dataclass
class TranscriptTurn:
    role: TurnRole
    content: str
    turn_number: int
    # Solo para turnos de customer (del simulador)
    goal_achieved: bool = False
    give_up: bool = False
    internal_reasoning: str = ""
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class SimulatorTranscript:
    scenario: SimulationScenario
    profile_name: str
    turns: list[TranscriptTurn] = field(default_factory=list)
    termination_reason: str | None = None
    skill_log: list[SkillAuditLog] = field(default_factory=list)
    aop_compiled_prompt: str | None = None


def format_for_sim_judge(transcript: SimulatorTranscript) -> str:
    """Serializa el transcript como texto estructurado para el judge."""
    lines: list[str] = []

    scenario = transcript.scenario
    lines.append(f"# Simulación — Scenario: {scenario.name}")
    lines.append(f"AOP: {scenario.aop_slug}")
    lines.append(f"Perfil del cliente: {transcript.profile_name}")
    lines.append(f"Goal del cliente: {scenario.mock_fixtures.get('goal', '(ver persona)')}")
    lines.append(f"Outcome esperado: {scenario.expected_outcome}")
    lines.append(
        f"Terminación: {transcript.termination_reason or 'desconocida'} "
        f"({len(transcript.turns)} turnos)"
    )
    lines.append("")

    lines.append("## Transcript de mensajes")
    role_labels: dict[str, str] = {
        "customer": "Cliente (sintético)",
        "agent": "Agente AI",
    }
    for turn in transcript.turns:
        label = role_labels.get(turn.role, turn.role)
        lines.append(f"**[Turno {turn.turn_number}] {label}:** {turn.content}")
        if turn.role == "customer" and turn.internal_reasoning:
            lines.append(f"  _(razonamiento interno: {turn.internal_reasoning})_")

    if transcript.skill_log:
        lines.append("")
        lines.append("## Skills ejecutadas")
        for entry in transcript.skill_log:
            lines.append(
                f"- `{entry.skill_slug}` ({entry.skill_tier}) → {entry.status}"
            )
            if entry.inputs_redacted:
                lines.append(f"  inputs: {entry.inputs_redacted}")
            if entry.outputs_redacted:
                lines.append(f"  outputs: {entry.outputs_redacted}")

    if transcript.aop_compiled_prompt:
        lines.append("")
        lines.append("## Prompt compilado del AOP (instrucciones del agente)")
        lines.append(transcript.aop_compiled_prompt)

    return "\n".join(lines)


def transcript_to_list(transcript: SimulatorTranscript) -> list[dict]:
    """Serializa el transcript a lista de dicts para persistir en JSONB."""
    return [
        {
            "role": t.role,
            "content": t.content,
            "turn_number": t.turn_number,
            "goal_achieved": t.goal_achieved,
            "give_up": t.give_up,
            "internal_reasoning": t.internal_reasoning,
            "tokens_in": t.tokens_in,
            "tokens_out": t.tokens_out,
        }
        for t in transcript.turns
    ]
