"""Worker de turnos inbound: procesa la cola `inbound_jobs` fuera del request (#260).

El webhook solo valida, persiste y encola (`services/inbound_intake.py`); aquí corre el
turno completo: message cap → grafo LangGraph → entrega al helpdesk → resolución /
escalado → uso. Corre dentro del proceso de la API (lifespan), con N slots
concurrentes; la serialización por conversación la garantiza el claim
(`db/inbound_jobs.claim_next_inbound_job`), no el proceso.

Robustez:
- **Heartbeat** renueva el lease mientras el turno corre; si la instancia muere, el lease
  vence y otro worker (o la siguiente instancia al arrancar) reclama el job.
- **Shutdown** (SIGTERM de Cloud Run): el job en curso vuelve a `pending` al instante.
- **Reintento seguro**: un job que ya corrió antes (`is_retry`) comprueba si su inbound
  ya tiene respuesta del agente antes de re-correr el grafo → nunca responde dos veces.
- **Fallos**: antes/durante el grafo → reintento con backoff; agotados → `failed` +
  `logger.error` (alerta). Los pasos post-grafo son best-effort y no reintentan (la
  respuesta puede haber salido ya).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.inbound_jobs import (
    ClaimedInboundJob,
    claim_next_inbound_job,
    complete_inbound_job,
    extend_inbound_job_lease,
    fail_inbound_job,
    get_inbound_message_contents,
    inbound_already_answered,
    release_inbound_job,
)
from apps.api.db.queries import get_conversation, get_tenant_configuration
from apps.api.services.agent_resolution import finalize_agent_resolution, send_agent_reply
from apps.api.services.helpdesk_delivery import load_helpdesk_client
from apps.api.services.helpdesk_escalation import push_escalation_to_helpdesk_safe
from apps.api.services.message_cap import enforce_message_cap
from apps.api.services.usage import UsageRecorder

if TYPE_CHECKING:
    from apps.api.agents.service import AgentOutcome, AgentService
    from apps.api.core.config import Settings
    from apps.api.db.models import Conversation

logger = logging.getLogger(__name__)
_usage_recorder = UsageRecorder()

# Backoff por intento fallido (1º, 2º, …). Más allá del último se reusa el último.
RETRY_BACKOFF_SECONDS: tuple[int, ...] = (30, 120, 300)


class InboundJobError(RuntimeError):
    """El job no se puede procesar con los datos actuales (se reintenta)."""


async def run_inbound_turn(
    job: ClaimedInboundJob,
    *,
    agent_service: AgentService,
    settings: Settings,
) -> str:
    """Ejecuta el turno de un job reclamado. Devuelve la decisión registrada.

    Lanza si falla antes o durante el grafo (el worker reintenta). Los pasos
    posteriores al grafo nunca lanzan.
    """
    async with bootstrap_connection() as conn:
        tenant_config = await get_tenant_configuration(conn, job.tenant_id)

    async with tenant_scope(job.tenant_id) as conn:
        if job.is_retry and await inbound_already_answered(
            conn,
            tenant_id=job.tenant_id,
            conversation_id=job.conversation_id,
            inbound_message_id=job.inbound_message_id,
        ):
            logger.warning(
                "inbound_job_already_answered",
                extra={"tenant_id": str(job.tenant_id), "job_id": str(job.id)},
            )
            return "already_answered"

        conversation = await get_conversation(conn, job.tenant_id, job.conversation_id)
        if conversation is None:
            raise InboundJobError("conversation_not_found")
        contents = await get_inbound_message_contents(
            conn,
            tenant_id=job.tenant_id,
            conversation_id=job.conversation_id,
            message_ids=[*job.absorbed_message_ids, job.inbound_message_id],
        )
        if not contents:
            raise InboundJobError("inbound_message_not_found")
        cap_outcome = await enforce_message_cap(
            conn,
            tenant_id=job.tenant_id,
            conversation_id=job.conversation_id,
            inbound_message_id=job.inbound_message_id,
            tenant_config=tenant_config,
            settings=settings,
        )

    if cap_outcome is not None:
        outcome = cap_outcome
    else:
        # Ráfaga: el turno responde a todos los mensajes absorbidos a la vez.
        outcome = await agent_service.process_inbound(
            tenant_id=job.tenant_id,
            conversation_id=job.conversation_id,
            inbound_message_id=job.inbound_message_id,
            inbound_message_content="\n\n".join(contents),
            channel=job.channel,
            end_customer_id=job.end_customer_id,
        )

    if outcome.decision == "error":
        logger.error(
            "inbound_turn_graph_error",
            extra={
                "tenant_id": str(job.tenant_id),
                "conversation_id": str(job.conversation_id),
                "job_id": str(job.id),
                "error": outcome.error,
            },
        )

    await _deliver_outcome(job, conversation, outcome, settings=settings)
    return outcome.decision


async def _deliver_outcome(
    job: ClaimedInboundJob,
    conversation: Conversation,
    outcome: AgentOutcome,
    *,
    settings: Settings,
) -> None:
    """Entrega + resolución + escalado + uso. Best-effort: nunca lanza."""
    delivered = False
    if outcome.response_text:
        client = None
        try:
            async with tenant_scope(job.tenant_id) as conn:
                client = await load_helpdesk_client(
                    conn, tenant_id=job.tenant_id, conversation=conversation
                )
        except Exception:
            logger.error(
                "agent_reply_helpdesk_load_failed",
                extra={"tenant_id": str(job.tenant_id), "job_id": str(job.id)},
                exc_info=True,
            )
        if client is None:
            logger.error(
                "agent_reply_no_helpdesk",
                extra={
                    "tenant_id": str(job.tenant_id),
                    "conversation_id": str(job.conversation_id),
                    "channel": job.channel,
                },
            )
        else:
            adapter, ctx = client
            delivered = await send_agent_reply(
                adapter,
                ctx,
                str(conversation.external_id),
                outcome.response_text,
                tenant_id=job.tenant_id,
                provider=job.channel,
            )

    # Resolución autónoma: solo si la respuesta llegó al cliente.
    if outcome.resolves_on_delivery:
        try:
            await finalize_agent_resolution(
                tenant_id=job.tenant_id,
                conversation=conversation,
                delivered=delivered,
                settings=settings,
            )
        except Exception:
            logger.error(
                "agent_resolution_finalize_failed",
                extra={"tenant_id": str(job.tenant_id), "job_id": str(job.id)},
                exc_info=True,
            )

    # Escalado: nota interna + asignación al equipo CX, solo al crear la escalación.
    if outcome.escalation_created:
        await push_escalation_to_helpdesk_safe(
            tenant_id=job.tenant_id,
            conversation=conversation,
            reason=outcome.escalation_reason or "unspecified_escalation",
        )

    _usage_recorder.record(
        tenant_id=job.tenant_id,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
        cost_usd=outcome.cost_usd,
    )


def retry_delay_seconds(attempts: int) -> int:
    """Backoff tras el intento nº `attempts` (1-based)."""
    idx = min(max(attempts, 1), len(RETRY_BACKOFF_SECONDS)) - 1
    return RETRY_BACKOFF_SECONDS[idx]


class InboundWorker:
    """N slots que reclaman y ejecutan jobs. `notify()` los despierta al encolar;
    además sondean cada `poll_interval_seconds` (recupera jobs de instancias caídas)."""

    def __init__(
        self,
        *,
        agent_service: AgentService,
        settings: Settings,
        concurrency: int = 2,
        poll_interval_seconds: float = 5.0,
        lease_seconds: int = 120,
    ) -> None:
        self._agent_service = agent_service
        self._settings = settings
        self._concurrency = concurrency
        self._poll_interval = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def notify(self) -> None:
        """Hay un job nuevo: despierta a los slots ociosos."""
        self._wake.set()

    def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._slot_loop(), name=f"inbound-worker-{i}")
            for i in range(self._concurrency)
        ]
        logger.info(
            "inbound_worker_started concurrency=%d lease_seconds=%d",
            self._concurrency,
            self._lease_seconds,
        )

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        logger.info("inbound_worker_stopped")

    async def run_once(self) -> bool:
        """Reclama y ejecuta un job. True si había uno. (Usado por el loop y los tests.)"""
        async with bootstrap_connection() as conn:
            job = await claim_next_inbound_job(conn, lease_seconds=self._lease_seconds)
        if job is None:
            return False
        await self._execute(job)
        return True

    async def _slot_loop(self) -> None:
        while True:
            try:
                had_job = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("inbound_worker_claim_failed")
                had_job = False
            if not had_job:
                await self._wait_for_work()

    async def _wait_for_work(self) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)
        self._wake.clear()

    async def _heartbeat(self, job: ClaimedInboundJob) -> None:
        interval = max(self._lease_seconds / 3, 1)
        while True:
            await asyncio.sleep(interval)
            try:
                async with bootstrap_connection() as conn:
                    await extend_inbound_job_lease(
                        conn, job_id=job.id, lease_seconds=self._lease_seconds
                    )
            except Exception:
                logger.warning("inbound_job_heartbeat_failed job_id=%s", job.id, exc_info=True)

    async def _execute(self, job: ClaimedInboundJob) -> None:
        log_extra = {
            "tenant_id": str(job.tenant_id),
            "conversation_id": str(job.conversation_id),
            "job_id": str(job.id),
            "attempt": job.attempts,
            "absorbed": len(job.absorbed_message_ids),
        }
        queue_wait_ms = int((datetime.now(UTC) - job.enqueued_at).total_seconds() * 1000)
        heartbeat = asyncio.create_task(self._heartbeat(job))
        try:
            decision = await run_inbound_turn(
                job, agent_service=self._agent_service, settings=self._settings
            )
        except asyncio.CancelledError:
            # Shutdown de la instancia: liberar para que otro worker lo retome ya.
            with contextlib.suppress(Exception):
                async with bootstrap_connection() as conn:
                    await asyncio.shield(release_inbound_job(conn, job_id=job.id))
            logger.warning("inbound_job_released_on_shutdown", extra=log_extra)
            raise
        except Exception as exc:
            async with bootstrap_connection() as conn:
                status = await fail_inbound_job(
                    conn,
                    job_id=job.id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_in_seconds=retry_delay_seconds(job.attempts),
                )
            if status == "failed":
                logger.error("inbound_job_failed", extra=log_extra, exc_info=True)
            else:
                logger.warning("inbound_job_retry_scheduled", extra=log_extra, exc_info=True)
            return
        finally:
            heartbeat.cancel()

        async with bootstrap_connection() as conn:
            await complete_inbound_job(conn, job_id=job.id, decision=decision)
        total_ms = int((datetime.now(UTC) - job.enqueued_at).total_seconds() * 1000)
        logger.info(
            "inbound_job_done",
            extra={
                **log_extra,
                "decision": decision,
                "queue_wait_ms": queue_wait_ms,
                "enqueue_to_done_ms": total_ms,
            },
        )
