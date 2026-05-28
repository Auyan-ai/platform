"""Despacha jobs due de la cola `outbound_email_jobs`.

Uso local:
    cd apps/api
    poetry run python -m scripts.dispatch_outbound_email --limit 25

Requiere `DATABASE_URL` y `POSTMARK_API_TOKEN`. Si Postmark no está configurado,
sale sin reclamar jobs para no consumir intentos en desarrollo local.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.integrations.postmark import PostmarkEmailAdapter  # noqa: E402
from apps.api.services.email_sender import EmailSender  # noqa: E402
from apps.api.services.outbound_email_dispatcher import (  # noqa: E402
    dispatch_due_outbound_emails,
)

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch outbound email jobs.")
    parser.add_argument("--limit", type=int, default=25, help="Max jobs to claim.")
    return parser.parse_args()


async def dispatch(*, database_url: str, limit: int) -> int:
    token = os.environ.get("POSTMARK_API_TOKEN", "").strip()
    if not token:
        print("POSTMARK_API_TOKEN is not configured; no jobs claimed.")
        return 0

    adapter = PostmarkEmailAdapter(
        server_token=token,
        from_email=os.environ.get("POSTMARK_FROM_EMAIL", "noreply@auyan.ai"),
        from_name=os.environ.get("POSTMARK_FROM_NAME", "Auyan"),
    )
    email_sender = EmailSender(adapter)
    conn = await asyncpg.connect(database_url)
    try:
        result = await dispatch_due_outbound_emails(
            conn,
            email_sender,
            limit=limit,
        )
    finally:
        await conn.close()

    print(
        "Outbound email dispatch: "
        f"claimed={result.claimed} sent={result.sent} "
        f"retry_scheduled={result.retry_scheduled} failed={result.failed}"
    )
    return result.claimed


async def main() -> int:
    args = parse_args()
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 2
    await dispatch(database_url=database_url, limit=args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
