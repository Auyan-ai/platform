"""Checks del doctor que llaman a las APIs reales (solo lecturas).

Cada proveedor corre en paralelo con su propio timeout. Un fallo de red o de auth no
tumba el informe: se convierte en un check `fail` con el motivo y queda en el log.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from apps.api.core.errors import ExternalIntegrationError
from apps.api.integrations.anthropic_client import (
    LLMProviderUnavailable,
    call_claude_with_tools,
)
from apps.api.integrations.chatwoot import ChatwootClient
from apps.api.integrations.shopify import ShopifyClient, ensure_shopify_access_token
from apps.api.integrations.zendesk import ZendeskClient
from apps.api.integrations.zendesk_triggers import (
    NOT_HANDOFF_CONDITION,
    admin_client,
    find_auyan_webhook,
    find_inbound_triggers,
    reply_trigger,
    solved_trigger,
)
from apps.api.integrations.zernio import ZernioClient
from apps.api.services.doctor.checks import ONBOARD_SCRIPT, TRIGGERS_SCRIPT
from apps.api.services.doctor.report import CheckGroup, DoctorCheck
from apps.api.services.doctor.snapshot import IntegrationSnapshot, TenantSnapshot

logger = logging.getLogger(__name__)

LIVE_TIMEOUT_S = 20
_GROUP_BY_KIND: dict[str, CheckGroup] = {
    "helpdesk": "helpdesk",
    "channel": "whatsapp",
    "commerce": "commerce",
}

ZendeskClientFactory = Callable[[dict[str, Any], str], Awaitable[ZendeskClient]]


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} en {exc.request.url.path}"
    if isinstance(exc, asyncio.TimeoutError | httpx.TimeoutException):
        return f"sin respuesta en {LIVE_TIMEOUT_S} s"
    if isinstance(exc, httpx.TransportError):
        return f"error de red ({type(exc).__name__})"
    if isinstance(exc, ExternalIntegrationError):
        return str(exc)
    return f"{type(exc).__name__}: {str(exc)[:200]}"


async def _guarded(
    snapshot: TenantSnapshot,
    check_id: str,
    group: CheckGroup,
    title: str,
    run: Callable[[], Awaitable[list[DoctorCheck]]],
) -> list[DoctorCheck]:
    try:
        return await asyncio.wait_for(run(), timeout=LIVE_TIMEOUT_S)
    except Exception as exc:  # el fallo ES el resultado del check
        logger.warning(
            "doctor_live_check_failed",
            extra={"tenant_id": str(snapshot.tenant_id), "check": check_id},
            exc_info=True,
        )
        return [
            DoctorCheck(
                id=check_id,
                group=group,
                title=title,
                status="fail",
                detail=f"La llamada falló: {describe_error(exc)}.",
                hint="Revisar las credenciales o reconectar la integración.",
            )
        ]


# ─── Zendesk ──────────────────────────────────────────────────────────────────


def _norm_conditions(conditions: dict[str, Any] | None) -> dict[str, list[tuple[str, str, str]]]:
    conditions = conditions or {}
    return {
        key: sorted(
            (str(c.get("field")), str(c.get("operator")), str(c.get("value")).lower())
            for c in conditions.get(key) or []
        )
        for key in ("all", "any")
    }


def _webhook_actions(trigger: dict[str, Any]) -> list[tuple[str, Any]]:
    actions = []
    for action in trigger.get("actions") or []:
        value = action.get("value")
        if action.get("field") == "notification_webhook" and isinstance(value, list) and value:
            body = value[1] if len(value) > 1 else ""
            try:
                parsed: Any = json.loads(body)
            except (TypeError, ValueError):
                parsed = body
            actions.append((str(value[0]), parsed))
    return actions


def trigger_drift(existing: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Diferencias entre el trigger de la cuenta y la definición canónica."""
    problems: list[str] = []
    if existing.get("active") is False:
        problems.append("está desactivado")
    if _norm_conditions(existing.get("conditions")) != _norm_conditions(expected["conditions"]):
        problems.append("sus condiciones no coinciden")
    if _webhook_actions(existing) != _webhook_actions(expected):
        problems.append("su acción de webhook (destino o body) no coincide")
    return problems


async def zendesk_live_checks(
    snapshot: TenantSnapshot,
    integration: IntegrationSnapshot,
    *,
    api_base_url: str | None,
    client_factory: ZendeskClientFactory = admin_client,
) -> list[DoctorCheck]:
    assert integration.credentials is not None
    subdomain = str(integration.config.get("subdomain") or "")
    client = await client_factory(integration.credentials, subdomain)
    checks: list[DoctorCheck] = []

    me = await client.get_me()
    me_id = str(me.get("id"))
    checks.append(
        DoctorCheck(
            id="helpdesk.zendesk.auth",
            group="helpdesk",
            title="Acceso a Zendesk",
            status="ok",
            detail=(
                f"{subdomain}.zendesk.com: autenticado como {me.get('name')} "
                f"({me.get('role')})."
            ),
        )
    )
    stored_user = integration.config.get("api_user_id")
    if stored_user and str(stored_user) != me_id:
        checks.append(
            DoctorCheck(
                id="helpdesk.zendesk.api_user",
                group="helpdesk",
                title="Usuario del API de Zendesk",
                status="warn",
                detail=f"`api_user_id` guardado ({stored_user}) ≠ usuario del API ({me_id}).",
                hint=TRIGGERS_SCRIPT.format(slug=snapshot.slug),
            )
        )

    webhooks = (await client._request("GET", "/webhooks")).get("webhooks") or []
    webhook = find_auyan_webhook(webhooks, api_base_url)
    if webhook is None:
        others = [
            str(w.get("endpoint"))
            for w in webhooks
            if str(w.get("endpoint") or "").endswith("/webhooks/zendesk")
        ]
        detail = f"Ningún webhook de Zendesk apunta a {api_base_url or '…'}/webhooks/zendesk."
        if others:
            detail += f" Hay {len(others)} apuntando a otro sitio: {', '.join(others[:2])}."
        checks.append(
            DoctorCheck(
                id="helpdesk.zendesk.webhook",
                group="helpdesk",
                title="Webhook de Zendesk",
                status="fail",
                detail=detail + " Los tickets no llegan a Auyan.",
                hint="Crear o corregir el webhook en Zendesk (Admin Center → Webhooks).",
            )
        )
        return checks
    webhook_id = str(webhook["id"])
    active = webhook.get("status") == "active"
    checks.append(
        DoctorCheck(
            id="helpdesk.zendesk.webhook",
            group="helpdesk",
            title="Webhook de Zendesk",
            status="ok" if active else "fail",
            detail=(
                f"`{webhook.get('name')}` → {webhook.get('endpoint')} "
                f"({webhook.get('status')})."
            ),
            hint=None if active else "Activar el webhook en Zendesk (Admin Center → Webhooks).",
        )
    )

    data = await client._request("GET", "/triggers.json")
    triggers = data.get("triggers") or []
    partial = (
        " (revisión parcial: la cuenta tiene más de una página de triggers)"
        if (data.get("next_page"))
        else ""
    )
    whatsapp = snapshot.find("channel", "zernio") is not None

    inbound = [t for t in find_inbound_triggers(triggers, webhook_id) if t.get("active", True)]
    if not inbound:
        checks.append(
            DoctorCheck(
                id="helpdesk.zendesk.inbound_trigger",
                group="helpdesk",
                title="Trigger de entrada",
                status="fail",
                detail=(
                    "Ningún trigger activo notifica al webhook de Auyan: los mensajes de los "
                    f"clientes no llegan al agente{partial}."
                ),
                hint="Crear el trigger de entrada (ver docs/runbooks y el body del webhook).",
            )
        )
    else:
        names = ", ".join(f"`{t.get('title')}`" for t in inbound)
        leaky = [
            t
            for t in inbound
            if NOT_HANDOFF_CONDITION not in ((t.get("conditions") or {}).get("all") or [])
        ]
        checks.append(
            DoctorCheck(
                id="helpdesk.zendesk.inbound_trigger",
                group="helpdesk",
                title="Trigger de entrada",
                status="warn" if whatsapp and leaky else "ok",
                detail=(
                    f"{names} no excluye los tickets de handoff (tag auyan_handoff); el código "
                    "los filtra igual, pero se pierde la primera capa anti-loop."
                    if whatsapp and leaky
                    else f"Activo: {names}{partial}."
                ),
                hint=TRIGGERS_SCRIPT.format(slug=snapshot.slug) if whatsapp and leaky else None,
            )
        )

    if not whatsapp:
        return checks
    by_title = {t.get("title"): t for t in triggers}
    for check_id, expected in (
        ("helpdesk.zendesk.handoff_reply_trigger", reply_trigger(webhook_id, subdomain)),
        ("helpdesk.zendesk.handoff_solved_trigger", solved_trigger(webhook_id, subdomain)),
    ):
        existing = by_title.get(expected["title"])
        problems = ["no existe"] if existing is None else trigger_drift(existing, expected)
        checks.append(
            DoctorCheck(
                id=check_id,
                group="helpdesk",
                title=f"Trigger `{expected['title']}`",
                status="fail" if problems else "ok",
                detail=(
                    "El trigger " + " y ".join(problems) + ": la vuelta del handoff de WhatsApp "
                    "no funciona." + partial
                    if problems
                    else "Coincide con la definición canónica."
                ),
                hint=TRIGGERS_SCRIPT.format(slug=snapshot.slug) if problems else None,
            )
        )
    return checks


# ─── Zernio (WhatsApp) ────────────────────────────────────────────────────────


def interpret_account_health(raw: dict[str, Any]) -> tuple[str, str]:
    """(estado, detalle) a partir de `GET /accounts/{id}/health`."""
    body = raw.get("account") or raw.get("data") or raw
    if not isinstance(body, dict):
        return "warn", "Respuesta de salud sin el formato esperado."
    status = str(body.get("status") or "unknown")
    connection = body.get("platformConnection") or {}
    connection_status = str(connection.get("status") or "sin sondeo")
    issues = [str(i) for i in body.get("issues") or []]
    parts = [f"estado {status}", f"conexión con Meta: {connection_status}"]
    if connection.get("phoneStatus"):
        parts.append(f"número {connection['phoneStatus']}")
    if issues:
        parts.append("problemas: " + "; ".join(issues[:3]))
    detail = ", ".join(parts) + "."
    if status == "error" or body.get("needsReconnect") or connection_status == "disconnected":
        return "fail", detail
    if status == "healthy" and connection_status in ("connected", "sin sondeo"):
        return "ok", detail
    return "warn", detail


async def zernio_live_checks(
    snapshot: TenantSnapshot,
    integration: IntegrationSnapshot,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[DoctorCheck]:
    assert integration.credentials is not None
    account_id = str(integration.config["account_id"])
    client = ZernioClient(str(integration.credentials["api_key"]), transport=transport)
    status, detail = interpret_account_health(await client.get_account_health(account_id))
    hint = None
    if status == "fail":
        hint = "Reconectar el número: nuevo enlace con " + ONBOARD_SCRIPT.format(
            cmd="prepare", slug=snapshot.slug
        )
    return [
        DoctorCheck(
            id="whatsapp.account_health",
            group="whatsapp",
            title="Salud de la cuenta de WhatsApp",
            status=status,  # type: ignore[arg-type]
            detail=f"Cuenta {account_id}: {detail}",
            hint=hint,
        )
    ]


# ─── Shopify / Chatwoot ───────────────────────────────────────────────────────


async def shopify_live_checks(
    snapshot: TenantSnapshot, integration: IntegrationSnapshot
) -> list[DoctorCheck]:
    creds = integration.credentials or {}
    domain = str(creds.get("domain") or "")
    token = creds.get("access_token") or creds.get("token")
    if creds.get("client_id") and creds.get("client_secret"):
        token, _ = await ensure_shopify_access_token(
            tenant_id=snapshot.tenant_id,
            domain=domain,
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
        )
    if not domain or not token:
        return [
            DoctorCheck(
                id="commerce.shopify.auth",
                group="commerce",
                title="Acceso a Shopify",
                status="fail",
                detail="Faltan `domain` o el token/client credentials en la integración.",
                hint="Reconectar Shopify desde el onboarding.",
            )
        ]
    shop = await ShopifyClient(domain, str(token)).validate()
    return [
        DoctorCheck(
            id="commerce.shopify.auth",
            group="commerce",
            title="Acceso a Shopify",
            status="ok",
            detail=f"Tienda `{shop.get('name')}` ({shop.get('myshopify_domain') or domain}).",
        )
    ]


async def chatwoot_live_checks(
    snapshot: TenantSnapshot, integration: IntegrationSnapshot, *, api_base_url: str | None
) -> list[DoctorCheck]:
    creds = integration.credentials or {}
    client = ChatwootClient(
        base_url=str(integration.config.get("base_url") or ""),
        api_access_token=str(creds.get("api_access_token") or ""),
        account_id=int(integration.config.get("account_id") or 0),
    )
    account = await client.validate()
    checks = [
        DoctorCheck(
            id="helpdesk.chatwoot.auth",
            group="helpdesk",
            title="Acceso a Chatwoot",
            status="ok",
            detail=f"Cuenta `{account.get('name')}`.",
        )
    ]
    if api_base_url:
        target = f"{api_base_url.rstrip('/')}/webhooks/chatwoot"
        found = any(str(w.get("url")) == target for w in await client.list_webhooks())
        checks.append(
            DoctorCheck(
                id="helpdesk.chatwoot.webhook",
                group="helpdesk",
                title="Webhook de Chatwoot",
                status="ok" if found else "fail",
                detail=f"{'Registrado' if found else 'No registrado'}: {target}.",
                hint=None if found else "Reconectar Chatwoot (registra el webhook).",
            )
        )
    return checks


# ─── Orquestación ─────────────────────────────────────────────────────────────


async def run_live_checks(
    snapshot: TenantSnapshot,
    *,
    api_base_url: str | None,
    zendesk_client_factory: ZendeskClientFactory = admin_client,
    zernio_transport: httpx.AsyncBaseTransport | None = None,
) -> list[DoctorCheck]:
    tasks: list[Awaitable[list[DoctorCheck]]] = []
    skipped: list[DoctorCheck] = []

    for integration in snapshot.integrations:
        if integration.credentials is None:
            continue  # ya reportado por los checks de configuración
        key = (integration.kind, integration.provider)
        if not integration.is_active:
            skipped.append(
                DoctorCheck(
                    id=f"{integration.kind}.{integration.provider}.live",
                    group=_GROUP_BY_KIND.get(integration.kind, "platform"),
                    title=f"Acceso a {integration.provider}",
                    status="skip",
                    detail="Inactiva: sin check en vivo.",
                )
            )
        elif key == ("helpdesk", "zendesk") and integration.config.get("subdomain"):
            tasks.append(
                _guarded(
                    snapshot,
                    "helpdesk.zendesk.auth",
                    "helpdesk",
                    "Acceso a Zendesk",
                    lambda i=integration: zendesk_live_checks(
                        snapshot,
                        i,
                        api_base_url=api_base_url,
                        client_factory=zendesk_client_factory,
                    ),
                )
            )
        elif key == ("helpdesk", "chatwoot"):
            tasks.append(
                _guarded(
                    snapshot,
                    "helpdesk.chatwoot.auth",
                    "helpdesk",
                    "Acceso a Chatwoot",
                    lambda i=integration: chatwoot_live_checks(
                        snapshot, i, api_base_url=api_base_url
                    ),
                )
            )
        elif key == ("commerce", "shopify"):
            tasks.append(
                _guarded(
                    snapshot,
                    "commerce.shopify.auth",
                    "commerce",
                    "Acceso a Shopify",
                    lambda i=integration: shopify_live_checks(snapshot, i),
                )
            )
        elif key == ("channel", "zernio"):
            ready = integration.config.get("account_id") and integration.credentials.get("api_key")
            if ready and integration.config.get("sandbox"):
                skipped.append(
                    DoctorCheck(
                        id="whatsapp.account_health",
                        group="whatsapp",
                        title="Salud de la cuenta de WhatsApp",
                        status="skip",
                        detail=(
                            "Sandbox compartido de Zernio: sin check de salud (su endpoint no "
                            "conoce la cuenta). Ver el aviso de configuración del SANDBOX."
                        ),
                    )
                )
            elif ready:
                tasks.append(
                    _guarded(
                        snapshot,
                        "whatsapp.account_health",
                        "whatsapp",
                        "Salud de la cuenta de WhatsApp",
                        lambda i=integration: zernio_live_checks(
                            snapshot, i, transport=zernio_transport
                        ),
                    )
                )
        else:
            skipped.append(
                DoctorCheck(
                    id=f"{integration.kind}.{integration.provider}.live",
                    group=_GROUP_BY_KIND.get(integration.kind, "platform"),
                    title=f"Acceso a {integration.provider}",
                    status="skip",
                    detail=f"Sin check en vivo para {integration.kind}/{integration.provider}.",
                )
            )

    results = await asyncio.gather(*tasks)
    return [check for group in results for check in group] + skipped


async def llm_provider_check(client: Any, model: str) -> DoctorCheck:
    """Una llamada mínima (1 token de salida, el modelo más barato) a Anthropic.

    Detecta saldo agotado, key inválida o sin permisos antes de que lo note un cliente.
    """
    title = "Anthropic: credencial y saldo"
    try:
        await call_claude_with_tools(
            client=client,
            model=model,
            system="ping",
            messages=[{"role": "user", "content": "ping"}],
            tools=[],
            max_tokens=1,
            max_retries=1,
            timeout_seconds=LIVE_TIMEOUT_S,
        )
    except LLMProviderUnavailable as exc:
        return DoctorCheck(
            id="platform.llm_provider",
            group="platform",
            title=title,
            status="fail",
            detail=f"Anthropic rechaza las llamadas ({exc.reason}, HTTP {exc.status_code}).",
            hint="Recargar saldo en console.anthropic.com o rotar ANTHROPIC_API_KEY.",
        )
    except Exception as exc:
        logger.warning("doctor_llm_provider_check_failed", exc_info=True)
        return DoctorCheck(
            id="platform.llm_provider",
            group="platform",
            title=title,
            status="warn",
            detail=f"No se pudo comprobar: {describe_error(exc)}.",
        )
    return DoctorCheck(
        id="platform.llm_provider",
        group="platform",
        title=title,
        status="ok",
        detail=f"Llamada mínima aceptada ({model}).",
    )
