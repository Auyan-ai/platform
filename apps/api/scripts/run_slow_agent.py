"""CLI para ejecutar el slow agent manualmente.

Uso básico:
    poetry run python -m scripts.run_slow_agent --tenant <uuid>

Con opciones:
    poetry run python -m scripts.run_slow_agent \\
        --tenant 11111111-1111-1111-1111-111111111111 \\
        --since-days 14 \\
        --max-conversations 30

El script imprime un resumen al final con conversaciones evaluadas,
propuestas generadas y costo estimado.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_slow_agent")


async def main(
    tenant_id: uuid.UUID,
    since_days: int,
    max_conversations: int,
) -> None:
    from apps.api.core.config import get_settings
    from apps.api.db.client import close_pool, init_pool
    from apps.api.integrations.anthropic_client import build_anthropic_client
    from apps.api.slow_agent.runner import run_slow_agent_for_tenant

    settings = get_settings()
    await init_pool()

    try:
        anthropic = build_anthropic_client(settings.anthropic_api_key.get_secret_value())

        logger.info(
            "Iniciando slow agent — tenant=%s since_days=%d max_conversations=%d",
            tenant_id, since_days, max_conversations,
        )

        stats = await run_slow_agent_for_tenant(
            anthropic=anthropic,
            tenant_id=tenant_id,
            since_days=since_days,
            max_conversations=max_conversations,
        )

        print("\n" + "=" * 60)
        print("Slow Agent completado")
        print("=" * 60)
        print(f"  Conversaciones evaluadas : {stats.conversations_evaluated}")
        print(f"  Propuestas generadas     : {stats.proposals_generated}")
        print(f"  Tokens Sonnet            : {stats.sonnet_tokens:,}")
        print(f"  Tokens Opus              : {stats.opus_tokens:,}")
        print(f"  Costo estimado (USD)     : ${stats.cost_usd:.4f}")
        if stats.errors:
            print(f"  Errores en convs         : {len(stats.errors)}")
            for e in stats.errors:
                print(f"    - {e}")
        print("=" * 60 + "\n")

    finally:
        await close_pool()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ejecuta el slow agent para un tenant.")
    parser.add_argument("--tenant", required=True, help="UUID del tenant")
    parser.add_argument(
        "--since-days",
        type=int,
        default=7,
        help="Analiza conversaciones de los últimos N días (default: 7)",
    )
    parser.add_argument(
        "--max-conversations",
        type=int,
        default=50,
        help="Máximo de conversaciones a juzgar en este run (default: 50)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        tenant_uuid = uuid.UUID(args.tenant)
    except ValueError:
        print(f"Error: '{args.tenant}' no es un UUID válido.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(main(tenant_uuid, args.since_days, args.max_conversations))
