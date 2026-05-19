"""Rate limiting para webhooks inbound.

Ventana fija de 60s por tenant y por end_customer.
Los límites se pueden overridear per-tenant en tenant_configurations.extra.rate_limits:

    {
        "rate_limits": {
            "tenant_per_minute": 600,
            "customer_per_minute": 60
        }
    }

Si el limite se excede, lanza RateLimitError (→ HTTP 429 con Retry-After header).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.core.errors import RateLimitError
from apps.api.db.queries import check_and_increment_rate_limit

if TYPE_CHECKING:
    import asyncpg
    from apps.api.core.config import Settings
    from apps.api.db.models import TenantConfiguration

logger = logging.getLogger(__name__)


async def enforce_rate_limit(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    tenant_config: TenantConfiguration | None,
    customer_id: UUID | None,
    settings: Settings,
) -> None:
    """Verifica y registra rate limit para un inbound webhook.

    Comprueba dos buckets en secuencia:
      1. tenant  → límite global de requests por tenant/minuto
      2. customer → límite por end_customer/minuto (solo si customer_id está disponible)

    Lanza RateLimitError si cualquiera supera su límite.
    No lanza si el tenant o el customer no están identificados (fail-open).
    """
    rate_limits: dict = {}
    if tenant_config and isinstance(tenant_config.extra.get("rate_limits"), dict):
        rate_limits = tenant_config.extra["rate_limits"]

    tenant_limit: int = int(
        rate_limits.get("tenant_per_minute", settings.rate_limit_tenant_per_minute)
    )
    customer_limit: int = int(
        rate_limits.get("customer_per_minute", settings.rate_limit_customer_per_minute)
    )

    # Bucket 1 — por tenant
    tenant_count = await check_and_increment_rate_limit(
        conn,
        tenant_id=tenant_id,
        bucket_key="tenant",
    )
    if tenant_count > tenant_limit:
        logger.warning(
            "rate_limit_exceeded_tenant",
            extra={"tenant_id": str(tenant_id), "count": tenant_count, "limit": tenant_limit},
        )
        raise RateLimitError(
            f"Demasiadas requests para este tenant ({tenant_count}/{tenant_limit} por minuto)",
            retry_after=60,
        )

    # Bucket 2 — por end_customer (solo si lo conocemos)
    if customer_id is not None:
        customer_count = await check_and_increment_rate_limit(
            conn,
            tenant_id=tenant_id,
            bucket_key=f"customer:{customer_id}",
        )
        if customer_count > customer_limit:
            logger.warning(
                "rate_limit_exceeded_customer",
                extra={
                    "tenant_id": str(tenant_id),
                    "customer_id": str(customer_id),
                    "count": customer_count,
                    "limit": customer_limit,
                },
            )
            raise RateLimitError(
                f"Demasiadas requests para este cliente "
                f"({customer_count}/{customer_limit} por minuto)",
                retry_after=60,
            )
