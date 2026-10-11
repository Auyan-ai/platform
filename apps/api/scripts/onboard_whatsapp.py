"""Onboarding de WhatsApp (Zernio) por tenant — fuente reproducible (ADR 0010).

Una cuenta de Zernio de Auyan, un **profile por tenant** y una API key **limitada a ese
profile** (la única que ve el runtime). Este script usa la key MAESTRA (`ZERNIO_API_KEY`),
que nunca entra en el runtime de la API.

Uso (desde apps/api, con `.env.staging` cargado —DATABASE_URL, INTEGRATIONS_SECRET_KEY y
AUYAN_API_BASE_URL— y `.env.zernio` aparte con ZERNIO_API_KEY; nunca en `.env.staging`, que
`deploy_cloud_run.sh` sube entero a Cloud Run):

    # 1. Profile + key limitada + webhook firmado; imprime el enlace del signup hospedado
    #    (co-branded) para mandárselo al cliente. Guarda la integración INACTIVA.
    python -m scripts.onboard_whatsapp prepare --tenant marea-studio --brand "Marea Studio" --dry-run
    python -m scripts.onboard_whatsapp prepare --tenant marea-studio --brand "Marea Studio"

    # 2. Cuando el cliente terminó el Embedded Signup: lee la cuenta de WhatsApp del
    #    profile, activa la integración y crea la plantilla de re-enganche (UTILITY, es).
    python -m scripts.onboard_whatsapp finalize --tenant marea-studio

    # Staging: sandbox compartido de Zernio (sin profile; routing por accountId).
    python -m scripts.onboard_whatsapp sandbox --tenant marea-studio --staging \\
        --phone "+34600111222" [--account-id <id>]  # por defecto: GET /phone-numbers → sandbox

    # Baja: borra webhook y key en Zernio y hace soft delete de la integración.
    python -m scripts.onboard_whatsapp offboard --tenant marea-studio

La red del entorno cloud bloquea `zernio.com` por defecto: para correrlo desde una
sesión hay que permitir el dominio (ver el runbook `docs/runbooks/whatsapp-onboarding.md`).
"""

# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.api.db.queries import (
    get_primary_integration_for_kind,
    get_tenant_by_id,
    get_tenant_by_slug,
    list_integrations_for_tenant,
    soft_delete_integration,
    upsert_integration,
)
from apps.api.integrations import chatwoot, gorgias, zendesk  # noqa: F401  registran los helpdesks
from apps.api.integrations.zernio import ZERNIO_API_BASE_URL
from apps.api.scripts.configure_staging_integrations import (
    _connect_database,
    _integration_key_from_env,
    _json_bytes,
    _require_env,
    redact_credentials,
)
from apps.api.services.handoff import supports_handoff
from apps.api.services.identity import normalize_phone
from apps.api.services.integrations_crypto import decrypt_credentials, encrypt_credentials

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)

WEBHOOK_EVENTS = [
    "message.received",
    "message.sent",
    "message.failed",
    "message.delivered",
    "conversation.control_changed",
    "account.disconnected",
]
ONBOARDING_MODES = ("business_app", "api")
REENGAGEMENT_TEMPLATE_NAME = "auyan_reengagement"
REENGAGEMENT_TEMPLATE_LANGUAGE = "es"
REENGAGEMENT_TEMPLATE_BODY = (
    "Hola {{1}}, tenemos una respuesta sobre tu consulta. Responde a este mensaje para verla."
)


# ─── Plan puro (testeable sin red) ────────────────────────────────────────────


@dataclass
class ZernioIntegrationState:
    """Lo que guardamos en tenant_integrations(kind='channel', provider='zernio')."""

    credentials: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    is_active: bool = False

    def redacted(self) -> dict[str, Any]:
        creds = redact_credentials(self.credentials)
        if creds.get("webhook_secret"):
            creds["webhook_secret"] = "***"  # noqa: S105 — marcador de redacción
        return {"credentials": creds, "config": self.config, "is_active": self.is_active}


def profile_name(slug: str) -> str:
    return f"auyan-{slug}"


def webhook_name(slug: str) -> str:
    return f"auyan-{slug}"[:50]


def webhook_url(api_base_url: str) -> str:
    return f"{api_base_url.rstrip('/')}/webhooks/zernio"


def api_key_request(slug: str, profile_id: str) -> dict[str, Any]:
    return {
        "name": f"auyan-{slug}-runtime",
        "scope": "profiles",
        "profileIds": [profile_id],
        "permission": "read-write",
    }


def webhook_request(
    slug: str,
    url: str,
    secret: str,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": webhook_name(slug),
        "url": url,
        "secret": secret,
        "events": WEBHOOK_EVENTS,
    }
    if profile_id:
        body["profileIds"] = [profile_id]
    return body


def reengagement_template_request(account_id: str) -> dict[str, Any]:
    return {
        "accountId": account_id,
        "name": REENGAGEMENT_TEMPLATE_NAME,
        "category": "UTILITY",
        "language": REENGAGEMENT_TEMPLATE_LANGUAGE,
        "components": [
            {
                "type": "BODY",
                "text": REENGAGEMENT_TEMPLATE_BODY,
                "example": {"body_text": [["Ana"]]},
            }
        ],
    }


def connect_url_params(
    profile_id: str, brand: str, redirect_url: str | None, onboarding: str = "business_app"
) -> dict[str, str]:
    params = {
        "profileId": profile_id,
        "signup": "hosted",
        "brandName": brand,
        "language": "es",
    }
    if redirect_url:
        params["redirect_url"] = redirect_url
    if onboarding != "business_app":
        params["onboarding"] = onboarding
    return params


def pick_whatsapp_account(accounts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """La cuenta de WhatsApp del profile (hay una por profile)."""
    for account in accounts:
        if str(account.get("platform") or "").lower() == "whatsapp":
            return account
    return None


def sandbox_account_id(phone_numbers: dict[str, Any]) -> str | None:
    """`accountId` del número compartido del sandbox (`GET /v1/phone-numbers` → `sandbox`)."""
    sandbox = phone_numbers.get("sandbox")
    value = sandbox.get("accountId") if isinstance(sandbox, dict) else None
    return str(value) if value else None


def account_id_of(account: dict[str, Any]) -> str | None:
    value = account.get("_id") or account.get("id") or account.get("accountId")
    return str(value) if value else None


def account_phone_of(account: dict[str, Any]) -> str | None:
    metadata = account.get("metadata") if isinstance(account.get("metadata"), dict) else {}
    for raw in (
        account.get("phoneNumber"),
        metadata.get("phoneNumber"),
        metadata.get("displayPhoneNumber"),
        account.get("username"),
    ):
        phone = normalize_phone(str(raw)) if raw else None
        if phone:
            return phone
    return None


# ─── Cliente de administración (key maestra) ──────────────────────────────────

_READ_METHODS = frozenset({"GET"})


@dataclass(frozen=True)
class RemoteKey:
    """Campos en lista blanca de una API key de Zernio. Nunca el valor de la key."""

    id: str
    name: str
    scope: str | None
    profile_ids: tuple[str, ...]


@dataclass(frozen=True)
class RemoteWebhook:
    id: str
    name: str
    url: str | None


def _items(data: dict[str, Any], *keys: str, what: str) -> list[dict[str, Any]]:
    """Lista de objetos bajo la primera clave presente. Falla cerrado si la forma no es la
    esperada: asumir "no hay nada" crearía duplicados."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    raise SystemExit(f"Zernio: forma inesperada en el listado de {what}; no se toca nada.")


def _id_of(item: dict[str, Any]) -> str | None:
    value = item.get("_id") or item.get("id")
    return str(value) if value else None


def parse_remote_keys(data: dict[str, Any]) -> list[RemoteKey]:
    """Solo id, nombre, scope y profileIds: `GET /api-keys` devuelve la key MAESTRA en claro
    en `firstApiKey` y nada de eso se retiene."""
    keys: list[RemoteKey] = []
    for item in _items(data, "apiKeys", "keys", "data", what="API keys"):
        key_id = _id_of(item)
        if key_id is None:
            continue
        raw_profiles = item.get("profileIds")
        profiles = tuple(str(p) for p in raw_profiles) if isinstance(raw_profiles, list) else ()
        scope = item.get("scope")
        keys.append(
            RemoteKey(
                id=key_id,
                name=str(item.get("name") or ""),
                scope=str(scope) if scope else None,
                profile_ids=profiles,
            )
        )
    return keys


def parse_remote_webhooks(data: dict[str, Any]) -> list[RemoteWebhook]:
    hooks: list[RemoteWebhook] = []
    for item in _items(data, "webhooks", "data", what="webhooks"):
        hook_id = _id_of(item)
        if hook_id is None:
            continue
        url = item.get("url")
        hooks.append(
            RemoteWebhook(
                id=hook_id, name=str(item.get("name") or ""), url=str(url) if url else None
            )
        )
    return hooks


class ZernioAdmin:
    def __init__(
        self,
        api_key: str,
        base_url: str = ZERNIO_API_BASE_URL,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.dry_run = False
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _failure(method: str, path: str, response: httpx.Response) -> SystemExit:
        # Los endpoints de keys pueden devolver key material: ni una línea del cuerpo.
        detail = "" if path.startswith("/api-keys") else f": {response.text[:500]}"
        return SystemExit(
            f"Zernio {method} {path} → HTTP {response.status_code} "
            f"(request_id={response.headers.get('X-Request-Id')}){detail}"
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        method = method.upper()
        if self.dry_run and method not in _READ_METHODS:
            raise RuntimeError(f"dry-run: escritura bloqueada ({method} {path})")
        response = await self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise self._failure(method, path, response)
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {"data": data}

    async def delete(self, path: str, **kwargs: Any) -> bool:
        """DELETE tolerante: False si el recurso ya no existe (404)."""
        if self.dry_run:
            raise RuntimeError(f"dry-run: escritura bloqueada (DELETE {path})")
        response = await self._client.request("DELETE", path, **kwargs)
        if response.status_code == 404:
            return False
        if response.status_code >= 400:
            raise self._failure("DELETE", path, response)
        return True

    async def find_profile(self, name: str) -> str | None:
        data = await self.request("GET", "/profiles")
        for profile in _items(data, "profiles", "data", what="profiles"):
            if profile.get("name") == name:
                return _id_of(profile)
        return None

    async def create_profile(self, name: str) -> str:
        created = await self.request("POST", "/profiles", json={"name": name})
        profile = created.get("profile") or created.get("data") or created
        profile_id = _id_of(profile) if isinstance(profile, dict) else None
        if profile_id is None:
            raise SystemExit("Zernio creó el profile pero no devolvió su id.")
        return profile_id

    async def list_api_keys(self) -> list[RemoteKey]:
        return parse_remote_keys(await self.request("GET", "/api-keys"))

    async def list_webhooks(self) -> list[RemoteWebhook]:
        return parse_remote_webhooks(await self.request("GET", "/webhooks/settings"))


# ─── DB ───────────────────────────────────────────────────────────────────────


async def _resolve_tenant_id(conn: Any, tenant: str) -> UUID:
    try:
        found = await get_tenant_by_id(conn, UUID(tenant))
    except ValueError:
        found = await get_tenant_by_slug(conn, tenant)
    if found is None:
        raise SystemExit(f"Tenant no encontrado: {tenant}")
    return found.id


async def _load_state(conn: Any, tenant_id: UUID, key: bytes) -> tuple[Any, ZernioIntegrationState]:
    integrations = await list_integrations_for_tenant(conn, tenant_id=tenant_id, kind="channel")
    current = next((i for i in integrations if i.provider == "zernio"), None)
    if current is None:
        return None, ZernioIntegrationState()
    row = await conn.fetchrow(
        "SELECT credentials_encrypted FROM tenant_integrations WHERE id = $1", current.id
    )
    creds = json.loads(decrypt_credentials(bytes(row["credentials_encrypted"]), key).decode())
    return current, ZernioIntegrationState(
        credentials=creds, config=dict(current.config or {}), is_active=current.is_active
    )


async def _save_state(
    conn: Any, tenant_id: UUID, key: bytes, state: ZernioIntegrationState
) -> None:
    await upsert_integration(
        conn,
        tenant_id=tenant_id,
        kind="channel",
        provider="zernio",
        credentials_encrypted=encrypt_credentials(_json_bytes(state.credentials), key),
        config=state.config,
        is_active=state.is_active,
        is_primary_for_kind=True,
    )


# ─── Informe por pasos ────────────────────────────────────────────────────────

ACTIONS = ("created", "reused", "skipped", "deleted")


@dataclass
class Report:
    """Cada decisión de un paso queda impresa y resumida. Sin secretos: solo ids y nombres."""

    dry_run: bool
    rows: list[tuple[str, str, str]] = field(default_factory=list)

    def record(self, step: str, action: str, detail: str = "") -> None:
        if action not in ACTIONS:
            raise ValueError(f"acción desconocida: {action}")
        self.rows.append((step, action, detail))
        prefix = "[dry-run] " if self.dry_run else ""
        print(f"{prefix}{step}: {action}" + (f" — {detail}" if detail else ""))

    def summary(self) -> None:
        title = "Resumen (dry-run: no se escribió nada)" if self.dry_run else "Resumen"
        print(f"\n{title}")
        for action in ACTIONS:
            steps = [step for step, a, _ in self.rows if a == action]
            if steps:
                print(f"  {action}: {', '.join(steps)}")


@dataclass
class Ctx:
    args: argparse.Namespace
    conn: Any
    admin: ZernioAdmin
    key: bytes
    tenant_id: UUID
    state: ZernioIntegrationState
    report: Report

    @property
    def dry_run(self) -> bool:
        return bool(self.args.dry_run)

    @property
    def slug(self) -> str:
        return str(self.args.tenant)

    async def persist(self) -> None:
        if not self.dry_run:
            await _save_state(self.conn, self.tenant_id, self.key, self.state)


async def _open_ctx(
    args: argparse.Namespace, conn: Any, admin: ZernioAdmin, key: bytes
) -> tuple[Ctx, Any]:
    admin.dry_run = bool(args.dry_run)
    tenant_id = await _resolve_tenant_id(conn, args.tenant)
    current, state = await _load_state(conn, tenant_id, key)
    return Ctx(args, conn, admin, key, tenant_id, state, Report(bool(args.dry_run))), current


async def _persist_or_rollback(ctx: Ctx, step: str, undo: Any, undo_detail: str) -> None:
    """Guarda justo después de crear un recurso remoto. Si el guardado falla, lo borra (y lo
    dice) para no dejarlo huérfano; el error original se relanza."""
    try:
        await ctx.persist()
    except Exception:
        print(f"{step}: el guardado en Supabase falló; revirtiendo {undo_detail} en Zernio.")
        try:
            await undo()
            ctx.report.record(step, "deleted", f"rollback de {undo_detail}")
        except Exception as rollback_error:
            print(
                f"{step}: AVISO el rollback también falló ({type(rollback_error).__name__}); "
                f"borra a mano {undo_detail}."
            )
        raise


# ─── Pasos idempotentes (compartidos por prepare y sandbox) ───────────────────


async def ensure_profile(ctx: Ctx) -> str:
    name = profile_name(ctx.slug)
    stored = ctx.state.config.get("profile_id")
    remote = await ctx.admin.find_profile(name)
    if stored:
        note = "" if remote in (None, stored) else f" (en Zernio '{name}' es {remote})"
        ctx.report.record("profile", "reused", f"{name} id={stored}{note}")
        return str(stored)
    if remote:
        ctx.state.config["profile_id"] = remote
        await ctx.persist()
        ctx.report.record("profile", "reused", f"{name} id={remote} (adoptado por nombre)")
        return remote
    if ctx.dry_run:
        ctx.report.record("profile", "created", f"POST /profiles {json.dumps({'name': name})}")
        return "<profile_id>"
    profile_id = await ctx.admin.create_profile(name)
    ctx.state.config["profile_id"] = profile_id
    await ctx.persist()
    ctx.report.record("profile", "created", f"{name} id={profile_id}")
    return profile_id


async def _delete_key(ctx: Ctx, remote: RemoteKey, why: str) -> None:
    detail = f"{remote.name} id={remote.id} ({why})"
    if ctx.dry_run:
        ctx.report.record("api_key", "deleted", f"DELETE /api-keys/{remote.id} — {detail}")
    elif await ctx.admin.delete(f"/api-keys/{remote.id}"):
        ctx.report.record("api_key", "deleted", detail)
    else:
        ctx.report.record("api_key", "skipped", f"{detail}: ya no existía")


async def ensure_api_key(
    ctx: Ctx, *, name: str, body: dict[str, Any], rotate: bool = False
) -> None:
    """Una key por tenant, localizada por nombre. El valor solo se obtiene al crearla, así que
    una key remota que no tenemos guardada (huérfana) no es recuperable: se borra y se recrea."""
    remote = [k for k in await ctx.admin.list_api_keys() if k.name == name]
    stored = ctx.state.credentials.get("api_key")
    stored_id = ctx.state.config.get("api_key_id")
    reusable: str | None = None
    if stored and not rotate:
        if stored_id and any(k.id == stored_id for k in remote):
            reusable = str(stored_id)
        elif not stored_id and remote:
            reusable = remote[0].id
            ctx.state.config["api_key_id"] = reusable
            await ctx.persist()
        else:
            print("api_key: la key guardada ya no existe en Zernio; se crea otra.")
    if reusable:
        ctx.report.record("api_key", "reused", f"{name} id={reusable}")
        for extra in (k for k in remote if k.id != reusable):
            await _delete_key(ctx, extra, "duplicada")
        return
    if not rotate:
        for orphan in remote:
            await _delete_key(ctx, orphan, "huérfana: no hay valor guardado")
    if ctx.dry_run:
        ctx.report.record("api_key", "created", f"POST /api-keys {json.dumps(body)}")
    else:
        created = await ctx.admin.request("POST", "/api-keys", json=body)
        api_key = created.get("apiKey") or created.get("api_key") or {}
        value, new_id = api_key.get("key"), api_key.get("id") or api_key.get("_id")
        if not value or not new_id:
            raise SystemExit("Zernio creó la key pero la respuesta no trae id y valor.")
        ctx.state.credentials["api_key"] = value
        ctx.state.config["api_key_id"] = str(new_id)
        ctx.report.record("api_key", "created", f"{name} id={new_id}")
        await _persist_or_rollback(
            ctx,
            "api_key",
            lambda: ctx.admin.delete(f"/api-keys/{new_id}"),
            f"la key {name} id={new_id}",
        )
        remote = [k for k in remote if k.id != str(new_id)]
    if rotate:
        for old in remote:
            await _delete_key(ctx, old, "reemplazada por rotación")


async def _delete_webhook(ctx: Ctx, remote: RemoteWebhook, why: str) -> None:
    detail = f"{remote.name} id={remote.id} ({why})"
    if ctx.dry_run:
        ctx.report.record(
            "webhook", "deleted", f"DELETE /webhooks/settings?webhookId={remote.id} — {detail}"
        )
    elif await ctx.admin.delete("/webhooks/settings", params={"webhookId": remote.id}):
        ctx.report.record("webhook", "deleted", detail)
    else:
        ctx.report.record("webhook", "skipped", f"{detail}: ya no existía")


async def ensure_webhook(ctx: Ctx, *, api_base: str, profile_id: str | None) -> None:
    """Un webhook firmado por tenant. Sin el secreto guardado no se puede reutilizar (Zernio
    no lo devuelve), así que un webhook del mismo nombre sin secreto se borra y se recrea."""
    name = webhook_name(ctx.slug)
    remote = [w for w in await ctx.admin.list_webhooks() if w.name == name]
    stored_id = ctx.state.config.get("webhook_id")
    secret_ok = bool(ctx.state.credentials.get("webhook_secret"))
    reusable = (
        str(stored_id)
        if stored_id and secret_ok and any(w.id == stored_id for w in remote)
        else None
    )
    if stored_id and not reusable:
        print("webhook: el guardado no coincide con Zernio o falta su secreto; se recrea.")
    if reusable:
        ctx.report.record("webhook", "reused", f"{name} id={reusable}")
        for extra in (w for w in remote if w.id != reusable):
            await _delete_webhook(ctx, extra, "duplicado")
        return
    for orphan in remote:
        await _delete_webhook(ctx, orphan, "huérfano: no hay secreto guardado")
    secret = secrets.token_hex(32)
    body = webhook_request(ctx.slug, webhook_url(api_base), secret, profile_id=profile_id)
    if ctx.dry_run:
        ctx.report.record(
            "webhook", "created", f"POST /webhooks/settings {json.dumps({**body, 'secret': '***'})}"
        )
        return
    created = await ctx.admin.request("POST", "/webhooks/settings", json=body)
    webhook = created.get("webhook") or {}
    new_id = _id_of(webhook) if isinstance(webhook, dict) else None
    if new_id is None:
        raise SystemExit("Zernio creó el webhook pero no devolvió su id.")
    ctx.state.config["webhook_id"] = new_id
    ctx.state.credentials["webhook_secret"] = secret
    ctx.report.record("webhook", "created", f"{name} id={new_id}")
    await _persist_or_rollback(
        ctx,
        "webhook",
        lambda: ctx.admin.delete("/webhooks/settings", params={"webhookId": new_id}),
        f"el webhook {name} id={new_id}",
    )


# ─── Subcomandos ──────────────────────────────────────────────────────────────


def handoff_target_warning(primary_helpdesk: str | None) -> str | None:
    """Aviso si los escalados de WhatsApp no van a llegar a nadie (s81: Marea tenía Chatwoot
    como helpdesk primario y el handoff fallaba en vivo). None si el handoff es posible."""
    if primary_helpdesk is None:
        return (
            "⚠️  El tenant no tiene helpdesk primario: los escalados de WhatsApp no abrirán "
            "handoff y solo quedarán en el dashboard."
        )
    if not supports_handoff(primary_helpdesk):
        return (
            f"⚠️  El helpdesk primario es {primary_helpdesk} y no admite handoff: los escalados "
            "de WhatsApp fallarán. Marca como primario un helpdesk con handoff (hoy: zendesk)."
        )
    return None


def ensure_not_sandbox(state: ZernioIntegrationState) -> None:
    """`prepare` sobre el sandbox reutilizaría su key de alcance completo (caduca a los 30
    días) y su webhook sin filtro, en vez de la key limitada y el webhook del profile (s81)."""
    if state.config.get("sandbox"):
        raise SystemExit(
            "El tenant tiene registrado el sandbox de Zernio: primero `offboard` (borra su key "
            "y su webhook) y después `prepare` con el número real."
        )


async def _warn_handoff_target(conn: Any, tenant_id: UUID) -> None:
    primary = await get_primary_integration_for_kind(conn, tenant_id=tenant_id, kind="helpdesk")
    warning = handoff_target_warning(primary.provider if primary else None)
    if warning:
        print(warning)


async def cmd_prepare(args: argparse.Namespace, conn: Any, admin: ZernioAdmin, key: bytes) -> None:
    ctx, _ = await _open_ctx(args, conn, admin, key)
    await _warn_handoff_target(conn, ctx.tenant_id)
    ensure_not_sandbox(ctx.state)
    api_base = _require_env("AUYAN_API_BASE_URL")

    profile_id = await ensure_profile(ctx)
    key_body = api_key_request(ctx.slug, profile_id)
    await ensure_api_key(ctx, name=key_body["name"], body=key_body, rotate=bool(args.rotate_key))
    await ensure_webhook(ctx, api_base=api_base, profile_id=profile_id)

    connected = False
    if profile_id != "<profile_id>":
        data = await admin.request("GET", "/accounts", params={"profileId": profile_id})
        connected = (
            pick_whatsapp_account(_items(data, "accounts", "data", what="cuentas")) is not None
        )
    if connected:
        ctx.report.record(
            "signup_link", "skipped", "el profile ya tiene WhatsApp conectado: corre `finalize`"
        )
    else:
        params = connect_url_params(profile_id, args.brand, args.redirect_url, args.onboarding)
        if ctx.dry_run:
            ctx.report.record(
                "signup_link", "created", f"GET /connect/whatsapp {json.dumps(params)}"
            )
        else:
            connect = await admin.request("GET", "/connect/whatsapp", params=params)
            ctx.report.record("signup_link", "created", f"onboarding={args.onboarding}")
            print("Enlace del signup hospedado para el cliente:\n ", connect.get("authUrl"))
    ctx.report.summary()
    if not ctx.dry_run:
        print("Integración INACTIVA hasta `finalize`.")


async def _list_templates(admin: ZernioAdmin, account_id: str) -> list[dict[str, Any]] | None:
    """None si no se pudo listar (se intenta crear igualmente, como antes)."""
    try:
        data = await admin.request("GET", "/whatsapp/templates", params={"accountId": account_id})
        return _items(data, "templates", "data", what="plantillas")
    except SystemExit as exc:
        print(f"template: no se pudo listar plantillas ({exc}); se intenta crear.")
        return None


async def cmd_finalize(args: argparse.Namespace, conn: Any, admin: ZernioAdmin, key: bytes) -> None:
    ctx, current = await _open_ctx(args, conn, admin, key)
    await _warn_handoff_target(conn, ctx.tenant_id)
    state = ctx.state
    if current is None or not state.config.get("profile_id"):
        raise SystemExit("Primero `prepare`: el tenant no tiene integración de Zernio.")
    data = await admin.request("GET", "/accounts", params={"profileId": state.config["profile_id"]})
    account = pick_whatsapp_account(_items(data, "accounts", "data", what="cuentas"))
    if account is None:
        raise SystemExit("El profile aún no tiene cuenta de WhatsApp: ¿terminó el signup?")
    account_id = account_id_of(account)
    if account_id is None:
        raise SystemExit(f"Cuenta de WhatsApp sin id: {account}")
    ctx.report.record("account", "reused", f"WhatsApp account_id={account_id}")

    desired = {
        "account_id": account_id,
        "phone_number": account_phone_of(account),
        "reengagement_template": {
            "name": REENGAGEMENT_TEMPLATE_NAME,
            "language": REENGAGEMENT_TEMPLATE_LANGUAGE,
        },
    }
    if state.is_active and all(state.config.get(k) == v for k, v in desired.items()):
        ctx.report.record("integration", "reused", "ya activa con la misma cuenta")
    else:
        state.config.update(desired)
        state.is_active = True
        await ctx.persist()
        ctx.report.record("integration", "created", "activada con la cuenta de WhatsApp")

    existing = await _list_templates(admin, account_id)
    already = existing is not None and any(
        t.get("name") == REENGAGEMENT_TEMPLATE_NAME
        and str(t.get("language") or REENGAGEMENT_TEMPLATE_LANGUAGE)
        == REENGAGEMENT_TEMPLATE_LANGUAGE
        for t in existing
    )
    template = reengagement_template_request(account_id)
    if already:
        ctx.report.record("template", "reused", REENGAGEMENT_TEMPLATE_NAME)
    elif ctx.dry_run:
        ctx.report.record("template", "created", f"POST /whatsapp/templates {json.dumps(template)}")
    else:
        try:
            await admin.request("POST", "/whatsapp/templates", json=template)
            ctx.report.record(
                "template",
                "created",
                f"{REENGAGEMENT_TEMPLATE_NAME}: pendiente de aprobación de Meta",
            )
        except SystemExit as exc:
            ctx.report.record("template", "skipped", f"AVISO plantilla: {exc}")
    ctx.report.summary()
    if not ctx.dry_run:
        print(f"OK: WhatsApp activo para {args.tenant} (account_id={account_id}).")


async def cmd_sandbox(args: argparse.Namespace, conn: Any, admin: ZernioAdmin, key: bytes) -> None:
    if not args.staging:
        raise SystemExit("El sandbox es solo para staging: añade --staging.")
    ctx, _ = await _open_ctx(args, conn, admin, key)
    await _warn_handoff_target(conn, ctx.tenant_id)
    state = ctx.state
    if state.config.get("profile_id") and not state.config.get("sandbox"):
        raise SystemExit(
            "El tenant tiene un profile real de Zernio: primero `offboard` y después `sandbox`."
        )
    phone = normalize_phone(args.phone)
    if phone is None:
        raise SystemExit(f"Teléfono inválido: {args.phone}")
    api_base = _require_env("AUYAN_API_BASE_URL")

    if state.config.get("sandbox") and state.config.get("sandbox_phone") == phone:
        ctx.report.record("session", "skipped", f"{phone} ya registrada")
    elif ctx.dry_run:
        ctx.report.record(
            "session", "created", f"POST /whatsapp/sandbox/sessions {json.dumps({'phone': phone})}"
        )
    else:
        await admin.request("POST", "/whatsapp/sandbox/sessions", json={"phone": phone})
        ctx.report.record(
            "session", "created", f"activación enviada a {phone}: responde al WhatsApp del sandbox"
        )
    account_id = args.account_id or sandbox_account_id(await admin.request("GET", "/phone-numbers"))
    if not account_id:
        raise SystemExit("Zernio no devuelve el número del sandbox (GET /phone-numbers).")

    # El sandbox compartido no tiene profile: la key limitada por profile no lo ve.
    # Excepción SOLO de staging: key de alcance completo, caduca en 30 días.
    key_name = f"auyan-{ctx.slug}-sandbox"
    await ensure_api_key(
        ctx, name=key_name, body={"name": key_name, "scope": "full", "expiresIn": 30}
    )
    # Sin filtro `accountIds`: el número del sandbox es de Zernio, no del equipo (filtrar por
    # él → 404 account_not_found). El routing a tenant lo hace /webhooks/zernio.
    await ensure_webhook(ctx, api_base=api_base, profile_id=None)

    desired = {"account_id": account_id, "sandbox": True, "sandbox_phone": phone}
    if state.is_active and all(state.config.get(k) == v for k, v in desired.items()):
        ctx.report.record("integration", "reused", "sandbox ya registrado")
    else:
        state.config.update(desired)
        state.is_active = True
        await ctx.persist()
        ctx.report.record("integration", "created", f"sandbox account_id={account_id}")
    ctx.report.summary()


async def cmd_offboard(args: argparse.Namespace, conn: Any, admin: ZernioAdmin, key: bytes) -> None:
    """Borra primero en Zernio y al final hace el soft delete: si algo falla en medio, repetir
    el comando termina el trabajo (lo ya borrado sale como `skipped`)."""
    ctx, current = await _open_ctx(args, conn, admin, key)
    state = ctx.state
    key_names = {f"auyan-{ctx.slug}-runtime", f"auyan-{ctx.slug}-sandbox"}
    hook_name = webhook_name(ctx.slug)

    stored_key_id = state.config.get("api_key_id")
    all_keys = await admin.list_api_keys()
    targets = [k for k in all_keys if k.name in key_names or k.id == stored_key_id]
    for remote_key in targets:
        why = (
            "guardada en la integración"
            if remote_key.id == stored_key_id
            else "huérfana por nombre"
        )
        await _delete_key(ctx, remote_key, why)
    if stored_key_id and not any(k.id == stored_key_id for k in targets):
        ctx.report.record("api_key", "skipped", f"id={stored_key_id}: ya no existía en Zernio")

    stored_hook_id = state.config.get("webhook_id")
    all_hooks = await admin.list_webhooks()
    hook_targets = [h for h in all_hooks if h.name == hook_name or h.id == stored_hook_id]
    for remote_hook in hook_targets:
        why = (
            "guardado en la integración"
            if remote_hook.id == stored_hook_id
            else "huérfano por nombre"
        )
        await _delete_webhook(ctx, remote_hook, why)
    if stored_hook_id and not any(h.id == stored_hook_id for h in hook_targets):
        ctx.report.record("webhook", "skipped", f"id={stored_hook_id}: ya no existía en Zernio")

    if current is None:
        ctx.report.record("integration", "skipped", "el tenant no tiene integración de Zernio")
    elif ctx.dry_run:
        ctx.report.record("integration", "deleted", f"soft delete tenant_integrations {current.id}")
    else:
        await soft_delete_integration(conn, tenant_id=ctx.tenant_id, integration_id=current.id)
        ctx.report.record("integration", "deleted", f"soft delete {current.id}")
    ctx.report.summary()
    if not ctx.dry_run and current is not None:
        print(f"OK: WhatsApp dado de baja para {args.tenant}. El profile se conserva (historial).")


COMMANDS = {
    "prepare": cmd_prepare,
    "finalize": cmd_finalize,
    "sandbox": cmd_sandbox,
    "offboard": cmd_offboard,
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Onboarding de WhatsApp vía Zernio.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        p = sub.add_parser(name)
        p.add_argument("--tenant", required=True, help="Slug o UUID del tenant")
        p.add_argument("--dry-run", action="store_true", help="Muestra lo que haría, sin cambios")
        if name == "prepare":
            p.add_argument("--brand", required=True, help="Nombre de la marca (signup hospedado)")
            p.add_argument("--redirect-url", default=None)
            p.add_argument("--rotate-key", action="store_true", help="Crea una key nueva")
            p.add_argument(
                "--onboarding",
                choices=ONBOARDING_MODES,
                default="business_app",
                help="business_app (coexistence, por defecto) o api (solo Cloud API)",
            )
        if name == "sandbox":
            p.add_argument("--phone", required=True, help="Móvil que activa el sandbox")
            p.add_argument("--account-id", default=None, help="account.id del sandbox")
            p.add_argument("--staging", action="store_true", help="Confirma que es staging")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    key = _integration_key_from_env()
    admin = ZernioAdmin(
        _require_env("ZERNIO_API_KEY"),
        os.environ.get("ZERNIO_API_BASE_URL", ZERNIO_API_BASE_URL),
    )
    conn = await _connect_database(_require_env("DATABASE_URL"))
    try:
        # Sin transacción envolvente: cada paso guarda en cuanto crea un recurso remoto. Con
        # una sola transacción, un fallo posterior revertía el guardado y dejaba la key
        # huérfana en Zernio (s81).
        await COMMANDS[args.command](args, conn, admin, key)
    finally:
        await conn.close()
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
