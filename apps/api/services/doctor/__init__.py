"""Doctor por tenant: checklist ejecutable de lo que un tenant necesita para funcionar.

Sprint 2.5 (s81): los ~10 bugs del E2E de WhatsApp estaban en los bordes —contratos de APIs
de terceros, configuración sin validar, migraciones sin aplicar—, no en el agente. El doctor
comprueba esos bordes contra el sistema real (catálogo de Postgres, APIs de Zendesk, Zernio,
Shopify y Chatwoot, solo lecturas) y dice qué falta y cómo arreglarlo.

Entradas: `GET /tenants/me/doctor` (super_admin) y `python -m scripts.doctor --tenant <slug>`.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.integrations.zendesk_triggers import admin_client
from apps.api.services.doctor.checks import (
    helpdesk_checks,
    operations_checks,
    schema_check,
    whatsapp_config_checks,
)
from apps.api.services.doctor.live import (
    ZendeskClientFactory,
    describe_error,
    llm_provider_check,
    run_live_checks,
)
from apps.api.services.doctor.report import (
    DoctorCheck,
    DoctorReport,
    count_statuses,
    worst_status,
)
from apps.api.services.doctor.schema import (
    MIGRATIONS_DIR,
    LiveSchema,
    expected_objects,
    read_live_schema,
)
from apps.api.services.doctor.snapshot import (
    TenantNotFoundError,
    TenantSnapshot,
    load_tenant_snapshot,
)

if TYPE_CHECKING:
    import asyncpg
    import httpx

__all__ = [
    "DoctorCheck",
    "DoctorReport",
    "TenantNotFoundError",
    "build_report",
    "default_llm_provider_check",
    "llm_provider_check",
    "platform_checks",
    "run_tenant_doctor",
]

logger = logging.getLogger(__name__)

_GROUP_ORDER = {"platform": 0, "helpdesk": 1, "whatsapp": 2, "commerce": 3, "operations": 4}


async def platform_checks(
    conn: asyncpg.Connection, migrations_dir: Path = MIGRATIONS_DIR
) -> list[DoctorCheck]:
    """Checks globales (no dependen del tenant). `conn` sin tenant scope."""
    if not migrations_dir.is_dir():
        return [
            DoctorCheck(
                id="platform.migrations",
                group="platform",
                title="Migraciones aplicadas",
                status="skip",
                detail=f"No están los ficheros de migración en {migrations_dir}.",
                hint="Incluir supabase/migrations en la imagen (.gcloudignore).",
            )
        ]
    try:
        live: LiveSchema = await read_live_schema(conn)
    except Exception as exc:  # se reporta como check fallido
        logger.warning("doctor_schema_read_failed", exc_info=True)
        return [
            DoctorCheck(
                id="platform.migrations",
                group="platform",
                title="Migraciones aplicadas",
                status="fail",
                detail=f"No se pudo leer el catálogo de Postgres: {describe_error(exc)}.",
            )
        ]
    migrations, objects = expected_objects(migrations_dir)
    return [schema_check(migrations, objects, live)]


async def default_llm_provider_check() -> DoctorCheck:
    """El check de Anthropic con la key y el modelo del clasificador de la configuración."""
    from apps.api.core.config import get_models, get_settings
    from apps.api.integrations.anthropic_client import build_anthropic_client

    settings = get_settings()
    client = build_anthropic_client(settings.anthropic_api_key.get_secret_value())
    return await llm_provider_check(client, get_models().intent_classifier_model)


async def build_report(
    snapshot: TenantSnapshot,
    platform: list[DoctorCheck],
    *,
    api_base_url: str | None,
    started: float,
    zendesk_client_factory: ZendeskClientFactory = admin_client,
    zernio_transport: httpx.AsyncBaseTransport | None = None,
) -> DoctorReport:
    checks = [
        *platform,
        *helpdesk_checks(snapshot),
        *whatsapp_config_checks(snapshot),
        *operations_checks(snapshot),
        *await run_live_checks(
            snapshot,
            api_base_url=api_base_url,
            zendesk_client_factory=zendesk_client_factory,
            zernio_transport=zernio_transport,
        ),
    ]
    checks.sort(key=lambda c: _GROUP_ORDER[c.group])
    report = DoctorReport(
        tenant_id=snapshot.tenant_id,
        tenant_slug=snapshot.slug,
        generated_at=datetime.now(UTC),
        duration_ms=int((time.monotonic() - started) * 1000),
        status=worst_status(checks),
        counts=count_statuses(checks),
        checks=checks,
    )
    logger.info(
        "tenant_doctor_run",
        extra={
            "tenant_id": str(snapshot.tenant_id),
            "status": report.status,
            "counts": report.counts,
            "failed": [c.id for c in checks if c.status == "fail"],
            "duration_ms": report.duration_ms,
        },
    )
    return report


async def run_tenant_doctor(
    tenant_id: UUID, *, crypto_key: bytes, api_base_url: str | None
) -> DoctorReport:
    """Doctor desde la API: lee con el pool y suelta la conexión antes de salir a internet."""
    started = time.monotonic()
    async with bootstrap_connection() as conn:
        platform = await platform_checks(conn)
    platform.append(await default_llm_provider_check())
    async with tenant_scope(tenant_id) as conn:
        snapshot = await load_tenant_snapshot(conn, tenant_id, crypto_key)
    return await build_report(snapshot, platform, api_base_url=api_base_url, started=started)
