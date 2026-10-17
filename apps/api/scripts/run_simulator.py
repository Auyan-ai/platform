"""CLI para correr el simulador manualmente.

Checkpoint mínimo del sub-PR 0.10: CE-01 y RE-01 pasan con judge >= 7.

Uso:
    # Seed + correr CE-01 y RE-01 (checkpoint mínimo)
    poetry run python -m scripts.run_simulator --tenant <uuid>

    # Correr un scenario específico (por nombre exacto)
    poetry run python -m scripts.run_simulator --tenant <uuid> --scenario "CE-01: Tracking de #1234 con fulfillment"

    # Correr todos los scenarios del tenant
    poetry run python -m scripts.run_simulator --tenant <uuid> --all

Requiere que la migration 20260522000004_add_simulator_tables.sql esté aplicada en la DB.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_simulator")

# Scenarios del checkpoint mínimo
CHECKPOINT_SCENARIOS = {"CE-01", "RE-01"}

# Criterio del checkpoint (design doc §16): "CE-01 y RE-01 pasan con judge ≥ 7".
# Distinto del label de operación normal (status='passed' exige ≥ 7.5). Aquí
# evaluamos la barra documentada del checkpoint: judge ≥ 7 + assertions críticas OK.
CHECKPOINT_JUDGE_MIN = 7.0


def _critical_assertions_pass(run) -> bool:
    """True si todas las assertions críticas del run pasan."""
    for a in run.assertions_results or []:
        if a.get("is_critical") and not a.get("passed"):
            return False
    return True


def _meets_checkpoint(run, *, require_judge: bool = True) -> bool:
    """True si el run cumple la barra del checkpoint: judge ≥ 7 y todas las
    assertions críticas pasan.

    Con require_judge=False (modo --no-judge para cazar bugs), solo se exige que
    pasen las assertions críticas — el judge no corre.
    """
    if not _critical_assertions_pass(run):
        return False
    if not require_judge:
        return True
    if not run.judge_eval:
        return False
    if float(run.judge_eval.get("overall_score", 0)) < CHECKPOINT_JUDGE_MIN:
        return False
    return True


_EMAIL = re.compile(r"([\w.+-])[\w.+-]*@([\w-])[\w.-]*(\.[a-z]{2,})", re.I)
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def mask_contacts(text: str) -> str:
    """Enmascara emails y teléfonos para que el informe se pueda pegar en un PR."""
    text = _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}***{m.group(3)}", text)
    return _PHONE.sub("***", text)


def _print_agent_replies(run) -> None:
    """Respuestas del agente del run (contactos enmascarados) y la decisión final."""
    for turn in run.transcript or []:
        if turn.get("role") == "agent":
            print(f"  Agente (turno {turn['turn_number']}): {mask_contacts(turn['content'])}")
    print(f"  Decisión final: {run.termination_reason}")


async def main(
    tenant_id: uuid.UUID,
    *,
    scenario_name: str | None,
    run_all: bool,
    no_judge: bool,
    judge_model: str,
    ids: list[str] | None = None,
    show_replies: bool = False,
) -> int:
    import apps.api.skills  # noqa: F401 — registra skills
    from apps.api.agents.dependencies import AgentDependencies
    from apps.api.agents.graph import build_graph
    from apps.api.core.config import get_settings
    from apps.api.db.client import close_pool, init_pool, tenant_scope
    from apps.api.db.queries import list_simulation_scenarios
    from apps.api.integrations.anthropic_client import build_anthropic_client
    from apps.api.integrations.langfuse_client import build_langfuse_client
    from apps.api.integrations.langsmith_client import build_langsmith_client
    from apps.api.integrations.observability import ObservabilityClient
    from apps.api.integrations.openai_embeddings import build_openai_client
    from apps.api.services.audit import AuditLogger
    from apps.api.services.reasoning import ReasoningTracker
    from apps.api.simulator.runner import run_simulation
    from apps.api.simulator.scenarios import capabilities_by_name, seed_scenarios

    settings = get_settings()
    await init_pool()

    try:
        anthropic = build_anthropic_client(settings.anthropic_api_key.get_secret_value())
        openai = build_openai_client(settings.openai_api_key.get_secret_value())
        langfuse = build_langfuse_client(settings)
        observability = ObservabilityClient(primary=build_langsmith_client(settings))

        deps = AgentDependencies(
            anthropic=anthropic,
            openai=openai,
            settings=settings,
            reasoning_tracker=ReasoningTracker(),
            audit_logger=AuditLogger(),
            observability=observability,
        )
        graph = build_graph(deps)

        # Crea los escenarios base que falten; el runner deja cada uno igual que en el
        # código antes de correrlo.
        logger.info("Haciendo seed de scenarios para tenant=%s ...", tenant_id)
        async with tenant_scope(tenant_id) as conn:
            seed_result = await seed_scenarios(conn, tenant_id)
            logger.info(
                "Seed: %s profiles, %s scenarios creados",
                seed_result["profiles"],
                seed_result["scenarios"],
            )

            # Obtener scenarios a correr
            all_scenarios = await list_simulation_scenarios(conn, tenant_id)

        if not all_scenarios:
            print("No hay scenarios disponibles para este tenant.", file=sys.stderr)
            return 1

        # Filtrar según args
        if scenario_name:
            targets = [s for s in all_scenarios if s.name == scenario_name]
            if not targets:
                names = [s.name for s in all_scenarios]
                print(f"Scenario '{scenario_name}' no encontrado. Disponibles:", file=sys.stderr)
                for n in names:
                    print(f"  - {n}", file=sys.stderr)
                return 1
        elif ids:
            targets = [s for s in all_scenarios if s.name.split(":")[0].strip() in ids]
            unknown = set(ids) - {s.name.split(":")[0].strip() for s in targets}
            if unknown:
                print(f"IDs sin escenario en el tenant: {sorted(unknown)}", file=sys.stderr)
                return 1
        elif run_all:
            targets = all_scenarios
        else:
            # Checkpoint: CE-01 y RE-01 (identifica por prefijo del nombre)
            targets = [
                s for s in all_scenarios
                if any(s.name.startswith(cid) for cid in CHECKPOINT_SCENARIOS)
            ]
            if len(targets) < len(CHECKPOINT_SCENARIOS):
                found = {s.name.split(":")[0].strip() for s in targets}
                missing = CHECKPOINT_SCENARIOS - found
                logger.warning("Scenarios de checkpoint no encontrados: %s", missing)

        print(f"\nCorriendo {len(targets)} scenario(s) para tenant={tenant_id}")
        print("=" * 70)

        capabilities = capabilities_by_name()
        results = []
        passed = 0
        failed = 0

        for scenario in targets:
            print(f"\n▶ {scenario.name}")
            print(f"  Capacidades: {', '.join(capabilities.get(scenario.name, [])) or '-'}")
            try:
                run_id = await run_simulation(
                    scenario.id,
                    tenant_id,
                    anthropic=anthropic,
                    graph=graph,
                    skip_judge=no_judge,
                    judge_model=judge_model,
                    observability=observability,
                )
                # Obtener resultado
                from apps.api.db.queries import get_simulation_run
                async with tenant_scope(tenant_id) as conn:
                    run = await get_simulation_run(conn, tenant_id, run_id)

                if run:
                    results.append((scenario.name, run))
                    status_icon = {"passed": "✅", "partial": "⚠️", "failed": "❌", "errored": "💥"}.get(run.status, "?")
                    print(f"  Status: {status_icon} {run.status.upper()}")
                    print(f"  Terminación: {run.termination_reason}")
                    print(f"  Turnos: {run.turns_count}")
                    print(f"  Run: {run.id}  traza LangSmith: {run.langsmith_trace_id or '-'}")
                    if run.judge_eval:
                        j = run.judge_eval
                        print(f"  Judge overall: {j.get('overall_score', 0):.1f}/10  verdict={j.get('verdict')}")
                        print(f"  Goal logrado: {j.get('judge_goal_achieved')}")
                        print(f"  Sugerencias: {j.get('suggestions', '')}")
                    if run.assertions_results:
                        total = run.assertions_total or 0
                        passed_a = run.assertions_passed or 0
                        print(f"  Assertions: {passed_a}/{total}")
                        for a in run.assertions_results:
                            icon = "✓" if a["passed"] else "✗"
                            crit = " [CRÍTICA]" if a["is_critical"] else ""
                            print(f"    {icon} {a['key']}: {a['evidence']}{crit}")
                    if show_replies:
                        _print_agent_replies(run)
                    cost = run.cost_cents or 0
                    print(f"  Costo: ${cost / 100:.4f}")

                    if _meets_checkpoint(run, require_judge=not no_judge):
                        passed += 1
                    else:
                        failed += 1
                else:
                    print("  ERROR: run no encontrado en DB")
                    failed += 1
            except Exception as exc:
                print(f"  EXCEPCIÓN: {exc}")
                logger.exception("scenario_run_failed name=%s", scenario.name)
                failed += 1

        print("\n" + "=" * 70)
        print("Escenario | capacidades | resultado")
        for name, run in results:
            caps = ", ".join(capabilities.get(name, [])) or "-"
            verdict = "OK" if _meets_checkpoint(run, require_judge=not no_judge) else "FALLA"
            print(f"{name} | {caps} | {verdict} ({run.status})")
        bar = "assertions críticas" if no_judge else f"judge ≥ {CHECKPOINT_JUDGE_MIN:.0f} + assertions críticas"
        print(f"RESUMEN: {passed}/{len(targets)} cumplen ({bar}) | {failed} no")
        if no_judge:
            print("⚠️  Modo --no-judge: el judge NO corrió. Corrida final lo requiere.")

        # Checkpoint mínimo (design doc §16): judge ≥ 7 + assertions críticas OK
        if not run_all and not scenario_name and not ids:
            checkpoint_passed = sum(
                1 for name, run in results
                if any(name.startswith(cid) for cid in CHECKPOINT_SCENARIOS)
                and _meets_checkpoint(run, require_judge=not no_judge)
            )
            print(
                f"\nCheckpoint 0.10: {checkpoint_passed}/{len(CHECKPOINT_SCENARIOS)} "
                f"scenarios cumplen (judge ≥ {CHECKPOINT_JUDGE_MIN:.0f} + assertions críticas)"
            )
            if checkpoint_passed == len(CHECKPOINT_SCENARIOS):
                print("✅ Checkpoint APROBADO — Sub-PR 0.10 listo para merge")
                return 0
            else:
                print("❌ Checkpoint NO aprobado — revisar resultados arriba")
                return 1

        return 0 if failed == 0 else 1

    finally:
        await observability.flush()
        await langfuse.flush()
        await close_pool()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Corre el simulador de agente para E2E testing.")
    parser.add_argument("--tenant", required=True, help="UUID del tenant")
    parser.add_argument(
        "--scenario",
        default=None,
        help="Nombre exacto del scenario a correr (ej: 'CE-01: Tracking de #1234 con fulfillment')",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Correr todos los scenarios del tenant",
    )
    parser.add_argument(
        "--ids",
        default=None,
        help="IDs de scenarios separados por coma (ej: ID-01,ID-02,OR-01).",
    )
    parser.add_argument(
        "--show-replies",
        action="store_true",
        help="Imprime las respuestas del agente (contactos enmascarados) y la decisión.",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Salta el judge — solo evalúa assertions. Para cazar bugs rápido.",
    )
    parser.add_argument(
        "--judge-model",
        choices=["sonnet", "opus"],
        default="sonnet",
        help="Modelo del judge. Default: sonnet. Usa opus solo para calibración explícita.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        tenant_uuid = uuid.UUID(args.tenant)
    except ValueError:
        print(f"Error: '{args.tenant}' no es un UUID válido.", file=sys.stderr)
        sys.exit(1)

    exit_code = asyncio.run(
        main(
            tenant_uuid,
            scenario_name=args.scenario,
            run_all=args.all,
            no_judge=args.no_judge,
            judge_model=args.judge_model,
            ids=[i.strip() for i in args.ids.split(",")] if args.ids else None,
            show_replies=args.show_replies,
        )
    )
    sys.exit(exit_code)
