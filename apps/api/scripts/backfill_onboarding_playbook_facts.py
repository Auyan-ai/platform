"""Rellena tenant_playbook y tenant_facts con los datos de step_data del onboarding.

Uso (one-shot retroactivo):
    cd apps/api
    poetry run python -m scripts.backfill_onboarding_playbook_facts
    poetry run python -m scripts.backfill_onboarding_playbook_facts --tenant-id 683246c2-10ce-4f6c-a299-5053f32f8c01
    poetry run python -m scripts.backfill_onboarding_playbook_facts --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

import asyncpg
from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)

_PLAYBOOK_KEYS = ("voice_traits", "forbidden_phrases", "launch_notes")
_FACTS_KEYS = (
    "business_hours", "support_email", "support_phone",
    "return_window_days", "company_name", "website_url", "primary_contact",
)


async def backfill(tenant_id: UUID | None, dry_run: bool) -> None:
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn)
    try:
        if tenant_id:
            rows = await conn.fetch(
                "SELECT tenant_id, step_data FROM tenant_onboarding WHERE tenant_id = $1",
                tenant_id,
            )
        else:
            rows = await conn.fetch("SELECT tenant_id, step_data FROM tenant_onboarding")

        print(f"Tenants encontrados: {len(rows)}")
        for row in rows:
            tid = row["tenant_id"]
            raw = row["step_data"]
            sd: dict = json.loads(raw) if isinstance(raw, str) else (raw or {})

            brand_voice = str(sd.get("voice_traits") or "")
            escalation_notes = str(sd.get("forbidden_phrases") or "")
            agent_instructions = str(sd.get("launch_notes") or "")
            facts_data = {k: sd[k] for k in _FACTS_KEYS if sd.get(k) is not None}

            print(f"\n--- Tenant {tid} ---")
            print(f"  brand_voice:       {brand_voice!r}")
            print(f"  escalation_notes:  {escalation_notes!r}")
            print(f"  agent_instructions:{agent_instructions!r}")
            print(f"  facts_data:        {facts_data}")

            if dry_run:
                print("  [DRY RUN — sin escritura]")
                continue

            await conn.execute(
                """
                INSERT INTO tenant_playbook
                  (tenant_id, brand_voice, escalation_notes, agent_instructions, last_edited_by)
                VALUES ($1, $2, $3, $4, NULL)
                ON CONFLICT (tenant_id) DO UPDATE SET
                  brand_voice        = EXCLUDED.brand_voice,
                  escalation_notes   = EXCLUDED.escalation_notes,
                  agent_instructions = EXCLUDED.agent_instructions,
                  version            = tenant_playbook.version + 1
                """,
                tid, brand_voice, escalation_notes, agent_instructions,
            )
            print("  playbook: OK")

            if facts_data:
                await conn.execute(
                    """
                    INSERT INTO tenant_facts (tenant_id, data, last_edited_by)
                    VALUES ($1, $2::jsonb, NULL)
                    ON CONFLICT (tenant_id) DO UPDATE SET
                      data    = EXCLUDED.data,
                      version = tenant_facts.version + 1
                    """,
                    tid, json.dumps(facts_data),
                )
                print("  facts:   OK")
            else:
                print("  facts:   vacío (sin datos en step_data)")
    finally:
        await conn.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tenant-id", type=UUID, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(backfill(args.tenant_id, args.dry_run))


if __name__ == "__main__":
    main()
