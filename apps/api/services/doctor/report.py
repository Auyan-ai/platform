"""Modelo del informe del doctor: una lista de checks con estado, detalle y cómo arreglarlo."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

CheckStatus = Literal["ok", "warn", "fail", "skip"]
CheckGroup = Literal["platform", "helpdesk", "whatsapp", "commerce", "operations"]

_SEVERITY: dict[CheckStatus, int] = {"skip": 0, "ok": 1, "warn": 2, "fail": 3}


class DoctorCheck(BaseModel):
    id: str
    group: CheckGroup
    title: str
    status: CheckStatus
    detail: str
    hint: str | None = None


class DoctorReport(BaseModel):
    tenant_id: UUID
    tenant_slug: str
    generated_at: datetime
    duration_ms: int
    status: CheckStatus
    counts: dict[CheckStatus, int]
    checks: list[DoctorCheck]


def worst_status(checks: list[DoctorCheck]) -> CheckStatus:
    """El peor estado de la lista; `ok` si no hay ninguno que cuente."""
    worst: CheckStatus = "ok"
    for check in checks:
        if _SEVERITY[check.status] > _SEVERITY[worst]:
            worst = check.status
    return worst


def count_statuses(checks: list[DoctorCheck]) -> dict[CheckStatus, int]:
    counts: dict[CheckStatus, int] = {"ok": 0, "warn": 0, "fail": 0, "skip": 0}
    for check in checks:
        counts[check.status] += 1
    return counts
