"""Genera borradores de reportes semanales para tenants activos.

Uso local:
    cd apps/api
    poetry run python -m scripts.generate_weekly_reports --dry-run
    poetry run python -m scripts.generate_weekly_reports

El cron corre los lunes 06:00 Europe/Madrid aproximadamente y genera el
reporte de la semana anterior (lunes-domingo). El envio sigue siendo manual:
Auyan revisa, aprueba y envia desde el dashboard.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.db.queries import create_or_refresh_weekly_report_draft  # noqa: E402

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)


@dataclass(frozen=True)
class TenantTarget:
    tenant_id: UUID
    slug: str
    name: str
    recipient_email: str | None


def previous_week(today: date) -> tuple[date, date]:
    """Retorna lunes-domingo de la semana anterior a `today`."""
    current_monday = today - timedelta(days=today.weekday())
    week_start = current_monday - timedelta(days=7)
    week_end = current_monday - timedelta(days=1)
    return week_start, week_end


def recipient_from_extra(extra: Any) -> str | None:
    """Extrae destinatario de reportes desde tenant_configurations.extra.

    Keys soportadas, en orden:
    - weekly_report_recipient_email
    - weekly_report_email
    - notif_email
    - notification_email
    """
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except json.JSONDecodeError:
            return None
    if not isinstance(extra, dict):
        return None

    for key in (
        "weekly_report_recipient_email",
        "weekly_report_email",
        "notif_email",
        "notification_email",
    ):
        value = extra.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def list_targets(conn: asyncpg.Connection, tenant_id: UUID | None) -> list[TenantTarget]:
    rows = await conn.fetch(
        """
        SELECT t.id, t.slug, t.name, tc.extra
          FROM tenants t
          LEFT JOIN tenant_configurations tc ON tc.tenant_id = t.id
         WHERE t.deleted_at IS NULL
           AND t.status = 'active'
           AND t.origin = 'client'
           AND ($1::uuid IS NULL OR t.id = $1)
         ORDER BY t.slug
        """,
        tenant_id,
    )
    return [
        TenantTarget(
            tenant_id=row["id"],
            slug=row["slug"],
            name=row["name"],
            recipient_email=recipient_from_extra(row["extra"]),
        )
        for row in rows
    ]


async def generate_reports(
    *,
    database_url: str,
    today: date,
    tenant_id: UUID | None,
    dry_run: bool,
) -> int:
    week_start, week_end = previous_week(today)
    conn = await asyncpg.connect(database_url)
    try:
        targets = await list_targets(conn, tenant_id)
        if not targets:
            print("No active tenants found.")
            return 0

        created = 0
        for target in targets:
            label = f"{target.slug} ({target.tenant_id})"
            if dry_run:
                print(
                    f"DRY RUN {label}: {week_start.isoformat()}..{week_end.isoformat()} "
                    f"recipient={target.recipient_email or 'unset'}"
                )
                continue

            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('app.tenant_id', $1, true)",
                    str(target.tenant_id),
                )
                report = await create_or_refresh_weekly_report_draft(
                    conn,
                    target.tenant_id,
                    week_start=week_start.isoformat(),
                    week_end=week_end.isoformat(),
                    created_by=None,
                    recipient_email=target.recipient_email,
                )
            created += 1
            print(f"Generated draft {report.id} for {label}: status={report.status}")

        print(f"Weekly report drafts processed: {created}/{len(targets)}")
        return created
    finally:
        await conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate weekly report drafts.")
    parser.add_argument("--dry-run", action="store_true", help="List targets without writing.")
    parser.add_argument("--tenant-id", type=UUID, default=None, help="Limit run to one tenant UUID.")
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=date.today(),
        help="Override current date for deterministic runs (YYYY-MM-DD).",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 2
    await generate_reports(
        database_url=database_url,
        today=args.today,
        tenant_id=args.tenant_id,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
