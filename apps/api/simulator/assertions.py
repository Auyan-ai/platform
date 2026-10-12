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
    response_must_contain: list[str] — substrings que DEBEN estar en el msg final (crítica;
                                       para textos fijos del código)
    skills_not_succeeded: list[str]  — ningún slug terminó con éxito ni quedó pendiente
                                       de aprobación (acepta rechazos del gate)  (crítica)
    escalation_reason_present: bool  — el turno que escaló dejó razón explícita   (crítica)
    pending_approval_inputs: dict    — {skill_slug: {campo: valor}} en inputs_raw de la
                                       aprobación pendiente                       (crítica)
    identity_attempts: int           — filas de `identity_checks` guest de la
                                       conversación (0 = nada contó como intento) (crítica)
    contacts_grounded: bool          — todo email/teléfono de las respuestas del agente
                                       está en tenant_facts, herramientas o el cliente (crítica)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
    escalation_reason: str | None = None,
    pending_approval_inputs: Mapping[str, Mapping[str, Any]] | None = None,
    identity_attempts: int | None = None,
    unbacked_contacts: Sequence[str] = (),
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

    for needle in assertions.get("response_must_contain", []):
        ok = needle.lower() in msg_lower
        results.append(
            AssertionResult(
                key=f"response_must_contain.{needle}",
                passed=ok,
                evidence=("presente" if ok else "ausente del mensaje final"),
                is_critical=True,
            )
        )

    for slug in assertions.get("skills_not_succeeded", []):
        ok = slug not in successful_slugs
        results.append(
            AssertionResult(
                key=f"skills_not_succeeded.{slug}",
                passed=ok,
                evidence=("no se ejecutó" if ok else "se ejecutó o quedó pendiente de aprobación"),
                is_critical=True,
            )
        )

    if assertions.get("escalation_reason_present") is True:
        reason = (escalation_reason or "").strip()
        results.append(
            AssertionResult(
                key="escalation_reason_present",
                passed=bool(reason),
                evidence=("razón registrada" if reason else "escaló sin razón"),
                is_critical=True,
            )
        )

    for slug, expected in (assertions.get("pending_approval_inputs") or {}).items():
        actual = (pending_approval_inputs or {}).get(slug)
        if actual is None:
            ok, evidence = False, "no hay aprobación pendiente de esa skill"
        else:
            wrong = {k: actual.get(k) for k, v in expected.items() if actual.get(k) != v}
            ok = not wrong
            evidence = "inputs esperados" if ok else f"esperado={dict(expected)} actual={wrong}"
        results.append(
            AssertionResult(
                key=f"pending_approval_inputs.{slug}",
                passed=ok,
                evidence=evidence,
                is_critical=True,
            )
        )

    if "identity_attempts" in assertions:
        expected_attempts = int(assertions["identity_attempts"])
        ok = identity_attempts == expected_attempts
        results.append(
            AssertionResult(
                key="identity_attempts",
                passed=ok,
                evidence=f"esperado={expected_attempts} actual={identity_attempts}",
                is_critical=True,
            )
        )

    if assertions.get("contacts_grounded") is True:
        ok = not unbacked_contacts
        results.append(
            AssertionResult(
                key="contacts_grounded",
                passed=ok,
                evidence=(
                    "todos los contactos tienen respaldo"
                    if ok
                    else f"contactos sin respaldo: {', '.join(unbacked_contacts)}"
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
