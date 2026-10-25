"""Corre una batería de preguntas contra el agente real de un tenant ("Probar agente").

Uso:
    # Ver las preguntas sin tocar nada
    poetry run python -m scripts.run_battery --tenant thinkingmu-demo \
        --file evals/batteries/thinkingmu.yaml --dry-run

    # Correrla (gasta crédito de Anthropic y escribe filas de simulación en la base de datos)
    poetry run python -m scripts.run_battery --tenant thinkingmu-demo \
        --file evals/batteries/thinkingmu.yaml --out /tmp/thinkingmu.json

Usa el mismo servicio que `POST /simulations/chats`: cada pregunta abre un chat nuevo (salvo
`same_chat: true`), cuenta en el tope diario del simulador y no entrega nada a ningún canal.
Se niega a correr si el tope ya está alcanzado y muestra el gasto.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from uuid import UUID

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.api.evals.battery import (  # noqa: E402
    Battery,
    BatteryRow,
    format_table,
    list_questions,
    load_battery,
    run_battery,
)

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_battery")


async def _spend_line(tenant_id: UUID) -> str:
    from apps.api.simulator.cost_guard import simulation_spend_cents

    tenant, total = await simulation_spend_cents(tenant_id)
    return f"gasto del simulador en 24 h: tenant ${tenant / 100:.2f}, global ${total / 100:.2f}"


async def _run(tenant_slug: str, battery: Battery, out: Path | None) -> int:
    import apps.api.skills  # noqa: F401 — registra skills
    from apps.api.agents.dependencies import AgentDependencies
    from apps.api.agents.graph import build_graph
    from apps.api.core.config import get_settings
    from apps.api.db.client import bootstrap_connection, close_pool, init_pool
    from apps.api.db.queries import get_tenant_by_slug
    from apps.api.integrations.anthropic_client import build_anthropic_client
    from apps.api.integrations.langsmith_client import build_langsmith_client
    from apps.api.integrations.observability import ObservabilityClient
    from apps.api.integrations.openai_embeddings import build_openai_client
    from apps.api.services.audit import AuditLogger
    from apps.api.services.reasoning import ReasoningTracker
    from apps.api.simulator.chat import create_chat, send_message
    from apps.api.simulator.cost_guard import SimulationBudgetExceeded, ensure_simulation_budget

    settings = get_settings()
    await init_pool()
    observability = ObservabilityClient(primary=build_langsmith_client(settings))
    try:
        async with bootstrap_connection() as conn:
            tenant = await get_tenant_by_slug(conn, tenant_slug)
        if tenant is None:
            print(f"No existe el tenant con slug {tenant_slug!r}", file=sys.stderr)
            return 2
        tenant_id = tenant.id

        try:
            await ensure_simulation_budget(tenant_id)
        except SimulationBudgetExceeded as exc:
            print(f"Tope diario alcanzado, no corro nada. {exc}", file=sys.stderr)
            print(await _spend_line(tenant_id), file=sys.stderr)
            return 3

        deps = AgentDependencies(
            anthropic=build_anthropic_client(settings.anthropic_api_key.get_secret_value()),
            openai=build_openai_client(settings.openai_api_key.get_secret_value()),
            settings=settings,
            reasoning_tracker=ReasoningTracker(),
            audit_logger=AuditLogger(),
            observability=observability,
        )
        graph = build_graph(deps)

        async def new_chat() -> UUID:
            return (await create_chat(tenant_id, triggered_by=None)).id

        async def send(chat_id: UUID, text: str):
            return await send_message(
                tenant_id, chat_id, text, graph=graph, observability=observability
            )

        rows: list[BatteryRow] = []
        stopped: SimulationBudgetExceeded | None = None
        try:
            rows = await run_battery(
                battery,
                new_chat=new_chat,
                send=send,
                ensure_budget=lambda: ensure_simulation_budget(tenant_id),
            )
        except SimulationBudgetExceeded as exc:
            stopped = exc

        if rows:
            print(format_table(rows))
        if out is not None and rows:
            out.write_text(json.dumps([_row_json(r) for r in rows], ensure_ascii=False, indent=2))
            print(f"Transcripción y trazas guardadas en {out}")
        print(await _spend_line(tenant_id))
        if stopped is not None:
            print(f"Batería interrumpida por el tope diario: {stopped}", file=sys.stderr)
            return 3
        return 0
    finally:
        await observability.flush()
        await close_pool()


def _row_json(r: BatteryRow) -> dict:
    return {
        "id": r.question.id,
        "ask": r.question.ask,
        "expected": r.question.expected,
        "chatbase": r.question.chatbase,
        "chat_id": str(r.chat_id) if r.chat_id else None,
        "decision": r.decision,
        "reply": r.reply,
        "escalation_reason": r.escalation_reason,
        "skills": r.skills,
        "trace_id": r.trace_id,
        "cost_cents": r.cost_cents,
        "error": r.error,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batería de preguntas contra el agente real.")
    parser.add_argument("--tenant", required=True, help="slug del tenant")
    parser.add_argument("--file", required=True, type=Path, help="YAML de la batería")
    parser.add_argument("--out", type=Path, default=None, help="JSON con la transcripción")
    parser.add_argument(
        "--dry-run", action="store_true", help="solo lista las preguntas, sin base de datos ni LLM"
    )
    args = parser.parse_args(argv)

    battery = load_battery(args.file)
    if args.dry_run:
        print(list_questions(battery))
        return 0
    return asyncio.run(_run(args.tenant, battery, args.out))


if __name__ == "__main__":
    sys.exit(main())
