"""Máquina de estados multi-turn del simulador.

Flujo por run:
  1. Crear end_customer sintético + conversation (is_simulation=TRUE).
  2. Insertar run en DB con status='running'.
  3. Turno 0: primer mensaje de la persona (sin llamar al LLM).
  4. Loop: invocar el grafo real con simulation_mode=True → respuesta del agente.
  5. Pasar respuesta al user_simulator (Haiku) → siguiente turno del cliente.
  6. Repetir hasta criterio de parada.
  7. Correr assertions + judge (en paralelo).
  8. Finalizar run en DB + soft-delete la conversación sintética.

El grafo se invoca DIRECTAMENTE (no por AgentService) para evitar:
  - Trace de Langfuse automático (usamos langfuse_trace_id manual).
  - Envío al helpdesk (respond/escalate no tocan canal externo, ya validado).
Los nodos respond/escalate guardan la respuesta en `messages`, como en producción; el
runner solo guarda los mensajes del cliente simulado y el acuse fijo de escalado.

Semáforo PROCESS-wide: 10 simulaciones concurrentes máximo.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from apps.api.agents.state import AgentState
from apps.api.core.config import get_models
from apps.api.db.client import tenant_scope
from apps.api.db.identity_checks import (
    count_conversation_attempts,
    soft_delete_conversation_checks,
)
from apps.api.db.models import SimulationScenario, UserProfile
from apps.api.db.queries import (
    create_conversation,
    create_end_customer,
    finalize_simulation_run,
    get_simulation_scenario,
    get_user_profile,
    has_pending_approval_for_conversation,
    insert_message,
    insert_simulation_run,
    list_pending_approval_inputs,
    list_skill_audit_log,
    set_simulation_run_trace_id,
    soft_delete_conversation,
    update_conversation_last_message,
)
from apps.api.services.inbound_media import chat_escalation_ack
from apps.api.services.language import state_languages
from apps.api.simulator.assertions import check_assertions, summarize
from apps.api.simulator.cost_guard import ensure_simulation_budget
from apps.api.simulator.judge import (
    DEFAULT_JUDGE_ALIAS,
    JUDGE_TIMEOUT_SECONDS,
    JudgeModelAlias,
    SimulatorJudgeVerdict,
    judge_simulation,
    normalize_judge_model,
    verdict_to_dict,
)
from apps.api.simulator.scenarios import sync_scenario_from_code
from apps.api.simulator.transcript import (
    SimulatorTranscript,
    TranscriptTurn,
    transcript_to_list,
)
from apps.api.simulator.user_simulator import UserSimulator

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic
    from apps.api.integrations.langsmith_client import LangSmithTrace
    from apps.api.integrations.observability import ObservabilityClient
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

# 10 simulaciones concurrentes como máximo en todo el proceso.
_GLOBAL_SIM_SEMAPHORE = asyncio.Semaphore(10)

LOOP_DETECTION_WINDOW = 200  # primeros chars del mensaje del agente para detectar loops

# Tope duro del run completo (multi-turn). Red de seguridad contra cuelgues de
# LLM o loops largos: aunque cada llamada tiene su propio timeout, este garantiza
# que un run nunca corre indefinidamente.
SIMULATION_TIMEOUT_SECONDS = 180


@dataclass
class _RunAccumulator:
    """Estado interno del runner durante la ejecución de un run."""

    run_id: UUID
    conversation_id: UUID
    end_customer_id: UUID
    transcript: SimulatorTranscript
    tokens_simulator_in: int = 0
    tokens_simulator_out: int = 0
    tokens_agent_in: int = 0
    tokens_agent_out: int = 0
    tokens_judge_in: int = 0
    tokens_judge_out: int = 0
    cost_usd: float = 0.0
    judge_model: str = field(default_factory=lambda: get_models().judge_sonnet_model)
    last_agent_messages: list[str] = field(default_factory=list)
    # Última razón de escalado que dejó el grafo y contactos de las respuestas del agente
    # que ni los datos de la tienda, ni las herramientas ni el cliente respaldan.
    escalation_reason: str | None = None
    unbacked_contacts: list[str] = field(default_factory=list)
    trace_run_ids: list[str] = field(default_factory=list)
    # Fila de `simulation_runs` y raíz de LangSmith de la corrida; de ellas cuelgan los
    # turnos del agente, el cliente simulado y el judge.
    db_run_id: UUID | None = None
    root_trace: LangSmithTrace | None = None
    sim_metadata: dict[str, Any] = field(default_factory=dict)


def sim_customer_email(run_id: object) -> str:
    """Email del cliente sintético de una simulación (único por run)."""
    return f"sim-{run_id}@simulator.auyan.internal"


_ORDER_FIXTURE_KEYS = ("get_order_by_name", "get_order")
_ORDER_LIST_FIXTURE_KEYS = ("search_orders_by_email",)


def _owned_by(order: Any, email: str) -> Any:
    if isinstance(order, dict) and "_error" not in order and not order.get("email"):
        return {**order, "email": email}
    return order


def assign_mock_orders_to_customer(fixtures: dict[str, Any], email: str) -> dict[str, Any]:
    """Los pedidos mock pertenecen al cliente simulado (mismo email), para que el
    gate de ownership (email remitente == email pedido) se comporte como con un
    cliente real escribiendo desde su email. Un escenario que fije `email` en el
    pedido (p. ej. para probar "no es el dueño") se respeta. No muta el original."""
    shopify = dict((fixtures or {}).get("shopify") or {})
    for key in _ORDER_FIXTURE_KEYS:
        if key in shopify:
            shopify[key] = _owned_by(shopify[key], email)
    for key in _ORDER_LIST_FIXTURE_KEYS:
        if isinstance(shopify.get(key), list):
            shopify[key] = [_owned_by(order, email) for order in shopify[key]]
    return {**(fixtures or {}), "shopify": shopify}


async def run_simulation(
    scenario_id: UUID,
    tenant_id: UUID,
    *,
    anthropic: AsyncAnthropic,
    graph: CompiledStateGraph,
    triggered_by: UUID | None = None,
    batch_id: UUID | None = None,
    skip_judge: bool = False,
    judge_model: JudgeModelAlias | str = DEFAULT_JUDGE_ALIAS,
    observability: ObservabilityClient | None = None,
) -> UUID:
    """Corre un scenario completo. Retorna el run_id.

    skip_judge=True salta la evaluación del judge. Pensado para
    cazar bugs de assertions/fixtures rápido; la corrida final SIEMPRE corre el judge.

    Con `observability`, cada turno deja su traza de LangSmith (el id sale en el log
    `sim_trace_ids`). Sin él, el run no se traza, como hasta ahora.
    """
    async with _GLOBAL_SIM_SEMAPHORE:
        return await _run_simulation_inner(
            scenario_id=scenario_id,
            tenant_id=tenant_id,
            anthropic=anthropic,
            graph=graph,
            triggered_by=triggered_by,
            batch_id=batch_id,
            skip_judge=skip_judge,
            judge_model=judge_model,
            observability=observability,
        )


async def run_batch(
    scenario_ids: list[UUID],
    tenant_id: UUID,
    *,
    anthropic: AsyncAnthropic,
    graph: CompiledStateGraph,
    triggered_by: UUID | None = None,
    judge_model: JudgeModelAlias | str = DEFAULT_JUDGE_ALIAS,
    observability: ObservabilityClient | None = None,
) -> UUID:
    """Corre múltiples scenarios en paralelo (limitado por el semáforo global).
    Retorna un batch_id compartido por todos los runs del batch.
    """
    batch_id = uuid4()
    tasks = [
        asyncio.create_task(
            run_simulation(
                sid,
                tenant_id,
                anthropic=anthropic,
                graph=graph,
                triggered_by=triggered_by,
                batch_id=batch_id,
                judge_model=judge_model,
                observability=observability,
            )
        )
        for sid in scenario_ids
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
    return batch_id


# ─── Inner implementation ──────────────────────────────────────────────────────


async def _run_simulation_inner(
    scenario_id: UUID,
    tenant_id: UUID,
    *,
    anthropic: AsyncAnthropic,
    graph: CompiledStateGraph,
    triggered_by: UUID | None,
    batch_id: UUID | None,
    skip_judge: bool = False,
    judge_model: JudgeModelAlias | str = DEFAULT_JUDGE_ALIAS,
    observability: ObservabilityClient | None = None,
) -> UUID:
    # Antes de gastar nada: el tope diario vale para el panel y para el CLI.
    await ensure_simulation_budget(tenant_id)
    async with tenant_scope(tenant_id) as conn:
        scenario = await get_simulation_scenario(conn, tenant_id, scenario_id)
        if scenario is None:
            raise ValueError(f"Scenario {scenario_id} not found for tenant {tenant_id}")
        scenario = await sync_scenario_from_code(conn, tenant_id, scenario)
        profile = await get_user_profile(conn, tenant_id, scenario.user_profile_id)
        if profile is None:
            raise ValueError(
                f"UserProfile {scenario.user_profile_id} not found for tenant {tenant_id}"
            )
        # El idioma del cliente es del escenario, no del perfil compartido (CE-07).
        language = (scenario.mock_fixtures or {}).get("customer_language")
        if language:
            profile = profile.model_copy(update={"language": language})

    normalized_judge_model = normalize_judge_model(judge_model)
    run_id = uuid4()

    try:
        conversation_id, run_db_id, end_customer_id = await _setup_run(
            tenant_id=tenant_id,
            scenario=scenario,
            profile=profile,
            run_id=run_id,
            triggered_by=triggered_by,
            batch_id=batch_id,
        )
    except Exception:
        logger.exception("sim_setup_failed run_id=%s scenario_id=%s", run_id, scenario_id)
        raise

    acc = _RunAccumulator(
        run_id=run_id,
        conversation_id=conversation_id,
        end_customer_id=end_customer_id,
        judge_model=normalized_judge_model,
        transcript=SimulatorTranscript(
            scenario=scenario,
            profile_name=profile.name,
        ),
    )

    termination_reason = "error"
    judge_verdict: SimulatorJudgeVerdict | None = None

    acc.db_run_id = run_db_id
    await _start_run_trace(acc, observability, tenant_id=tenant_id, scenario=scenario)

    try:
        termination_reason = await asyncio.wait_for(
            _execute_loop(
                acc=acc,
                scenario=scenario,
                profile=profile,
                tenant_id=tenant_id,
                anthropic=anthropic,
                graph=graph,
                observability=observability,
            ),
            timeout=SIMULATION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning(
            "sim_loop_timeout run_id=%s scenario_id=%s timeout=%ds",
            run_id,
            scenario_id,
            SIMULATION_TIMEOUT_SECONDS,
        )
        termination_reason = "error"
    except Exception:
        logger.exception("sim_loop_failed run_id=%s scenario_id=%s", run_id, scenario_id)
        termination_reason = "error"

    acc.transcript.termination_reason = termination_reason

    # Obtener skill_log y estado de pending_approval, luego correr assertions + judge
    skill_log = await _get_skill_log(tenant_id, conversation_id)
    acc.transcript.skill_log = skill_log

    last_agent_msg = _last_agent_message(acc.transcript)
    pending_approval = await _pending_approval_present(tenant_id, conversation_id)
    approval_inputs, identity_attempts = await _behavior_evidence(
        tenant_id, conversation_id, scenario.assertions
    )

    assertion_results = check_assertions(
        assertions=scenario.assertions,
        agent_messages=[t.content for t in acc.transcript.turns if t.role == "agent"],
        skill_log=skill_log,
        last_agent_message=last_agent_msg,
        termination_reason=termination_reason,
        turns_count=len(acc.transcript.turns),
        pending_approval_present=pending_approval,
        escalation_reason=acc.escalation_reason,
        pending_approval_inputs=approval_inputs,
        identity_attempts=identity_attempts,
        unbacked_contacts=acc.unbacked_contacts,
    )

    if skip_judge:
        logger.info("sim_judge_skipped run_id=%s (skip_judge=True)", run_id)
    else:
        judge_started = datetime.now(UTC)
        try:
            judge_verdict = await asyncio.wait_for(
                judge_simulation(
                    anthropic=anthropic,
                    transcript=acc.transcript,
                    scenario=scenario,
                    judge_model=acc.judge_model,
                ),
                timeout=JUDGE_TIMEOUT_SECONDS + 30,
            )
            acc.tokens_judge_in = judge_verdict.input_tokens
            acc.tokens_judge_out = judge_verdict.output_tokens
            acc.cost_usd += judge_verdict.cost_usd
            if observability is not None:
                observability.record_llm_run(
                    acc.root_trace,
                    name="simulation_judge",
                    model=judge_verdict.model_used,
                    usage=judge_verdict.usage,
                    cost_usd=judge_verdict.cost_usd,
                    start_time=judge_started,
                    end_time=datetime.now(UTC),
                    outputs={"verdict": str(judge_verdict.verdict)},
                    call=judge_verdict.call.as_dict() if judge_verdict.call else None,
                )
        except TimeoutError:
            logger.warning("sim_judge_timeout run_id=%s", run_id)
        except Exception:
            logger.exception("sim_judge_failed run_id=%s", run_id)

    passed, total, all_critical_passed = summarize(assertion_results)
    status = _compute_status(
        all_critical_passed=all_critical_passed,
        passed=passed,
        total=total,
        judge_verdict=judge_verdict,
        judge_required=not skip_judge,
    )

    cost_cents = round(acc.cost_usd * 100, 4)

    await _finalize(
        tenant_id=tenant_id,
        run_id=run_db_id,
        conversation_id=conversation_id,
        acc=acc,
        status=status,
        termination_reason=termination_reason,
        assertion_results=assertion_results,
        passed=passed,
        total=total,
        judge_verdict=judge_verdict,
        cost_cents=cost_cents,
    )

    if observability is not None and acc.root_trace is not None:
        observability.finalize_simulation_trace(
            acc.root_trace,
            outputs={
                "status": status,
                "termination_reason": termination_reason,
                "assertions_passed": passed,
                "assertions_total": total,
            },
            metadata={
                "status": status,
                "termination_reason": termination_reason,
                "turns": len(acc.transcript.turns),
                "cost_usd": acc.cost_usd,
                "tokens_agent": acc.tokens_agent_in + acc.tokens_agent_out,
                "tokens_simulator": acc.tokens_simulator_in + acc.tokens_simulator_out,
                "tokens_judge": acc.tokens_judge_in + acc.tokens_judge_out,
            },
            error=None if termination_reason != "error" else "simulation_error",
        )
    logger.info(
        "sim_trace_ids run_id=%s langsmith_root=%s turns=%s",
        run_id,
        acc.root_trace.run_id if acc.root_trace else None,
        ",".join(acc.trace_run_ids),
    )
    logger.info(
        "sim_run_complete run_id=%s scenario=%s status=%s turns=%d",
        run_id,
        scenario.name,
        status,
        len(acc.transcript.turns),
    )
    return run_db_id


async def _setup_run(
    tenant_id: UUID,
    scenario: SimulationScenario,
    profile: UserProfile,
    run_id: UUID,
    triggered_by: UUID | None,
    batch_id: UUID | None,
) -> tuple[UUID, UUID, UUID]:
    """Crea end_customer + conversation + simulation_run.

    Retorna (conversation_id, run_id_db, end_customer_id).
    """
    async with tenant_scope(tenant_id) as conn:
        # Cliente sintético — email único para que no colisione con reales
        end_customer = await create_end_customer(
            conn,
            tenant_id=tenant_id,
            email=sim_customer_email(run_id),
            full_name=f"[SIM] {profile.name}",
            metadata={"simulation": True, "profile_name": profile.name},
        )

        conversation = await create_conversation(
            conn,
            tenant_id=tenant_id,
            end_customer_id=end_customer.id,
            channel="chat",
            subject=f"[SIM] {scenario.name}",
            is_simulation=True,
        )

        # AOP version actual (se llena después si el grafo lo setea)
        run = await insert_simulation_run(
            conn,
            tenant_id=tenant_id,
            scenario_id=scenario.id,
            aop_slug=scenario.aop_slug,
            aop_version=None,
            conversation_id=conversation.id,
            batch_id=batch_id,
            triggered_by=triggered_by,
        )

    return conversation.id, run.id, end_customer.id


async def _execute_loop(
    acc: _RunAccumulator,
    scenario: SimulationScenario,
    profile: UserProfile,
    tenant_id: UUID,
    anthropic: AsyncAnthropic,
    graph: CompiledStateGraph,
    observability: ObservabilityClient | None = None,
) -> str:
    """Loop principal de la simulación. Retorna el termination_reason."""
    sim = UserSimulator(profile=profile, anthropic=anthropic)
    fixtures = assign_mock_orders_to_customer(
        scenario.mock_fixtures, sim_customer_email(acc.run_id)
    )

    identity_mode = scenario_identity_mode(scenario.mock_fixtures)

    # Turno 0: primer mensaje del cliente (sin LLM)
    first = sim.first_message()
    await _persist_customer_message(tenant_id, acc.conversation_id, first.message)
    acc.transcript.turns.append(
        TranscriptTurn(
            role="customer",
            content=first.message,
            turn_number=0,
            goal_achieved=first.goal_achieved,
            give_up=first.give_up,
            internal_reasoning=first.internal_reasoning,
        )
    )

    max_turns = scenario.max_turns

    for turn_number in range(1, max_turns + 1):
        # ── Invocar el grafo ──────────────────────────────────────────────────
        last_customer_msg = acc.transcript.turns[-1].content
        trace = (
            observability.start_conversation_trace(
                tenant_id=str(tenant_id),
                conversation_id=str(acc.conversation_id),
                end_customer_id=str(acc.end_customer_id),
                channel="chat",
                input_text=last_customer_msg,
                parent=acc.root_trace,
                extra_metadata=acc.sim_metadata,
                extra_tags=["simulation"],
            )
            if observability is not None
            else None
        )
        primary_trace = trace.primary if trace else None
        initial_state: AgentState = {
            "tenant_id": str(tenant_id),
            "conversation_id": str(acc.conversation_id),
            "end_customer_id": str(acc.end_customer_id),
            "inbound_message_content": last_customer_msg,
            "channel": "chat",
            "simulation_mode": True,
            "simulation_fixtures": fixtures,
            "simulation_identity": identity_mode,
            "forced_aop_slug": scenario.aop_slug,
            "langfuse_trace_id": f"sim-{acc.run_id}-t{turn_number}",
            "_trace_run_id": str(primary_trace.run_id) if primary_trace else None,
            "_trace_dotted_order": primary_trace.dotted_order if primary_trace else None,
            "tool_results": [],
            "tool_iterations": 0,
            "max_tool_iterations": 5,
            "allowed_skills": [],
        }

        try:
            final_state: AgentState = await graph.ainvoke(initial_state)
        except Exception:
            logger.exception("sim_graph_invoke_failed run_id=%s turn=%d", acc.run_id, turn_number)
            _finalize_trace(observability, trace, None, error="graph_invoke_failed")
            return "error"
        _finalize_trace(observability, trace, final_state)

        agent_response = simulated_chat_reply(final_state)
        decision = final_state.get("decision", "respond")

        acc.tokens_agent_in += final_state.get("tokens_in", 0)
        acc.tokens_agent_out += final_state.get("tokens_out", 0)
        acc.cost_usd += final_state.get("cost_usd", 0.0)

        if final_state.get("escalation_reason"):
            acc.escalation_reason = str(final_state["escalation_reason"])
        acc.unbacked_contacts += _unbacked_contacts(final_state, agent_response)
        if primary_trace is not None:
            acc.trace_run_ids.append(str(primary_trace.run_id))

        if not agent_response.strip():
            logger.error(
                "sim_turn_without_reply run_id=%s turn=%d decision=%s error=%s",
                acc.run_id,
                turn_number,
                final_state.get("decision"),
                final_state.get("error"),
            )
            return "error"

        ack = _chat_ack(final_state)
        if ack is not None:
            await _persist_escalation_ack(tenant_id, acc.conversation_id, ack)
        acc.transcript.turns.append(
            TranscriptTurn(
                role="agent",
                content=agent_response,
                turn_number=turn_number,
            )
        )

        # Capturar aop_version si el grafo la setea
        if final_state.get("aop_version") and not hasattr(acc, "_aop_version"):
            acc.transcript.aop_compiled_prompt = final_state.get("aop_workspace")
        acc.transcript.tenant_facts = final_state.get("tenant_facts") or acc.transcript.tenant_facts
        for chunk in final_state.get("retrieved_chunks") or []:
            acc.transcript.knowledge.setdefault(
                str(chunk.get("document_title", "")), str(chunk.get("content", ""))[:1500]
            )

        if decision == "escalate":
            return "escalated_by_agent"

        # Loop detection: dos respuestas del agente con el mismo inicio
        acc.last_agent_messages.append(agent_response[:LOOP_DETECTION_WINDOW])
        # Un texto fijo del código (sin LLM, `tokens_in` en 0) se repite por diseño: no
        # es un bucle del agente.
        if (
            final_state.get("tokens_in", 0) > 0
            and len(acc.last_agent_messages) >= 2
            and acc.last_agent_messages[-1] == acc.last_agent_messages[-2]
        ):
            logger.warning("sim_agent_loop_detected run_id=%s", acc.run_id)
            return "agent_loop_detected"

        # ── Siguiente turno del simulador ──────────────────────────────────────
        history = [{"role": t.role, "content": t.content} for t in acc.transcript.turns]
        sim_turn = await _next_simulator_turn(
            sim, history, turn_number, acc=acc, observability=observability
        )

        # El modelo a veces devuelve mensaje vacío de forma transitoria (sin flag de
        # cierre). Reintentamos una vez antes de tratarlo como fin de conversación.
        if not sim_turn.message.strip() and not sim_turn.goal_achieved and not sim_turn.give_up:
            sim_turn = await _next_simulator_turn(
                sim, history, turn_number, acc=acc, observability=observability
            )

        # Mensaje vacío persistente = el cliente dejó de responder. No lo persistimos
        # (rompería el embed del grafo y la API de Anthropic con content vacío) y
        # terminamos. Si marcó goal_achieved, lo respetamos; si no, el cliente
        # se desenganchó sin resolver (give_up).
        if not sim_turn.message.strip():
            if sim_turn.goal_achieved:
                return "goal_achieved"
            return "give_up"

        await _persist_customer_message(tenant_id, acc.conversation_id, sim_turn.message)
        acc.transcript.turns.append(
            TranscriptTurn(
                role="customer",
                content=sim_turn.message,
                turn_number=turn_number,
                goal_achieved=sim_turn.goal_achieved,
                give_up=sim_turn.give_up,
                internal_reasoning=sim_turn.internal_reasoning,
                tokens_in=sim_turn.input_tokens,
                tokens_out=sim_turn.output_tokens,
            )
        )

        if sim_turn.goal_achieved:
            return "goal_achieved"
        if sim_turn.give_up:
            return "give_up"

    return "max_turns"


async def _start_run_trace(
    acc: _RunAccumulator,
    observability: ObservabilityClient | None,
    *,
    tenant_id: UUID,
    scenario: SimulationScenario,
) -> None:
    """Abre la raíz de LangSmith de la corrida y guarda su id en `simulation_runs`.

    Sin `observability` no hace nada. Un fallo al guardar el id no tumba la corrida:
    la traza sigue en LangSmith y el id sale en el log `sim_trace_ids`."""
    if observability is None or acc.db_run_id is None:
        return
    from apps.api.simulator.scenarios import capabilities_by_name

    acc.sim_metadata = {
        "simulation": True,
        "simulation_run_id": str(acc.db_run_id),
        "scenario_id": str(scenario.id),
        "scenario_name": scenario.name,
        "capabilities": capabilities_by_name().get(scenario.name, []),
    }
    first_message = acc.transcript.turns[0].content if acc.transcript.turns else ""
    acc.root_trace = observability.start_simulation_trace(
        tenant_id=str(tenant_id),
        conversation_id=str(acc.conversation_id),
        metadata=acc.sim_metadata,
        tags=["simulation", f"scenario:{scenario.id}"],
        input_text=first_message or scenario.name,
    )
    if acc.root_trace is None:
        return
    try:
        async with tenant_scope(tenant_id) as conn:
            await set_simulation_run_trace_id(conn, acc.db_run_id, tenant_id, acc.root_trace.run_id)
    except Exception:
        logger.exception("sim_trace_id_save_failed run_id=%s", acc.run_id)


async def _next_simulator_turn(
    sim: UserSimulator,
    history: list[dict],
    turn_number: int,
    *,
    acc: _RunAccumulator,
    observability: ObservabilityClient | None,
) -> Any:
    """Llama al cliente simulado, suma su uso a la corrida y lo traza como run hijo."""
    started = datetime.now(UTC)
    sim_turn = await sim.next_turn(conversation_history=history, turn_number=turn_number)
    acc.tokens_simulator_in += sim_turn.input_tokens
    acc.tokens_simulator_out += sim_turn.output_tokens
    acc.cost_usd += sim_turn.cost_usd
    if observability is not None:
        observability.record_llm_run(
            acc.root_trace,
            name="customer_simulator",
            model=get_models().simulator_model,
            usage=sim_turn.usage,
            cost_usd=sim_turn.cost_usd,
            start_time=started,
            end_time=datetime.now(UTC),
            outputs={
                "turn": turn_number,
                "message": sim_turn.message,
                "goal_achieved": sim_turn.goal_achieved,
                "give_up": sim_turn.give_up,
            },
            call=sim_turn.call.as_dict() if sim_turn.call else None,
        )
    return sim_turn


async def _persist_customer_message(tenant_id: UUID, conversation_id: UUID, content: str) -> None:
    async with tenant_scope(tenant_id) as conn:
        await insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role="customer",
            direction="inbound",
            content=content,
        )
        await update_conversation_last_message(conn, tenant_id, conversation_id)


async def _persist_escalation_ack(tenant_id: UUID, conversation_id: UUID, content: str) -> None:
    """El grafo ya guardó la respuesta del agente; el acuse fijo de escalado lo guarda
    quien entrega el turno, igual que `POST /webhooks/inbound`."""
    async with tenant_scope(tenant_id) as conn:
        await insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role="agent_ai",
            direction="outbound",
            content=content,
            metadata={"fixed_message": "escalation_ack"},
        )
        await update_conversation_last_message(conn, tenant_id, conversation_id)


async def _get_skill_log(tenant_id: UUID, conversation_id: UUID) -> list:
    async with tenant_scope(tenant_id) as conn:
        return await list_skill_audit_log(
            conn,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            limit=100,
        )


async def _finalize(
    tenant_id: UUID,
    run_id: UUID,
    conversation_id: UUID,
    acc: _RunAccumulator,
    status: str,
    termination_reason: str,
    assertion_results: list,
    passed: int,
    total: int,
    judge_verdict: SimulatorJudgeVerdict | None,
    cost_cents: float,
) -> None:
    judge_dict = verdict_to_dict(judge_verdict) if judge_verdict else None
    assertions_dicts = [
        {
            "key": r.key,
            "passed": r.passed,
            "evidence": r.evidence,
            "is_critical": r.is_critical,
        }
        for r in assertion_results
    ]

    async with tenant_scope(tenant_id) as conn:
        await finalize_simulation_run(
            conn,
            run_id,
            tenant_id,
            status=status,
            termination_reason=termination_reason,
            turns_count=len(acc.transcript.turns),
            transcript=transcript_to_list(acc.transcript),
            judge_eval=judge_dict,
            assertions_results=assertions_dicts,
            assertions_passed=passed,
            assertions_total=total,
            tokens_simulator=acc.tokens_simulator_in + acc.tokens_simulator_out,
            tokens_agent=acc.tokens_agent_in + acc.tokens_agent_out,
            tokens_judge=acc.tokens_judge_in + acc.tokens_judge_out,
            cost_cents=cost_cents,
        )
        # Soft-delete la conversación sintética
        await soft_delete_conversation(conn, tenant_id, conversation_id)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def simulated_chat_reply(final_state: AgentState) -> str:
    """Lo que recibe el cliente en el chat tras el turno, igual que en `POST
    /webhooks/inbound`: el texto del agente o el acuse fijo de escalado. Un turno con
    error nunca entrega el borrador (`AgentService`)."""
    text = None if final_state.get("error") else final_state.get("agent_response")
    return _chat_ack(final_state) or text or ""


def _chat_ack(final_state: AgentState) -> str | None:
    error = final_state.get("error")
    language, tenant_default = state_languages(final_state)
    return chat_escalation_ack(
        "error" if error else final_state.get("decision"),
        None if error else final_state.get("agent_response"),
        final_state.get("escalation_reason"),
        escalated=final_state.get("escalation_id") is not None,
        language=language,
        tenant_default=tenant_default,
    )


def _last_agent_message(transcript: SimulatorTranscript) -> str:
    for turn in reversed(transcript.turns):
        if turn.role == "agent":
            return turn.content
    return ""


def _finalize_trace(
    observability: ObservabilityClient | None,
    trace: Any,
    final_state: AgentState | None,
    error: str | None = None,
) -> None:
    if observability is None or trace is None:
        return
    state: Any = final_state or {}
    observability.finalize_trace(
        trace,
        decision=state.get("decision"),
        confidence=state.get("confidence"),
        response_text=state.get("agent_response"),
        escalation_reason=state.get("escalation_reason"),
        tokens_in=state.get("tokens_in", 0),
        tokens_cache_write=state.get("tokens_cache_write", 0),
        tokens_cache_read=state.get("tokens_cache_read", 0),
        tokens_out=state.get("tokens_out", 0),
        cost_usd=state.get("cost_usd", 0.0),
        model=state.get("model_used"),
        error=error or state.get("error"),
    )


IDENTITY_MODES = ("sender", "chat")


def scenario_identity_mode(mock_fixtures: dict[str, Any] | None) -> str:
    """Cómo se identifica el cliente simulado: `sender` (escribe desde el email de la
    compra, `verified`) o `chat` (solo cuenta lo que teclea, como el visitante de un chat).
    Va en `mock_fixtures["identity"]` para no tocar el esquema de `simulation_scenarios`."""
    mode = (mock_fixtures or {}).get("identity", "sender")
    if mode not in IDENTITY_MODES:
        raise ValueError(f"identity del escenario debe ser una de {IDENTITY_MODES}, no {mode!r}")
    return str(mode)


def _unbacked_contacts(final_state: AgentState, response: str) -> list[str]:
    """Contactos enmascarados de `response` sin respaldo, con la misma regla del supervisor."""
    from apps.api.agents.nodes.supervise import _literal_evidence
    from apps.api.services.contact_grounding import unbacked_contacts
    from apps.api.services.identity import default_phone_region

    if not response:
        return []
    region = default_phone_region(final_state.get("tenant_config"), final_state.get("tenant_facts"))
    return [c.masked() for c in unbacked_contacts(response, _literal_evidence(final_state), region)]


async def _behavior_evidence(
    tenant_id: UUID, conversation_id: UUID, assertions: dict[str, Any]
) -> tuple[dict[str, dict] | None, int | None]:
    """Lo que algunas assertions leen de la DB: inputs de la aprobación e intentos guest.
    Solo consulta lo que el escenario pide. Borra los intentos para que los fallos de una
    simulación no cuenten en la pausa por tenant de los clientes reales."""
    approval_inputs: dict[str, dict] | None = None
    attempts: int | None = None
    async with tenant_scope(tenant_id) as conn:
        if assertions.get("pending_approval_inputs"):
            approval_inputs = await list_pending_approval_inputs(conn, tenant_id, conversation_id)
        if "identity_attempts" in assertions:
            attempts = await count_conversation_attempts(conn, tenant_id, conversation_id)
        await soft_delete_conversation_checks(conn, tenant_id, conversation_id)
    return approval_inputs, attempts


async def _pending_approval_present(tenant_id: UUID, conversation_id: UUID) -> bool:
    async with tenant_scope(tenant_id) as conn:
        return await has_pending_approval_for_conversation(conn, tenant_id, conversation_id)


def _compute_status(
    all_critical_passed: bool,
    passed: int,
    total: int,
    judge_verdict: SimulatorJudgeVerdict | None,
    *,
    judge_required: bool = True,
) -> str:
    if judge_verdict is None:
        if not judge_required:
            if all_critical_passed:
                return "passed"
            if (passed / total >= 0.5) if total > 0 else False:
                return "partial"
            return "failed"
        return "errored"
    overall = judge_verdict.overall_score
    goal = judge_verdict.judge_goal_achieved
    if all_critical_passed and overall >= 7.5 and goal:
        return "passed"
    if (passed / total >= 0.5 if total > 0 else False) and overall >= 6.0:
        return "partial"
    return "failed"
