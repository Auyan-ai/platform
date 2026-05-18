"""Construcción del transcript que recibe el judge.

Reglas de PII:
- Mensajes del cliente: raw (el judge necesita entender intent).
- Inputs/outputs de skills: redactados con el helper del audit log (PII Sprint 9.3).
- El AOP compilado se incluye para que el judge entienda qué instrucciones tenía el agente.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.api.db.models import (
    AopWithContent,
    Conversation,
    Message,
    SkillAuditLog,
)
from apps.api.services.pii import redact_inputs

_OUTCOME_MAP: dict[str, str] = {
    "resolved": "resuelto",
    "closed": "cerrado",
    "closed_abandoned": "cerrado por abandono",
    "escalated": "escalado a humano",
    "open": "abierto (sin resolver)",
    "pending": "pendiente de respuesta del cliente",
}


@dataclass(frozen=True)
class ConversationTranscript:
    conversation: Conversation
    messages: list[Message]
    skill_audit_entries: list[SkillAuditLog]
    aop: AopWithContent | None
    aop_compiled_prompt: str | None
    outcome: str
    escalation_reason: str | None = None


def build_transcript(
    conversation: Conversation,
    messages: list[Message],
    skill_audit_entries: list[SkillAuditLog],
    aop: AopWithContent | None,
    aop_compiled_prompt: str | None,
    pii_salt: str,
    escalation_reason: str | None = None,
) -> ConversationTranscript:
    redacted: list[SkillAuditLog] = []
    for entry in skill_audit_entries:
        if entry.inputs_redacted:
            new_inputs = redact_inputs(entry.inputs_redacted, pii_salt)
        else:
            new_inputs = entry.inputs_redacted
        redacted.append(
            SkillAuditLog(
                **{**entry.model_dump(), "inputs_redacted": new_inputs}
            )
        )

    return ConversationTranscript(
        conversation=conversation,
        messages=messages,
        skill_audit_entries=redacted,
        aop=aop,
        aop_compiled_prompt=aop_compiled_prompt,
        outcome=_OUTCOME_MAP.get(str(conversation.status), str(conversation.status)),
        escalation_reason=escalation_reason,
    )


def format_for_judge(transcript: ConversationTranscript) -> str:
    """Serializa el transcript como texto estructurado para el modelo judge."""
    lines: list[str] = []

    lines.append(f"# Conversación {transcript.conversation.id}")
    lines.append(f"Canal: {transcript.conversation.channel}")
    lines.append(f"Outcome: {transcript.outcome}")
    if transcript.escalation_reason:
        lines.append(f"Razón de escalado: {transcript.escalation_reason}")
    if transcript.aop:
        lines.append(
            f"AOP activo: {transcript.aop.slug} (v{transcript.aop.current_version})"
        )
    lines.append("")

    lines.append("## Transcript de mensajes")
    role_labels: dict[str, str] = {
        "customer": "Cliente",
        "agent_ai": "Agente AI",
        "agent_human": "Agente Humano",
        "system": "Sistema",
    }
    for msg in transcript.messages:
        label = role_labels.get(msg.role, msg.role)
        lines.append(f"**{label}:** {msg.content}")

    if transcript.skill_audit_entries:
        lines.append("")
        lines.append("## Skills ejecutadas")
        for entry in transcript.skill_audit_entries:
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


def transcript_has_l2_l3_skills(transcript: ConversationTranscript) -> bool:
    return any(
        e.skill_tier in ("L2", "L3") for e in transcript.skill_audit_entries
    )
