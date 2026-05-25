"""Assertions programáticas del simulador — deterministas, sin LLM.

Corren antes del judge. Atrapan regresiones obvias barato. Si una assertion
crítica falla, el status final del run será 'failed' independiente del score
del judge (la decisión la toma el runner).

Las assertions vienen del JSONB `simulation_scenarios.assertions`. Tipos:

    skills_called:        list[str]  — cada slug debe aparecer con status='success'   (crítica)
    skills_not_called:    list[str]  — ningún slug debe aparecer                        (crítica)
    response_contains:    list[str]  — substrings en el último msg del agente           (no crítica)
    response_not_contains: list[str] — substrings ausentes del msg final     (crítica)
    outcome_is:           str        — resolved|escalated|abandoned|errored   (crítica)
    max_turns:            int        — turns_count <= N                       (no crítica)
    must_escalate:        bool       — True: debe escalar; False: NO debe escalar (crítica)
    must_have_pending_approval: bool — quedó pending_approval (gate L3)        (crítica)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.api.db.models import SkillAuditLog

# termination_reason → outcome canónico para la assertion `outcome_is`.
_OUTCOME_BY_TERMINATION: dict[str, str] = {
    "goal_achieved": "resolved",
    "escalated_by_agent": "escalated",
    "give_up": "abandoned",
    "max_turns": "abandoned",
    "agent_loop_detected": "abandoned",
    "error": "errored",
}

_ESCALATED_REASONS = {"escalated_by_agent"}


@dataclass(frozen=True)
class AssertionResult:
    key: str
    passed: bool
    evidence: str
    is_critical: bool


def check_assertions(
    *,
    assertions: dict,
    skill_log: list[SkillAuditLog],
    last_agent_message: str,
    termination_reason: str | None,
    turns_count: int,
    pending_approval_present: bool,
) -> list[AssertionResult]:
    """Evalúa todas las assertions del scenario. Retorna un resultado por cada una."""
    results: list[AssertionResult] = []
    # Para skills L3 con pending_approval, el status es "rejected_by_permissions"
    # con error_message="awaiting_human_approval". Se considera "invocada" a efectos
    # de testing — el gate de aprobación es el comportamiento esperado.
    successful_slugs = {
        e.skill_slug
        for e in skill_log
        if e.status == "success" or e.error_message == "awaiting_human_approval"
    }
    all_called_slugs = {e.skill_slug for e in skill_log}
    msg_lower = last_agent_message.lower()

    for slug in assertions.get("skills_called", []):
        ok = slug in successful_slugs
        results.append(
            AssertionResult(
                key=f"skills_called.{slug}",
                passed=ok,
                evidence=("ejecutada con éxito" if ok else "no ejecutada o falló"),
                is_critical=True,
            )
        )

    for slug in assertions.get("skills_not_called", []):
        ok = slug not in all_called_slugs
        results.append(
            AssertionResult(
                key=f"skills_not_called.{slug}",
                passed=ok,
                evidence=("no se llamó" if ok else "se llamó indebidamente"),
                is_critical=True,
            )
        )

    for needle in assertions.get("response_contains", []):
        ok = needle.lower() in msg_lower
        results.append(
            AssertionResult(
                key=f"response_contains.{needle}",
                passed=ok,
                evidence=("presente" if ok else "ausente del mensaje final"),
                is_critical=False,
            )
        )

    for needle in assertions.get("response_not_contains", []):
        ok = needle.lower() not in msg_lower
        results.append(
            AssertionResult(
                key=f"response_not_contains.{needle}",
                passed=ok,
                evidence=("ausente" if ok else "presente indebidamente"),
                is_critical=True,
            )
        )

    if "outcome_is" in assertions:
        expected = assertions["outcome_is"]
        actual = _OUTCOME_BY_TERMINATION.get(termination_reason or "", "unknown")
        ok = actual == expected
        results.append(
            AssertionResult(
                key="outcome_is",
                passed=ok,
                evidence=f"esperado={expected} actual={actual} (term={termination_reason})",
                is_critical=True,
            )
        )

    if "max_turns" in assertions:
        limit = int(assertions["max_turns"])
        ok = turns_count <= limit
        results.append(
            AssertionResult(
                key="max_turns",
                passed=ok,
                evidence=f"turns={turns_count} limite={limit}",
                is_critical=False,
            )
        )

    if "must_escalate" in assertions:
        escalated = (termination_reason in _ESCALATED_REASONS) or pending_approval_present
        if assertions["must_escalate"] is True:
            ok = escalated
        else:
            # must_escalate: False → el agente NO debe escalar.
            ok = not escalated
        results.append(
            AssertionResult(
                key="must_escalate",
                passed=ok,
                evidence=(
                    f"esperado_escala={assertions['must_escalate']} "
                    f"term={termination_reason} pending_approval={pending_approval_present}"
                ),
                is_critical=True,
            )
        )

    if assertions.get("must_have_pending_approval") is True:
        results.append(
            AssertionResult(
                key="must_have_pending_approval",
                passed=pending_approval_present,
                evidence=(
                    "pending_approval presente"
                    if pending_approval_present
                    else "no quedó pending_approval"
                ),
                is_critical=True,
            )
        )

    return results


def summarize(results: list[AssertionResult]) -> tuple[int, int, bool]:
    """Retorna (passed, total, all_critical_passed)."""
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    all_critical_passed = all(r.passed for r in results if r.is_critical)
    return passed, total, all_critical_passed
