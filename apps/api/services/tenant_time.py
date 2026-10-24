"""Zona horaria de la tienda: `tenant_facts["timezone"]`, por defecto Europe/Madrid."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Zona por defecto del vertical e-commerce ES. Cada tenant la sobrescribe en tenant_facts.
DEFAULT_TENANT_TZ = "Europe/Madrid"


def tenant_zone(tenant_facts: Mapping[str, Any] | None) -> tuple[str, tzinfo]:
    """(nombre, zona). Una zona inválida cae a Europe/Madrid; sin tzdata, a UTC."""
    name = (tenant_facts or {}).get("timezone") or DEFAULT_TENANT_TZ
    for candidate in (name, DEFAULT_TENANT_TZ):
        try:
            return candidate, ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return "UTC", UTC
