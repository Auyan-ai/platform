"""Listener de invalidación de cache de AOPs vía Postgres NOTIFY.

Cuando un worker guarda una nueva versión de AOP, emite
`pg_notify('aop_cache_invalidated', payload)` dentro de la transacción.
Al hacer commit, Postgres entrega la notificación a todos los workers que
estén haciendo LISTEN en ese canal — incluyendo los que corren en otras
instancias de Railway.

Cada worker tiene su propio AopCacheListener con una conexión asyncpg
dedicada (fuera del pool). Las conexiones LISTEN no pueden ejecutar queries
normales mientras esperan notificaciones, por eso deben ser separadas.
"""

from __future__ import annotations

import asyncio
import json
import logging

import asyncpg
from apps.api.aops.compiler import invalidate_aop_cache

logger = logging.getLogger(__name__)

_CHANNEL = "aop_cache_invalidated"
_KEEPALIVE_INTERVAL = 30  # segundos


class AopCacheListener:
    """Escucha Postgres NOTIFY e invalida el cache local de AOPs.

    Uso:
        listener = AopCacheListener()
        await listener.start(dsn)           # en lifespan startup
        ...
        await listener.stop()               # en lifespan shutdown
    """

    def __init__(self) -> None:
        self._conn: asyncpg.Connection | None = None
        self._task: asyncio.Task | None = None

    async def start(self, dsn: str) -> None:
        """Crea conexión dedicada, registra listener y arranca keep-alive."""
        self._conn = await asyncpg.connect(dsn)
        await self._conn.add_listener(_CHANNEL, self._on_notify)
        self._task = asyncio.create_task(
            self._keep_alive_loop(),
            name="aop-cache-listener-keepalive",
        )
        logger.info("aop_cache_listener.started channel=%s", _CHANNEL)

    async def stop(self) -> None:
        """Cancela el keep-alive y cierra la conexión."""
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

        if self._conn is not None and not self._conn.is_closed():
            try:
                await self._conn.remove_listener(_CHANNEL, self._on_notify)
            except Exception:
                logger.debug("aop_cache_listener.remove_listener_error", exc_info=True)
            await self._conn.close()
            self._conn = None

        logger.info("aop_cache_listener.stopped")

    def _on_notify(
        self,
        conn: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Callback síncrono llamado por asyncpg al recibir una notificación."""
        try:
            data = json.loads(payload)
            tenant_id: str = data["tenant_id"]
            slug: str = data["slug"]
            workspace: str = data["workspace"]
        except (json.JSONDecodeError, KeyError):
            logger.exception("aop_cache_listener.parse_error payload=%r", payload)
            return

        invalidate_aop_cache(tenant_id, slug, workspace)
        logger.info(
            "aop_cache.invalidated tenant=%s slug=%s workspace=%s",
            tenant_id,
            slug,
            workspace,
        )

    async def _keep_alive_loop(self) -> None:
        """Ping periódico para evitar que la conexión idle sea cerrada por el proxy."""
        while True:
            try:
                await asyncio.sleep(_KEEPALIVE_INTERVAL)
                if self._conn is not None and not self._conn.is_closed():
                    await self._conn.execute("SELECT 1")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("aop_cache_listener.keepalive_error")
