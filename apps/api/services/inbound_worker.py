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
from typing import TYPE_CHECKING, Any
from uuid import UUID

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
from apps.api.db.queries import (
    get_active_handoff_for_chat,
    get_active_integration,
    get_conversation,
    get_tenant_configuration,
    insert_message,
    update_conversation_last_message,
)
from apps.api.services.agent_resolution import finalize_agent_resolution, send_agent_reply
from apps.api.services.channel_delivery import deliver_to_customer, flush_pending_messages
from apps.api.services.channel_routing import is_messaging_channel, load_delivery_client
from apps.api.services.handoff import close_handoff, forward_customer_message, is_approval_gate
from apps.api.services.helpdesk_escalation import push_escalation_to_helpdesk_safe
from apps.api.services.inbound_media import fallback_message, process_inbound_media
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

    if is_messaging_channel(conversation.channel):
        pre_graph_decision, contents = await _messaging_pre_graph(
            job,
            conversation,
            contents,
            settings=settings,
            observability=getattr(agent_service, "observability", None),
        )
        if pre_graph_decision is not None:
            return pre_graph_decision

    async with tenant_scope(job.tenant_id) as conn:
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

    delivered = await _deliver_outcome(job, conversation, outcome, settings=settings)
    if outcome.response_text and not delivered:
        # Queda visible en la cola: el cliente NO recibió la respuesta.
        return f"{outcome.decision}:undelivered"
    return outcome.decision


async def _messaging_pre_graph(
    job: ClaimedInboundJob,
    conversation: Conversation,
    contents: list[str],
    *,
    settings: Settings,
    observability: Any | None = None,
) -> tuple[str | None, list[str]]:
    """Pasos deterministas previos al grafo en canales de mensajería (WhatsApp).

    0. Adjuntos: descarga a Storage, transcripción de notas de voz y marca de "imagen que
       no puedes ver" (`services.inbound_media`). Recalcula el contenido del turno.
    1. Entregar lo que esperaba la ventana (el comprador acaba de escribir: está abierta).
    2. Handoff activo → la IA calla: `helpdesk` reenvía el mensaje (y sus adjuntos) al
       ticket (`handoff_forwarded`); `device` vigente → `human_hold`; `device` vencido →
       se cierra y sigue.
    3. Sin texto útil (solo imagen, sticker, audio no transcrito…) → mensaje fijo del
       tenant, sin grafo (`media_fallback`).
    Devuelve (decisión si el turno termina aquí o None para correr el grafo, contenidos).
    """
    media = await process_inbound_media(
        job=job, conversation=conversation, settings=settings, observability=observability
    )
    if media.transcription_cost_usd > 0:
        _usage_recorder.record(
            tenant_id=job.tenant_id,
            tokens_in=0,
            tokens_out=0,
            cost_usd=media.transcription_cost_usd,
        )
    contents = media.texts
    async with tenant_scope(job.tenant_id) as conn:
        await flush_pending_messages(conn, tenant_id=job.tenant_id, conversation=conversation)
        handoff = await get_active_handoff_for_chat(
            conn, job.tenant_id, conversation.channel, str(conversation.external_id)
        )
        if handoff is not None and handoff.target == "device":
            expires_at = handoff.expires_at
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at is not None and expires_at > datetime.now(UTC):
                return "human_hold", contents
            await close_handoff(
                conn, tenant_id=job.tenant_id, handoff=handoff, reason="device_hold_expired"
            )
            handoff = None
    if handoff is not None:
        forwarded = await forward_customer_message(
            tenant_id=job.tenant_id,
            handoff=handoff,
            content="\n\n".join(contents),
            attachments=media.attachments,
        )
        # Si falla queda visible en la cola: el mensaje no llegó al ticket (logger.error).
        return ("handoff_forwarded" if forwarded else "handoff_forward_failed"), contents
    if media.fallback_kind is not None:
        await _send_fixed_message(job, conversation, media.fallback_kind)
        return "media_fallback", contents
    return None, contents


async def _send_fixed_message(
    job: ClaimedInboundJob, conversation: Conversation, kind: str
) -> None:
    """Mensaje FIJO del tenant por el canal de mensajería (sin LLM). Nunca lanza.

    Cuando no hay nada que razonar (adjunto sin texto, audio ilegible) y como acuse de un
    escalado que no llevó respuesta al cliente."""
    extra = {"tenant_id": str(job.tenant_id), "job_id": str(job.id), "kind": kind}
    try:
        async with tenant_scope(job.tenant_id) as conn:
            integration = await get_active_integration(
                conn, tenant_id=job.tenant_id, kind="channel", provider="zernio"
            )
            content = fallback_message(kind, integration.config if integration else None)
            message = await insert_message(
                conn,
                tenant_id=job.tenant_id,
                conversation_id=conversation.id,
                role="agent_ai",
                direction="outbound",
                content=content,
                metadata={"fixed_message": kind},
            )
            await update_conversation_last_message(conn, job.tenant_id, conversation.id)
        async with tenant_scope(job.tenant_id) as conn:
            result = await deliver_to_customer(
                conn,
                tenant_id=job.tenant_id,
                conversation=conversation,
                content=content,
                message_id=message.id,
            )
    except Exception:
        logger.error("fixed_message_failed", extra=extra, exc_info=True)
        return
    if result != "delivered":
        logger.error("fixed_message_not_delivered", extra={**extra, "result": result})
    else:
        logger.info("fixed_message_sent", extra=extra)


async def _deliver_outcome(
    job: ClaimedInboundJob,
    conversation: Conversation,
    outcome: AgentOutcome,
    *,
    settings: Settings,
) -> bool:
    """Entrega + resolución + escalado + uso. Best-effort: nunca lanza.

    Devuelve True si la respuesta llegó al helpdesk del cliente."""
    delivered = False
    if outcome.response_text and is_messaging_channel(conversation.channel):
        delivered = await _deliver_messaging_reply(job, conversation, outcome)
    elif outcome.response_text:
        client = None
        try:
            async with tenant_scope(job.tenant_id) as conn:
                client = await load_delivery_client(
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

    # Escalado: nota interna + asignación al equipo CX, solo al crear la escalación. En
    # mensajería también si ya existía: si el turno llegó al grafo es que NO hay handoff
    # activo (si lo hubiera, el mensaje se habría reenviado al ticket), así que se reintenta
    # abrirlo (s81: un handoff fallido dejaba la escalación huérfana y nadie la atendía).
    retry_handoff = is_messaging_channel(conversation.channel) and outcome.decision == "escalate"
    if outcome.escalation_created or retry_handoff:
        reason = outcome.escalation_reason or "unspecified_escalation"
        await push_escalation_to_helpdesk_safe(
            tenant_id=job.tenant_id, conversation=conversation, reason=reason
        )
        # En un chat nadie ve un ticket `pending`: si el turno escaló sin llegarle nada al
        # cliente, acuse fijo (haya o no handoff; si no lo hay, ya salió `handoff_unavailable`
        # como ERROR). La puerta L3 no: la IA sigue atendiendo y ya respondió.
        if (
            is_messaging_channel(conversation.channel)
            and not delivered
            and not is_approval_gate(reason)
        ):
            await _send_fixed_message(job, conversation, "escalation_ack")

    _usage_recorder.record(
        tenant_id=job.tenant_id,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
        cost_usd=outcome.cost_usd,
    )
    return delivered


async def _deliver_messaging_reply(
    job: ClaimedInboundJob,
    conversation: Conversation,
    outcome: AgentOutcome,
) -> bool:
    """WhatsApp: entrega con ventana, formato e `Idempotency-Key` = id del mensaje del
    agente (un reintento del job nunca duplica el mensaje en el móvil). Nunca lanza."""
    message_id = UUID(outcome.output_message_id) if outcome.output_message_id else None
    try:
        async with tenant_scope(job.tenant_id) as conn:
            result = await deliver_to_customer(
                conn,
                tenant_id=job.tenant_id,
                conversation=conversation,
                content=str(outcome.response_text),
                message_id=message_id,
            )
    except Exception:
        logger.error(
            "agent_reply_messaging_delivery_failed",
            extra={"tenant_id": str(job.tenant_id), "job_id": str(job.id)},
            exc_info=True,
        )
        return False
    if result != "delivered":
        logger.error(
            "agent_reply_not_delivered",
            extra={
                "tenant_id": str(job.tenant_id),
                "conversation_id": str(job.conversation_id),
                "result": result,
            },
        )
    return result == "delivered"


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
