"""Configura y verifica integraciones reales para Agent Verification Staging.

Este script es para 0.11A: conectar Lunaria staging a Shopify test store y
Chatwoot sandbox usando `tenant_integrations` con credentials cifradas.

Uso:
    cd apps/api

    # Verifica APIs externas y muestra lo que guardaría.
    poetry run python -m scripts.configure_staging_integrations --tenant lunaria --dry-run

    # Configura Shopify + Chatwoot en tenant_integrations.
    poetry run python -m scripts.configure_staging_integrations --tenant lunaria

    # Sólo Shopify, permitiendo activar antes de crear órdenes auyan-e2e.
    poetry run python -m scripts.configure_staging_integrations \\
        --tenant lunaria --only shopify --allow-missing-e2e-orders

Variables esperadas en .env:
    DATABASE_URL
    INTEGRATIONS_SECRET_KEY
    SHOPIFY_TEST_DOMAIN
    SHOPIFY_TEST_ACCESS_TOKEN
    CHATWOOT_BASE_URL
    CHATWOOT_ACCOUNT_ID
    CHATWOOT_API_ACCESS_TOKEN

Opcionales:
    CHATWOOT_WEBHOOK_SECRET_TOKEN
    CHATWOOT_ESCALATION_TEAM_ID
"""

# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

import asyncpg
import httpx
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.api.db.queries import get_tenant_by_id, get_tenant_by_slug, upsert_integration
from apps.api.services.integrations_crypto import encrypt_credentials

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)

SHOPIFY_API_VERSION = "2024-10"
DEFAULT_E2E_ORDER_TAG = "auyan-e2e"
Provider = Literal["shopify", "chatwoot"]


@dataclass(frozen=True)
class IntegrationPlan:
    """Plan redacted para impresión y tests."""

    provider: Provider
    kind: Literal["commerce", "helpdesk"]
    credentials: dict[str, Any]
    config: dict[str, Any]
    is_primary_for_kind: bool = True

    def redacted(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "kind": self.kind,
            "credentials": redact_credentials(self.credentials),
            "config": self.config,
            "is_primary_for_kind": self.is_primary_for_kind,
        }


def redact_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
    """Redacta valores sensibles preservando qué keys existen."""
    redacted: dict[str, Any] = {}
    for key, value in credentials.items():
        if value in (None, ""):
            redacted[key] = value
        elif key in {"token", "api_access_token", "webhook_secret_token"}:
            text = str(value)
            suffix = text[-4:] if len(text) >= 4 else "set"
            redacted[key] = f"***{suffix}"
        else:
            redacted[key] = value
    return redacted


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} no está configurado en .env")
    return value


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _integration_key_from_env() -> bytes:
    raw = _require_env("INTEGRATIONS_SECRET_KEY")
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise SystemExit("INTEGRATIONS_SECRET_KEY debe ser hex válido") from exc
    if len(key) != 32:
        raise SystemExit(
            f"INTEGRATIONS_SECRET_KEY debe tener 32 bytes/64 hex chars; tiene {len(key)} bytes"
        )
    return key


def _json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _normalize_shopify_domain(domain: str) -> str:
    normalized = domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    if "/" in normalized:
        raise SystemExit("SHOPIFY_TEST_DOMAIN debe ser sólo el host, ej. tienda.myshopify.com")
    return normalized


async def _validate_shopify(domain: str, token: str) -> dict[str, Any]:
    url = f"https://{domain}/admin/api/{SHOPIFY_API_VERSION}/shop.json"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            timeout=15,
        )
    response.raise_for_status()
    shop = response.json().get("shop")
    if not isinstance(shop, dict):
        raise RuntimeError("Respuesta Shopify inválida: falta shop")
    return shop


async def _fetch_shopify_e2e_orders(
    domain: str,
    token: str,
    *,
    tag: str,
    limit: int = 250,
) -> list[dict[str, Any]]:
    """Trae órdenes recientes y filtra localmente por tag.

    La REST Orders API no ofrece un filtro por tag suficientemente portable para
    este smoke test, así que pedimos campos mínimos y filtramos en cliente.
    """
    url = f"https://{domain}/admin/api/{SHOPIFY_API_VERSION}/orders.json"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            params={
                "status": "any",
                "limit": limit,
                "fields": "id,name,email,tags,fulfillment_status,total_price,currency,created_at",
            },
            timeout=20,
        )
    response.raise_for_status()
    orders = response.json().get("orders", [])
    if not isinstance(orders, list):
        raise RuntimeError("Respuesta Shopify inválida: orders no es lista")

    result: list[dict[str, Any]] = []
    for order in orders:
        raw_tags = str(order.get("tags") or "")
        tags = {part.strip() for part in raw_tags.split(",") if part.strip()}
        if tag in tags:
            result.append(order)
    return result


async def build_shopify_plan(
    *,
    e2e_order_tag: str,
    allow_missing_e2e_orders: bool,
) -> IntegrationPlan:
    domain = _normalize_shopify_domain(_require_env("SHOPIFY_TEST_DOMAIN"))
    token = _require_env("SHOPIFY_TEST_ACCESS_TOKEN")

    shop = await _validate_shopify(domain, token)
    e2e_orders = await _fetch_shopify_e2e_orders(domain, token, tag=e2e_order_tag)
    if not e2e_orders and not allow_missing_e2e_orders:
        raise SystemExit(
            "No encontré órdenes Shopify con tag "
            f"'{e2e_order_tag}'. Crea órdenes reales de test o usa "
            "--allow-missing-e2e-orders sólo para activar antes de verificar."
        )

    return IntegrationPlan(
        provider="shopify",
        kind="commerce",
        credentials={"domain": domain, "token": token},
        config={
            "api_version": SHOPIFY_API_VERSION,
            "shop_name": shop.get("name"),
            "shop_email": shop.get("email"),
            "e2e_order_tag": e2e_order_tag,
            "e2e_order_count": len(e2e_orders),
            "e2e_order_names": [str(order.get("name")) for order in e2e_orders[:10]],
            "verified_at": _now_iso(),
        },
    )


async def _validate_chatwoot(base_url: str, account_id: str, token: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"api_access_token": token, "Content-Type": "application/json"},
            timeout=15,
        )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


async def build_chatwoot_plan() -> IntegrationPlan:
    base_url = _require_env("CHATWOOT_BASE_URL").rstrip("/")
    account_id = _require_env("CHATWOOT_ACCOUNT_ID")
    token = _require_env("CHATWOOT_API_ACCESS_TOKEN")
    webhook_secret = _optional_env("CHATWOOT_WEBHOOK_SECRET_TOKEN")
    escalation_team_id = _optional_env("CHATWOOT_ESCALATION_TEAM_ID")

    account = await _validate_chatwoot(base_url, account_id, token)
    credentials = {"api_access_token": token}
    if webhook_secret:
        credentials["webhook_secret_token"] = webhook_secret

    config: dict[str, Any] = {
        "base_url": base_url,
        "account_id": account_id,
        "account_name": account.get("name"),
        "verified_at": _now_iso(),
    }
    if escalation_team_id:
        config["escalation_team_id"] = escalation_team_id

    return IntegrationPlan(
        provider="chatwoot",
        kind="helpdesk",
        credentials=credentials,
        config=config,
    )


async def _resolve_tenant_id(conn: asyncpg.Connection, tenant: str) -> UUID:
    try:
        tenant_id = UUID(tenant)
    except ValueError:
        row = await get_tenant_by_slug(conn, tenant)
    else:
        row = await get_tenant_by_id(conn, tenant_id)

    if row is None:
        raise SystemExit(f"Tenant no encontrado: {tenant}")
    return cast(UUID, row.id)


async def _apply_plan(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    key: bytes,
    plan: IntegrationPlan,
) -> None:
    encrypted = encrypt_credentials(_json_bytes(plan.credentials), key)
    await upsert_integration(
        conn,
        tenant_id=tenant_id,
        kind=plan.kind,
        provider=plan.provider,
        credentials_encrypted=encrypted,
        config=plan.config,
        is_active=True,
        is_primary_for_kind=plan.is_primary_for_kind,
    )


async def _connect_database(database_url: str) -> asyncpg.Connection:
    conn = await asyncpg.connect(database_url)
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    return conn


async def run(
    *,
    tenant: str,
    only: Provider | None,
    dry_run: bool,
    e2e_order_tag: str,
    allow_missing_e2e_orders: bool,
) -> None:
    database_url = _require_env("DATABASE_URL")
    key = _integration_key_from_env()

    providers: list[Provider] = [only] if only else ["shopify", "chatwoot"]
    plans: list[IntegrationPlan] = []
    if "shopify" in providers:
        plans.append(
            await build_shopify_plan(
                e2e_order_tag=e2e_order_tag,
                allow_missing_e2e_orders=allow_missing_e2e_orders,
            )
        )
    if "chatwoot" in providers:
        plans.append(await build_chatwoot_plan())

    conn = await _connect_database(database_url)
    try:
        tenant_id = await _resolve_tenant_id(conn, tenant)
        print(f"tenant_id: {tenant_id}")
        print(json.dumps([plan.redacted() for plan in plans], ensure_ascii=False, indent=2))

        if dry_run:
            print("\n[dry-run] No se hicieron cambios en tenant_integrations.")
            return

        for plan in plans:
            await _apply_plan(conn, tenant_id=tenant_id, key=key, plan=plan)
            print(f"OK: integración {plan.kind}/{plan.provider} configurada.")
    finally:
        await conn.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configura Shopify/Chatwoot reales para Agent Verification Staging."
    )
    parser.add_argument("--tenant", default="lunaria", help="Slug o UUID del tenant")
    parser.add_argument(
        "--only",
        choices=["shopify", "chatwoot"],
        default=None,
        help="Configura sólo un proveedor. Default: ambos.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Valida y muestra sin guardar")
    parser.add_argument(
        "--e2e-order-tag",
        default=DEFAULT_E2E_ORDER_TAG,
        help="Tag requerido para órdenes reales de verificación Shopify.",
    )
    parser.add_argument(
        "--allow-missing-e2e-orders",
        action="store_true",
        help="Permite guardar Shopify aunque aún no existan órdenes con tag auyan-e2e.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    asyncio.run(
        run(
            tenant=args.tenant,
            only=args.only,
            dry_run=args.dry_run,
            e2e_order_tag=args.e2e_order_tag,
            allow_missing_e2e_orders=args.allow_missing_e2e_orders,
        )
    )


if __name__ == "__main__":
    main()
