from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx
from apps.api.db.client import bootstrap_connection
from apps.api.db.site_ingestions import (
    ClaimedIngestion,
    LeaseLost,
    claim_next_site_ingestion,
    extend_site_ingestion_lease,
    fail_site_ingestion,
    release_site_ingestion,
)
from apps.api.services.knowledge_ingestion import Embedder
from apps.api.services.site_ingestion.auto_approve import auto_approve_if_demo
from apps.api.services.site_ingestion.models import IngestionStatus
from apps.api.services.site_ingestion.orchestrator import NoContentError, run_ingestion

logger = logging.getLogger(__name__)

RETRY_BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 900)


def retry_delay_seconds(attempts: int) -> int:
    idx = min(max(attempts, 1), len(RETRY_BACKOFF_SECONDS)) - 1
    return RETRY_BACKOFF_SECONDS[idx]


class SiteIngestionWorker:
    def __init__(
        self,
        *,
        concurrency: int = 1,
        poll_interval_seconds: float = 15.0,
        lease_seconds: int = 120,
        transport: httpx.AsyncBaseTransport | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._transport = transport
        self._embedder = embedder
        self._concurrency = concurrency
        self._poll_interval = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def notify(self) -> None:
        self._wake.set()

    def start(self) -> None:
        if self._tasks or self._concurrency <= 0:
            return
        self._tasks = [
            asyncio.create_task(self._slot_loop(), name=f"site-ingestion-worker-{i}")
            for i in range(self._concurrency)
        ]
        logger.info(
            "site_ingestion_worker_started concurrency=%d lease_seconds=%d",
            self._concurrency,
            self._lease_seconds,
        )

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def run_once(self) -> bool:
        async with bootstrap_connection() as conn:
            job = await claim_next_site_ingestion(conn, lease_seconds=self._lease_seconds)
        if job is None:
            return False
        await self.execute(job)
        return True

    async def _slot_loop(self) -> None:
        while True:
            try:
                had_job = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("site_ingestion_worker_claim_failed")
                had_job = False
            if not had_job:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)
                self._wake.clear()

    async def _heartbeat(self, job: ClaimedIngestion) -> None:
        interval = max(self._lease_seconds / 3, 1)
        while True:
            await asyncio.sleep(interval)
            try:
                async with bootstrap_connection() as conn:
                    owned = await extend_site_ingestion_lease(
                        conn, job, lease_seconds=self._lease_seconds
                    )
                if not owned:
                    logger.warning("site_ingestion_lease_lost", extra=_log_extra(job))
                    return
            except Exception:
                logger.warning(
                    "site_ingestion_heartbeat_failed", extra=_log_extra(job), exc_info=True
                )

    async def execute(self, job: ClaimedIngestion) -> None:
        extra = _log_extra(job)
        heartbeat = asyncio.create_task(self._heartbeat(job))
        try:
            stats = await run_ingestion(job, transport=self._transport)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                async with bootstrap_connection() as conn:
                    await asyncio.shield(release_site_ingestion(conn, job))
            logger.warning("site_ingestion_released_on_shutdown", extra=extra)
            raise
        except LeaseLost:
            logger.warning("site_ingestion_lease_lost", extra=extra, exc_info=True)
            return
        except NoContentError as exc:
            await self._fail(job, str(exc), retry=False)
            return
        except Exception as exc:
            await self._fail(job, f"{type(exc).__name__}: {exc}", retry=True)
            return
        finally:
            heartbeat.cancel()
        logger.info(
            "site_ingestion_ready",
            extra={
                **extra,
                "platform": stats.platform.value if stats.platform else None,
                "docs": stats.docs,
                "submissions_created": stats.created,
                "requests": stats.requests,
                "rate_limited": stats.rate_limited,
                "seconds": round(stats.seconds, 1),
            },
        )
        await self._auto_approve_demo(job)

    async def _auto_approve_demo(self, job: ClaimedIngestion) -> None:
        if self._embedder is None:
            logger.warning("demo_auto_approve_without_embedder", extra=_log_extra(job))
            return
        try:
            await auto_approve_if_demo(job, self._embedder)
        except Exception:
            logger.exception("demo_auto_approve_failed", extra=_log_extra(job))

    async def _fail(self, job: ClaimedIngestion, reason: str, *, retry: bool) -> None:
        extra = {**_log_extra(job), "reason": reason}
        try:
            async with bootstrap_connection() as conn:
                status = await fail_site_ingestion(
                    conn,
                    job,
                    reason=reason,
                    retry_in_seconds=retry_delay_seconds(job.attempts) if retry else None,
                )
        except LeaseLost:
            logger.warning("site_ingestion_lease_lost", extra=extra)
            return
        if status is IngestionStatus.FAILED:
            logger.error("site_ingestion_failed", extra=extra)
        else:
            logger.warning("site_ingestion_retry_scheduled", extra=extra)


def _log_extra(job: ClaimedIngestion) -> dict[str, str | int]:
    return {
        "tenant_id": str(job.tenant_id),
        "ingestion_id": str(job.id),
        "root_url": job.root_url,
        "attempt": job.attempts,
    }
