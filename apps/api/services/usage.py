"""Tracking de uso diario por tenant y gate de presupuesto pre-grafo.

check_tenant_budget   — lanza BudgetExceededError si el tenant superó su límite diario.
schedule_record_usage — fire-and-forget: registra tokens y costo tras el grafo.

Presupuesto por defecto: Settings.budget_usd_daily.
Override per-tenant:    tenant_configurations.extra["budget_usd_daily"] (float, USD).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID

from apps.api.core.errors import BudgetExceededError
from apps.api.db.client import bootstrap_connection
from apps.api.db.queries import get_tenant_usage_today, upsert_tenant_usage_daily

if TYPE_CHECKING:
    import asyncpg
    from apps.api.core.config import Settings
    from apps.api.db.models import TenantConfiguration

logger = logging.getLogger(__name__)


def _seconds_until_midnight_utc() -> int:
    """Segundos hasta la próxima medianoche UTC (mínimo 1)."""
    now = datetime.datetime.now(datetime.UTC)
    tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


async def check_tenant_budget(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    tenant_config: TenantConfiguration | None,
    settings: Settings,
) -> None:
    """Verifica si el tenant tiene presupuesto disponible para hoy.

    Lanza BudgetExceededError con Retry-After=segundos_hasta_medianoche_UTC
    si el costo acumulado del día supera el límite configurado.
    Si no hay registro de uso hoy, pasa sin problema (primer request del día).
    """
    budget: float = settings.budget_usd_daily
    if tenant_config is not None:
        override = tenant_config.extra.get("budget_usd_daily")
        if isinstance(override, int | float) and override > 0:
            budget = float(override)

    usage = await get_tenant_usage_today(conn, tenant_id=tenant_id)
    if usage is None:
        return

    if usage.cost_usd >= budget:
        retry_after = _seconds_until_midnight_utc()
        logger.warning(
            "budget_exceeded",
            extra={
                "tenant_id": str(tenant_id),
                "cost_usd": usage.cost_usd,
                "budget_usd": budget,
            },
        )
        raise BudgetExceededError(
            f"Presupuesto diario agotado ({usage.cost_usd:.4f}/{budget:.2f} USD). "
            "Se restablece a medianoche UTC.",
            retry_after=retry_after,
        )


class UsageRecorder:
    """Registra uso diario de forma fire-and-forget, con refs fuertes a tasks en vuelo."""

    _pending_tasks: ClassVar[set[asyncio.Task[None]]] = set()

    def record(
        self,
        *,
        tenant_id: UUID,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        requests: int = 1,
    ) -> None:
        """Encola el registro de uso. Noop si no hay event loop o si el uso es cero.

        `requests`: cuánto suma a `request_count` (1 por turno; 0 para llamadas sueltas,
        como el mensaje tras una aprobación, que gastan pero no son un turno)."""
        if tokens_in == 0 and tokens_out == 0 and cost_usd == 0.0:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # sin event loop — tests síncronos

        task = loop.create_task(
            self._insert(
                tenant_id=tenant_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                requests=requests,
            ),
            name=f"record_usage_{tenant_id}",
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _insert(
        self,
        *,
        tenant_id: UUID,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        requests: int,
    ) -> None:
        try:
            async with bootstrap_connection() as conn:
                await upsert_tenant_usage_daily(
                    conn,
                    tenant_id=tenant_id,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    requests=requests,
                )
        except Exception:
            logger.exception(
                "record_tenant_usage_failed",
                extra={"tenant_id": str(tenant_id)},
            )
