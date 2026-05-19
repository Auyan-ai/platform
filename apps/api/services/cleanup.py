"""Job de limpieza: cierra conversaciones abandonadas + envía nudges preventivos.

Se ejecuta cada `cleanup_interval_seconds` (default 15 min) como asyncio task
arrancado en el lifespan de FastAPI. Itera todos los tenants y aplica los
timeouts por canal definidos en `tenant_configurations.extra.conversation_timeouts`.

Formato de `extra.conversation_timeouts` (segundos):
    {
        "conversation_timeouts": {
            "email":     259200,   # 72 h
            "chat":      86400,    # 24 h
            "default":   172800    # 48 h — fallback para canales no definidos
        }
    }

Formato del nudge (opt-in por tenant):
    {
        "nudge_enabled": true,
        "nudge_before_seconds": 3600,   # enviar 1h antes del cierre (default)
        "nudge_message": "¿Pudimos ayudarte? Si necesitas algo más estamos aquí 😊"
    }

Si un tenant no define estos campos, se usan los defaults del módulo.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.models import TenantConfiguration
from apps.api.db.queries import (
    delete_expired_rate_limit_buckets,
    get_nudge_candidates,
    get_stale_conversations,
    get_tenant_configuration,
    insert_message,
    list_all_tenants,
    mark_conversations_abandoned,
    mark_conversations_nudged,
)

logger = logging.getLogger(__name__)

DEFAULT_NUDGE_BEFORE_SECONDS = 3_600  # 1 h antes del cierre
DEFAULT_NUDGE_MESSAGE = (
    "¿Pudimos resolver tu consulta? Si hay algo más en lo que podamos ayudarte, "
    "estamos aquí. Esta conversación se cerrará automáticamente si no recibimos respuesta pronto."
)

# Timeouts por canal (segundos). Overrideable por tenant via extra.conversation_timeouts.
DEFAULT_TIMEOUTS: dict[str, int] = {
    "email": 259_200,     # 72 h — email es asíncrono, dar más margen
    "chat": 86_400,       # 24 h
    "widget": 86_400,     # 24 h
    "whatsapp": 172_800,  # 48 h
    "instagram": 172_800, # 48 h
    "zendesk": 259_200,   # 72 h
    "intercom": 259_200,  # 72 h
    "chatwoot": 172_800,  # 48 h
    "default": 172_800,   # 48 h — fallback para canales nuevos
}


def _build_cutoffs(
    config: TenantConfiguration | None,
    now: datetime,
) -> tuple[dict[str, datetime], datetime]:
    """Retorna (cutoffs_por_canal, default_cutoff) con los datetimes de corte.

    Los overrides del tenant se mezclan sobre los defaults del módulo.
    """
    overrides: dict[str, int] = {}
    if config and isinstance(config.extra.get("conversation_timeouts"), dict):
        overrides = config.extra["conversation_timeouts"]

    merged = {**DEFAULT_TIMEOUTS, **overrides}

    default_cutoff = now - timedelta(seconds=merged.get("default", DEFAULT_TIMEOUTS["default"]))
    cutoffs = {
        ch: now - timedelta(seconds=secs)
        for ch, secs in merged.items()
        if ch != "default"
    }
    return cutoffs, default_cutoff


async def _close_abandoned_for_tenant(
    tenant_id: UUID,
    config: TenantConfiguration | None,
) -> int:
    """Cierra conversaciones abandonadas para un tenant. Retorna el nº cerradas."""
    now = datetime.now(UTC)
    channel_cutoffs, default_cutoff = _build_cutoffs(config, now)

    # Pre-filtro SQL: cutoff más permisivo (timeout más corto → datetime más reciente)
    lenient_cutoff = max(channel_cutoffs.values()) if channel_cutoffs else default_cutoff

    async with tenant_scope(tenant_id) as conn:
        candidates = await get_stale_conversations(conn, tenant_id, lenient_cutoff)
        if not candidates:
            return 0

        # Filtro Python: aplica timeout específico por canal
        stale_ids = [
            conv_id
            for conv_id, channel, last_activity in candidates
            if last_activity.replace(tzinfo=UTC) < channel_cutoffs.get(channel, default_cutoff)
        ]
        if not stale_ids:
            return 0

        count = await mark_conversations_abandoned(conn, tenant_id, stale_ids)

    return count


def _build_nudge_cutoffs(
    config: TenantConfiguration | None,
    now: datetime,
) -> tuple[dict[str, tuple[datetime, datetime]], tuple[datetime, datetime]] | None:
    """Retorna (cutoffs_por_canal, default_range) para la ventana de nudge, o None si desactivado.

    Cada valor es (cutoff_min, cutoff_max): last_activity debe caer dentro para hacer nudge.
    - cutoff_max = now - (timeout - nudge_before)  → dentro de la ventana de nudge
    - cutoff_min = now - timeout                    → todavía no cerrada

    Retorna None si nudge_enabled != true en la config del tenant.
    """
    extra = config.extra if config else {}
    if not extra.get("nudge_enabled"):
        return None

    nudge_before: int = int(extra.get("nudge_before_seconds", DEFAULT_NUDGE_BEFORE_SECONDS))
    overrides: dict[str, int] = {}
    if isinstance(extra.get("conversation_timeouts"), dict):
        overrides = extra["conversation_timeouts"]

    merged_timeouts = {**DEFAULT_TIMEOUTS, **overrides}

    def _range(timeout_secs: int) -> tuple[datetime, datetime] | None:
        if nudge_before >= timeout_secs:
            return None  # ventana inválida: nudge_before >= timeout
        cutoff_min = now - timedelta(seconds=timeout_secs)
        cutoff_max = now - timedelta(seconds=timeout_secs - nudge_before)
        return cutoff_min, cutoff_max

    default_timeout = merged_timeouts.get("default", DEFAULT_TIMEOUTS["default"])
    default_range = _range(default_timeout)
    if default_range is None:
        return None

    channel_ranges: dict[str, tuple[datetime, datetime]] = {}
    for ch, secs in merged_timeouts.items():
        if ch == "default":
            continue
        r = _range(secs)
        if r is not None:
            channel_ranges[ch] = r

    return channel_ranges, default_range


async def _nudge_for_tenant(
    tenant_id: UUID,
    config: TenantConfiguration | None,
) -> int:
    """Envía mensajes de nudge a conversaciones dentro de la ventana pre-cierre.

    Retorna el nº de conversaciones a las que se envió el nudge.
    No actualiza last_message_at para no reiniciar el timer del cleanup.
    """
    ranges_result = _build_nudge_cutoffs(config, datetime.now(UTC))
    if ranges_result is None:
        return 0

    channel_ranges, default_range = ranges_result
    extra = config.extra if config else {}
    nudge_message: str = extra.get("nudge_message") or DEFAULT_NUDGE_MESSAGE

    # Pre-filtro SQL: usar el cutoff_max más permisivo (ventana más pequeña → cutoff más reciente)
    all_maxes = [r[1] for r in channel_ranges.values()] + [default_range[1]]
    lenient_cutoff = max(all_maxes)

    async with tenant_scope(tenant_id) as conn:
        candidates = await get_nudge_candidates(conn, tenant_id, lenient_cutoff)
        if not candidates:
            return 0

        # Refinamiento Python: last_activity debe caer dentro de la ventana de su canal
        nudge_ids: list[UUID] = []
        for conv_id, channel, last_activity in candidates:
            cutoff_min, cutoff_max = channel_ranges.get(channel, default_range)
            activity = last_activity.replace(tzinfo=UTC)
            if cutoff_min < activity <= cutoff_max:
                nudge_ids.append(conv_id)

        if not nudge_ids:
            return 0

        # Insertar mensaje de nudge en cada conversación (sin actualizar last_message_at)
        for conv_id in nudge_ids:
            await insert_message(
                conn,
                tenant_id=tenant_id,
                conversation_id=conv_id,
                role="agent_ai",
                direction="outbound",
                content=nudge_message,
            )

        count = await mark_conversations_nudged(conn, tenant_id, nudge_ids)

    return count


async def run_abandoned_cleanup() -> dict[str, int]:
    """Punto de entrada del job: nudges primero, luego cierra abandonadas.

    Retorna {tenant_slug: conversations_closed} solo para tenants con cierres > 0.
    Errores por tenant se loguean y no interrumpen los demás tenants.
    """
    async with bootstrap_connection() as conn:
        tenants = await list_all_tenants(conn)
        expired_buckets = await delete_expired_rate_limit_buckets(conn)
        if expired_buckets > 0:
            logger.debug("rate_limit_buckets_cleaned count=%d", expired_buckets)

    results: dict[str, int] = {}
    for tenant in tenants:
        try:
            async with bootstrap_connection() as conn:
                config = await get_tenant_configuration(conn, tenant.id)

            # Nudge antes de cerrar — no reinicia el timer
            nudged = await _nudge_for_tenant(tenant.id, config)
            if nudged > 0:
                logger.info("nudges_sent tenant=%s count=%d", tenant.slug, nudged)

            count = await _close_abandoned_for_tenant(tenant.id, config)
            if count > 0:
                results[tenant.slug] = count
                logger.info(
                    "abandoned_closed tenant=%s count=%d",
                    tenant.slug,
                    count,
                )
        except Exception:
            logger.exception("cleanup_tenant_error tenant=%s", tenant.slug)

    return results
