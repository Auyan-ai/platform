"""Onboarding de WhatsApp (Zernio) por tenant — fuente reproducible (ADR 0010).

Una cuenta de Zernio de Auyan, un **profile por tenant** y una API key **limitada a ese
profile** (la única que ve el runtime). Este script usa la key MAESTRA (`ZERNIO_API_KEY`),
que nunca entra en el runtime de la API.

Uso (desde apps/api, con `.env.staging` cargado: DATABASE_URL, INTEGRATIONS_SECRET_KEY,
ZERNIO_API_KEY y AUYAN_API_BASE_URL):

    # 1. Profile + key limitada + webhook firmado; imprime el enlace del signup hospedado
    #    (co-branded) para mandárselo al cliente. Guarda la integración INACTIVA.
    python -m scripts.onboard_whatsapp prepare --tenant marea-studio --brand "Marea Studio" --dry-run
    python -m scripts.onboard_whatsapp prepare --tenant marea-studio --brand "Marea Studio"

    # 2. Cuando el cliente terminó el Embedded Signup: lee la cuenta de WhatsApp del
    #    profile, activa la integración y crea la plantilla de re-enganche (UTILITY, es).
    python -m scripts.onboard_whatsapp finalize --tenant marea-studio

    # Staging: sandbox compartido de Zernio (sin profile; routing por accountId).
    python -m scripts.onboard_whatsapp sandbox --tenant marea-studio --staging \\
        --phone "+34600111222" [--account-id <account.id del primer webhook>]

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
    get_tenant_by_id,
    get_tenant_by_slug,
    list_integrations_for_tenant,
    soft_delete_integration,
    upsert_integration,
)
from apps.api.integrations.zernio import ZERNIO_API_BASE_URL
from apps.api.scripts.configure_staging_integrations import (
    _connect_database,
    _integration_key_from_env,
    _json_bytes,
    _require_env,
    redact_credentials,
)
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
            creds["webhook_secret"] = "***"
        return {"credentials": creds, "config": self.config, "is_active": self.is_active}


def profile_name(slug: str) -> str:
    return f"auyan-{slug}"


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
    account_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"auyan-{slug}"[:50],
        "url": url,
        "secret": secret,
        "events": WEBHOOK_EVENTS,
    }
    if profile_id:
        body["profileIds"] = [profile_id]
    if account_id:
        body["accountIds"] = [account_id]
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


def connect_url_params(profile_id: str, brand: str, redirect_url: str | None) -> dict[str, str]:
    params = {
        "profileId": profile_id,
        "signup": "hosted",
        "brandName": brand,
        "language": "es",
    }
    if redirect_url:
        params["redirect_url"] = redirect_url
    return params


def pick_whatsapp_account(accounts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """La cuenta de WhatsApp del profile (hay una por profile)."""
    for account in accounts:
        if str(account.get("platform") or "").lower() == "whatsapp":
            return account
    return None


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


class ZernioAdmin:
    def __init__(self, api_key: str, base_url: str = ZERNIO_API_BASE_URL) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.request(method, path, **kwargs)
        request_id = response.headers.get("X-Request-Id")
        if response.status_code >= 400:
            raise SystemExit(
                f"Zernio {method} {path} → HTTP {response.status_code} "
                f"(request_id={request_id}): {response.text[:500]}"
            )
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {"data": data}

    async def find_or_create_profile(self, name: str) -> str:
        data = await self.request("GET", "/profiles")
        for profile in data.get("profiles") or data.get("data") or []:
            if isinstance(profile, dict) and profile.get("name") == name:
                return str(profile.get("_id") or profile.get("id"))
        created = await self.request("POST", "/profiles", json={"name": name})
        profile = created.get("profile") or created.get("data") or created
        return str(profile.get("_id") or profile.get("id"))


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


# ─── Subcomandos ──────────────────────────────────────────────────────────────


async def cmd_prepare(args: argparse.Namespace, conn: Any, admin: ZernioAdmin, key: bytes) -> None:
    tenant_id = await _resolve_tenant_id(conn, args.tenant)
    _, state = await _load_state(conn, tenant_id, key)
    api_base = _require_env("AUYAN_API_BASE_URL")

    profile_id = state.config.get("profile_id")
    if not profile_id:
        profile_id = (
            "<profile_id>"
            if args.dry_run
            else await admin.find_or_create_profile(profile_name(args.tenant))
        )
    state.config["profile_id"] = profile_id

    if not state.credentials.get("api_key") or args.rotate_key:
        body = api_key_request(args.tenant, profile_id)
        if args.dry_run:
            print("POST /api-keys", json.dumps(body))
        else:
            created = await admin.request("POST", "/api-keys", json=body)
            api_key = created.get("apiKey") or created.get("api_key") or {}
            state.credentials["api_key"] = api_key["key"]
            state.config["api_key_id"] = api_key.get("id") or api_key.get("_id")

    if not state.config.get("webhook_id"):
        secret = secrets.token_hex(32)
        body = webhook_request(args.tenant, webhook_url(api_base), secret, profile_id=profile_id)
        if args.dry_run:
            print("POST /webhooks/settings", json.dumps({**body, "secret": "***"}))
        else:
            created = await admin.request("POST", "/webhooks/settings", json=body)
            webhook = created.get("webhook") or {}
            state.config["webhook_id"] = webhook.get("_id") or webhook.get("id")
            state.credentials["webhook_secret"] = secret

    params = connect_url_params(profile_id, args.brand, args.redirect_url)
    if args.dry_run:
        print("GET /connect/whatsapp", json.dumps(params))
        print("Plan:", json.dumps(state.redacted(), indent=2))
        return
    connect = await admin.request("GET", "/connect/whatsapp", params=params)
    await _save_state(conn, tenant_id, key, state)
    print("OK: profile, key limitada y webhook listos (integración INACTIVA hasta finalize).")
    print("Enlace del signup hospedado para el cliente:\n ", connect.get("authUrl"))


async def cmd_finalize(args: argparse.Namespace, conn: Any, admin: ZernioAdmin, key: bytes) -> None:
    tenant_id = await _resolve_tenant_id(conn, args.tenant)
    current, state = await _load_state(conn, tenant_id, key)
    if current is None or not state.config.get("profile_id"):
        raise SystemExit("Primero `prepare`: el tenant no tiene integración de Zernio.")
    data = await admin.request("GET", "/accounts", params={"profileId": state.config["profile_id"]})
    accounts = data.get("accounts") or data.get("data") or []
    account = pick_whatsapp_account([a for a in accounts if isinstance(a, dict)])
    if account is None:
        raise SystemExit("El profile aún no tiene cuenta de WhatsApp: ¿terminó el signup?")
    account_id = account_id_of(account)
    if account_id is None:
        raise SystemExit(f"Cuenta de WhatsApp sin id: {account}")
    state.config.update(
        {
            "account_id": account_id,
            "phone_number": account_phone_of(account),
            "reengagement_template": {
                "name": REENGAGEMENT_TEMPLATE_NAME,
                "language": REENGAGEMENT_TEMPLATE_LANGUAGE,
            },
        }
    )
    state.is_active = True
    template = reengagement_template_request(account_id)
    if args.dry_run:
        print("POST /whatsapp/templates", json.dumps(template))
        print("Plan:", json.dumps(state.redacted(), indent=2))
        return
    await _save_state(conn, tenant_id, key, state)
    try:
        await admin.request("POST", "/whatsapp/templates", json=template)
        print("Plantilla de re-enganche creada: pendiente de aprobación de Meta.")
    except SystemExit as exc:
        # Ya existe (re-ejecución) u otro error: se informa, la integración queda activa.
        print(f"AVISO plantilla: {exc}")
    print(f"OK: WhatsApp activo para {args.tenant} (account_id={account_id}).")


async def cmd_sandbox(args: argparse.Namespace, conn: Any, admin: ZernioAdmin, key: bytes) -> None:
    if not args.staging:
        raise SystemExit("El sandbox es solo para staging: añade --staging.")
    tenant_id = await _resolve_tenant_id(conn, args.tenant)
    _, state = await _load_state(conn, tenant_id, key)
    phone = normalize_phone(args.phone)
    if phone is None:
        raise SystemExit(f"Teléfono inválido: {args.phone}")
    if args.dry_run:
        print("POST /whatsapp/sandbox/sessions", json.dumps({"phone": phone}))
    else:
        await admin.request("POST", "/whatsapp/sandbox/sessions", json={"phone": phone})
        print(f"Activación enviada a {phone}: responde al WhatsApp del sandbox para activarla.")
    if not args.account_id:
        print(
            "Falta --account-id: escribe al número del sandbox y copia `account.id` del log del "
            "webhook (GET /v1/webhooks/logs); luego repite con --account-id."
        )
        return
    if not state.credentials.get("api_key"):
        # El sandbox compartido no tiene profile: la key limitada por profile no lo ve.
        # Excepción SOLO de staging: key de alcance completo, caduca en 30 días.
        body = {"name": f"auyan-{args.tenant}-sandbox", "scope": "full", "expiresIn": 30}
        if args.dry_run:
            print("POST /api-keys", json.dumps(body))
        else:
            created = await admin.request("POST", "/api-keys", json=body)
            api_key = created.get("apiKey") or created.get("api_key") or {}
            state.credentials["api_key"] = api_key["key"]
            state.config["api_key_id"] = api_key.get("id") or api_key.get("_id")
    if not state.config.get("webhook_id"):
        secret = secrets.token_hex(32)
        body = webhook_request(
            args.tenant,
            webhook_url(_require_env("AUYAN_API_BASE_URL")),
            secret,
            account_id=args.account_id,
        )
        if args.dry_run:
            print("POST /webhooks/settings", json.dumps({**body, "secret": "***"}))
        else:
            created = await admin.request("POST", "/webhooks/settings", json=body)
            webhook = created.get("webhook") or {}
            state.config["webhook_id"] = webhook.get("_id") or webhook.get("id")
            state.credentials["webhook_secret"] = secret
    state.config.update({"account_id": args.account_id, "sandbox": True})
    state.is_active = True
    if args.dry_run:
        print("Plan:", json.dumps(state.redacted(), indent=2))
        return
    await _save_state(conn, tenant_id, key, state)
    print(f"OK: sandbox registrado para {args.tenant} (account_id={args.account_id}).")


async def cmd_offboard(args: argparse.Namespace, conn: Any, admin: ZernioAdmin, key: bytes) -> None:
    tenant_id = await _resolve_tenant_id(conn, args.tenant)
    current, state = await _load_state(conn, tenant_id, key)
    if current is None:
        raise SystemExit("El tenant no tiene integración de Zernio.")
    webhook_id = state.config.get("webhook_id")
    api_key_id = state.config.get("api_key_id")
    if args.dry_run:
        print(f"DELETE /webhooks/settings?webhookId={webhook_id}")
        print(f"DELETE /api-keys/{api_key_id}")
        print(f"soft delete tenant_integrations {current.id}")
        return
    if webhook_id:
        await admin.request("DELETE", "/webhooks/settings", params={"webhookId": webhook_id})
    if api_key_id:
        await admin.request("DELETE", f"/api-keys/{api_key_id}")
    await soft_delete_integration(conn, tenant_id=tenant_id, integration_id=current.id)
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
        async with conn.transaction():
            await COMMANDS[args.command](args, conn, admin, key)
    finally:
        await conn.close()
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
