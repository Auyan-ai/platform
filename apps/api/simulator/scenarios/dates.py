"""Fechas relativas a hoy para los fixtures: los plazos (devolución, retraso de envío) se
miden contra la fecha real, así que una fecha fija caduca y cambia el resultado."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def days_ago(days: int) -> str:
    """ISO 8601 UTC de las 10:00 de hace `days` días."""
    moment = datetime.now(UTC).replace(hour=10, minute=0, second=0, microsecond=0)
    return (moment - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
