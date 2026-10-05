"""Checks del doctor que no salen a internet: esquema, configuración y actividad.

Cada función recibe datos ya cargados y devuelve `DoctorCheck`s. Las pistas (`hint`)
dicen qué hacer, con el comando exacto cuando lo hay.
"""

from __future__ import annotations

from datetime import UTC, datetime

from apps.api.services.doctor.report import DoctorCheck
from apps.api.services.doctor.schema import LiveSchema, SchemaObject, migration_statuses
from apps.api.services.doctor.snapshot import STUCK_JOB_MINUTES, TenantSnapshot
from apps.api.services.handoff import supports_handoff

MAX_LISTED = 5
TRIGGERS_SCRIPT = "python -m scripts.setup_zendesk_handoff_triggers --tenant {slug}"
ONBOARD_SCRIPT = "python -m scripts.onboard_whatsapp {cmd} --tenant {slug}"


def _ago(moment: datetime, now: datetime) -> str:
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 3600:
        return f"hace {seconds // 60} min"
    if seconds < 86400:
        return f"hace {seconds // 3600} h"
    return f"hace {seconds // 86400} d"


# ─── Plataforma ───────────────────────────────────────────────────────────────


def schema_check(
    migrations: list[str], objects: list[SchemaObject], live: LiveSchema
) -> DoctorCheck:
    statuses = migration_statuses(migrations, objects, live)
    pending = [s for s in statuses if s.state in ("missing", "partial")]
    verifiable = [s for s in statuses if s.state != "unverifiable"]
    if not pending:
        detail = f"{len(verifiable)}/{len(statuses)} migraciones verificables, todas aplicadas."
        if live.buckets is None:
            detail += " No se pudo leer storage.buckets: los buckets no se comprobaron."
        return DoctorCheck(
            id="platform.migrations",
            group="platform",
            title="Migraciones aplicadas",
            status="ok",
            detail=detail,
        )
    lines = []
    for status in pending[:MAX_LISTED]:
        missing = ", ".join(status.missing[:3])
        extra = f" (+{len(status.missing) - 3})" if len(status.missing) > 3 else ""
        lines.append(f"{status.migration}: falta {missing}{extra}")
    if len(pending) > MAX_LISTED:
        lines.append(f"… y {len(pending) - MAX_LISTED} más")
    return DoctorCheck(
        id="platform.migrations",
        group="platform",
        title="Migraciones aplicadas",
        status="fail",
        detail=f"{len(pending)} migración(es) sin aplicar o a medias:\n" + "\n".join(lines),
        hint=(
            "Aplicar en orden con psql o el SQL Editor de Supabase: "
            + ", ".join(f"supabase/migrations/{s.migration}" for s in pending[:MAX_LISTED])
        ),
    )


# ─── Helpdesk ─────────────────────────────────────────────────────────────────


def helpdesk_checks(snapshot: TenantSnapshot) -> list[DoctorCheck]:
    whatsapp = snapshot.find("channel", "zernio")
    helpdesks = snapshot.of_kind("helpdesk")
    primary = snapshot.primary("helpdesk")
    checks: list[DoctorCheck] = []

    if primary is None:
        names = ", ".join(sorted(h.provider for h in helpdesks)) or "ninguno"
        checks.append(
            DoctorCheck(
                id="helpdesk.primary",
                group="helpdesk",
                title="Helpdesk primario",
                status="fail" if whatsapp else "warn",
                detail=(
                    f"No hay helpdesk primario activo (conectados: {names}). "
                    "Los escalados solo quedan en el dashboard de Auyan."
                ),
                hint="Marcar como primario el helpdesk donde trabaja el equipo CX del cliente.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                id="helpdesk.primary",
                group="helpdesk",
                title="Helpdesk primario",
                status="ok",
                detail=f"{primary.provider} (activo y primario).",
            )
        )

    if whatsapp is not None:
        if primary is not None and supports_handoff(primary.provider):
            checks.append(
                DoctorCheck(
                    id="helpdesk.handoff_target",
                    group="helpdesk",
                    title="Destino del handoff de WhatsApp",
                    status="ok",
                    detail=f"Los escalados de WhatsApp abren ticket en {primary.provider}.",
                )
            )
        else:
            provider = primary.provider if primary else "ninguno"
            checks.append(
                DoctorCheck(
                    id="helpdesk.handoff_target",
                    group="helpdesk",
                    title="Destino del handoff de WhatsApp",
                    status="fail",
                    detail=(
                        f"El helpdesk primario ({provider}) no admite handoff: los escalados "
                        "de WhatsApp no llegan al equipo del cliente."
                    ),
                    hint="Marcar como primario un helpdesk con handoff (hoy: zendesk).",
                )
            )

    for helpdesk in helpdesks:
        if helpdesk.credentials_error:
            checks.append(
                DoctorCheck(
                    id=f"helpdesk.{helpdesk.provider}.credentials",
                    group="helpdesk",
                    title=f"Credenciales de {helpdesk.provider}",
                    status="fail",
                    detail=f"Credenciales {helpdesk.credentials_error}.",
                    hint="Reconectar la integración (o revisar INTEGRATIONS_SECRET_KEY).",
                )
            )
        if helpdesk.provider == "zendesk" and helpdesk.credentials is not None:
            checks.extend(_zendesk_config_checks(snapshot, helpdesk.credentials, helpdesk.config))
    return checks


def _zendesk_config_checks(
    snapshot: TenantSnapshot, credentials: dict, config: dict
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    if not config.get("subdomain"):
        checks.append(
            DoctorCheck(
                id="helpdesk.zendesk.subdomain",
                group="helpdesk",
                title="Subdominio de Zendesk",
                status="fail",
                detail="Sin `subdomain`: el webhook de Zendesk no puede resolver el tenant.",
                hint="Reconfigurar Zendesk con scripts.configure_staging_integrations.",
            )
        )
    if credentials.get("webhook_signing_secret"):
        checks.append(
            DoctorCheck(
                id="helpdesk.zendesk.signature",
                group="helpdesk",
                title="Firma del webhook de Zendesk",
                status="ok",
                detail="Se valida X-Zendesk-Webhook-Signature.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                id="helpdesk.zendesk.signature",
                group="helpdesk",
                title="Firma del webhook de Zendesk",
                status="warn",
                detail=(
                    "Sin `webhook_signing_secret`: /webhooks/zendesk acepta este subdominio "
                    "sin validar la firma."
                ),
                hint="Guardar el signing secret del webhook de Zendesk en las credenciales.",
            )
        )
    if snapshot.find("channel", "zernio") is not None and not config.get("api_user_id"):
        checks.append(
            DoctorCheck(
                id="helpdesk.zendesk.api_user",
                group="helpdesk",
                title="Usuario del API de Zendesk",
                status="warn",
                detail="Falta `api_user_id`: no se distingue al usuario de Auyan en Zendesk.",
                hint=TRIGGERS_SCRIPT.format(slug=snapshot.slug),
            )
        )
    return checks


# ─── WhatsApp (Zernio) ────────────────────────────────────────────────────────


def whatsapp_config_checks(snapshot: TenantSnapshot) -> list[DoctorCheck]:
    integration = snapshot.find("channel", "zernio")
    if integration is None:
        return [
            DoctorCheck(
                id="whatsapp.integration",
                group="whatsapp",
                title="Integración de WhatsApp",
                status="skip",
                detail="El tenant no tiene WhatsApp (Zernio).",
            )
        ]
    slug = snapshot.slug
    checks: list[DoctorCheck] = []
    config = integration.config
    sandbox = bool(config.get("sandbox"))

    if not integration.is_active:
        checks.append(
            DoctorCheck(
                id="whatsapp.integration",
                group="whatsapp",
                title="Integración de WhatsApp",
                status="fail",
                detail="Preparada pero inactiva: falta que el cliente termine el alta de Meta.",
                hint=ONBOARD_SCRIPT.format(cmd="finalize", slug=slug),
            )
        )
    elif sandbox:
        checks.append(
            DoctorCheck(
                id="whatsapp.integration",
                group="whatsapp",
                title="Integración de WhatsApp",
                status="warn",
                detail=(
                    "Activa sobre el SANDBOX compartido de Zernio: solo pruebas (key con "
                    "caducidad de 30 días, sesión del móvil de 7 días, 50 mensajes/día)."
                ),
                hint=(
                    ONBOARD_SCRIPT.format(cmd="offboard", slug=slug)
                    + " y después prepare/finalize con el número real."
                ),
            )
        )
    else:
        phone = config.get("phone_number") or "número sin registrar"
        checks.append(
            DoctorCheck(
                id="whatsapp.integration",
                group="whatsapp",
                title="Integración de WhatsApp",
                status="ok",
                detail=f"Activa con número propio ({phone}).",
            )
        )

    if integration.credentials_error:
        checks.append(
            DoctorCheck(
                id="whatsapp.credentials",
                group="whatsapp",
                title="Credenciales de Zernio",
                status="fail",
                detail=f"Credenciales {integration.credentials_error}.",
                hint=ONBOARD_SCRIPT.format(cmd="prepare", slug=slug),
            )
        )
    elif integration.credentials is not None:
        missing = [k for k in ("api_key", "webhook_secret") if not integration.credentials.get(k)]
        checks.append(
            DoctorCheck(
                id="whatsapp.credentials",
                group="whatsapp",
                title="Credenciales de Zernio",
                status="fail" if missing else "ok",
                detail=(
                    f"Faltan: {', '.join(missing)}. Sin webhook_secret, /webhooks/zernio "
                    "responde 500 a todos los eventos."
                    if missing
                    else "Key limitada y secreto del webhook guardados."
                ),
                hint=ONBOARD_SCRIPT.format(cmd="prepare", slug=slug) if missing else None,
            )
        )

    if integration.is_active and not config.get("account_id"):
        checks.append(
            DoctorCheck(
                id="whatsapp.account",
                group="whatsapp",
                title="Cuenta de WhatsApp",
                status="fail",
                detail="Sin `account_id`: los webhooks no se pueden enrutar a este tenant.",
                hint=ONBOARD_SCRIPT.format(cmd="finalize", slug=slug),
            )
        )

    if integration.is_active and not sandbox:
        template = config.get("reengagement_template") or {}
        checks.append(
            DoctorCheck(
                id="whatsapp.reengagement_template",
                group="whatsapp",
                title="Plantilla de re-enganche",
                status="ok" if template.get("name") else "fail",
                detail=(
                    f"`{template.get('name')}` ({template.get('language')}). Su aprobación por "
                    "Meta se ve en WhatsApp Manager."
                    if template.get("name")
                    else "Sin plantilla: fuera de la ventana de 24 h no se puede responder."
                ),
                hint=None
                if template.get("name")
                else ONBOARD_SCRIPT.format(cmd="finalize", slug=slug),
            )
        )
    return checks


# ─── Operación ────────────────────────────────────────────────────────────────


def operations_checks(snapshot: TenantSnapshot, now: datetime | None = None) -> list[DoctorCheck]:
    now = now or datetime.now(UTC)
    activity = snapshot.activity
    checks: list[DoctorCheck] = []

    if activity.last_inbound_by_channel:
        parts = [
            f"{channel} {_ago(moment, now)}"
            for channel, moment in sorted(activity.last_inbound_by_channel.items())
        ]
        checks.append(
            DoctorCheck(
                id="operations.last_inbound",
                group="operations",
                title="Último mensaje entrante",
                status="ok",
                detail="Por canal: " + ", ".join(parts) + ".",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                id="operations.last_inbound",
                group="operations",
                title="Último mensaje entrante",
                status="warn",
                detail="Ningún mensaje de cliente real en los últimos 30 días.",
                hint="Si el tenant debería tener tráfico, revisar los webhooks de cada canal.",
            )
        )

    failed = ""
    if activity.failed_jobs_24h:
        error = (activity.last_job_error or "sin detalle")[:200]
        failed = f"{activity.failed_jobs_24h} turno(s) fallido(s) en 24 h. Último error: {error}"
    if activity.stuck_jobs:
        checks.append(
            DoctorCheck(
                id="operations.stuck_jobs",
                group="operations",
                title="Cola de turnos",
                status="fail",
                detail=(
                    f"{activity.stuck_jobs} turno(s) esperando más de {STUCK_JOB_MINUTES} min "
                    "en inbound_jobs: el worker no los está reclamando."
                    + (f"\n{failed}" if failed else "")
                ),
                hint="Revisar los logs de Cloud Run (inbound_worker) y que haya instancia viva.",
            )
        )
    elif failed:
        checks.append(
            DoctorCheck(
                id="operations.stuck_jobs",
                group="operations",
                title="Cola de turnos",
                status="warn",
                detail=failed,
                hint="Buscar el job en los logs de Cloud Run (inbound_job_failed).",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                id="operations.stuck_jobs",
                group="operations",
                title="Cola de turnos",
                status="ok",
                detail="Sin turnos atascados ni fallidos en 24 h.",
            )
        )
    return checks
