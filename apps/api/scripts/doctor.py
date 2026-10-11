"""Doctor de un tenant desde la terminal (misma lógica que `GET /tenants/me/doctor`).

Solo lecturas: catálogo de Postgres + APIs de Zendesk, Zernio, Shopify y Chatwoot. Sale con
código 1 si algún check falla, así que sirve como último paso de cualquier provisión.

Uso (desde apps/api con `.env.staging` cargado: DATABASE_URL, INTEGRATIONS_SECRET_KEY y
AUYAN_API_BASE_URL):

    python -m scripts.doctor --tenant marea-studio
    python -m scripts.doctor --tenant marea-studio --json
"""

# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.api.integrations import chatwoot, gorgias, zendesk  # noqa: F401  registran los helpdesks
from apps.api.scripts.configure_staging_integrations import (
    _connect_database,
    _integration_key_from_env,
    _require_env,
)
from apps.api.scripts.onboard_whatsapp import _resolve_tenant_id
from apps.api.services.doctor import DoctorReport, build_report, platform_checks
from apps.api.services.doctor.snapshot import load_tenant_snapshot

ICONS = {"ok": "✅", "warn": "⚠️ ", "fail": "❌", "skip": "⏭️ "}
GROUP_LABELS = {
    "platform": "Plataforma",
    "helpdesk": "Helpdesk",
    "whatsapp": "WhatsApp",
    "commerce": "Commerce",
    "operations": "Operación",
}


class _NoTracebackFormatter(logging.Formatter):
    def formatException(self, ei: object) -> str:
        return ""


def quiet_live_tracebacks() -> None:
    """Deja el aviso de cada check en vivo fallido en una línea, sin traceback, en la salida.

    Solo afecta al CLI: el record conserva `exc_info`, así que en la API (Cloud Run) el
    logger sigue registrando la excepción completa.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(_NoTracebackFormatter("%(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger("apps.api.services.doctor.live")
    logger.handlers[:] = [handler]
    logger.propagate = False


def render(report: DoctorReport) -> str:
    lines = [f"Doctor · {report.tenant_slug} · {ICONS[report.status]} {report.status.upper()}"]
    group = None
    for check in report.checks:
        if check.group != group:
            group = check.group
            lines.append(f"\n── {GROUP_LABELS[group]}")
        lines.append(f"{ICONS[check.status]} {check.title}")
        lines.extend(f"     {line}" for line in check.detail.splitlines())
        if check.hint:
            lines.append(f"     → {check.hint}")
    counts = report.counts
    lines.append(
        f"\n{counts['ok']} ok · {counts['warn']} avisos · {counts['fail']} fallos · "
        f"{counts['skip']} omitidos · {report.duration_ms} ms"
    )
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    quiet_live_tracebacks()
    key = _integration_key_from_env()
    started = time.monotonic()
    conn = await _connect_database(_require_env("DATABASE_URL"))
    try:
        tenant_id = await _resolve_tenant_id(conn, args.tenant)
        platform = await platform_checks(conn)
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
            snapshot = await load_tenant_snapshot(conn, tenant_id, key)
    finally:
        await conn.close()
    report = await build_report(
        snapshot,
        platform,
        api_base_url=os.environ.get("AUYAN_API_BASE_URL") or os.environ.get("API_BASE_URL"),
        started=started,
    )
    print(report.model_dump_json(indent=2) if args.json else render(report))
    return 1 if report.status == "fail" else 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Doctor de un tenant")
    parser.add_argument("--tenant", required=True, help="slug o id del tenant")
    parser.add_argument("--json", action="store_true", help="informe en JSON")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(run(_parse_args())))
