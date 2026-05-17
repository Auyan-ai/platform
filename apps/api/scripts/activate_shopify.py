"""Activa las skills Shopify para un tenant en Supabase.

Pasos:
  1. Lee SHOPIFY_TEST_DOMAIN y SHOPIFY_TEST_ACCESS_TOKEN del .env.
  2. Valida las creds con GET /admin/api/.../shop.json.
  3. Hace MERGE en tenant_configurations.extra del tenant indicado:
       allowed_skills, max_tool_iterations, shopify_domain, shopify_token.

Uso:
    cd apps/api
    poetry run python -m scripts.activate_shopify
    poetry run python -m scripts.activate_shopify --tenant lunaria --dry-run
    poetry run python -m scripts.activate_shopify --revert   # borra las creds
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import asyncpg
import httpx
from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)

ALLOWED_SKILLS = [
    "shopify.get_order_by_email",
    "shopify.get_order_status",
    "shopify.get_product_info",
    "shopify.get_customer_history",
    "shopify.get_shop_policies",
]
MAX_TOOL_ITERATIONS = 5
SHOPIFY_API_VERSION = "2024-10"


async def _validate_shopify_creds(domain: str, token: str) -> dict:
    url = f"https://{domain}/admin/api/{SHOPIFY_API_VERSION}/shop.json"
    async with httpx.AsyncClient() as client:
        r = await client.get(
            url,
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["shop"]


async def _get_tenant_id(conn: asyncpg.Connection, slug: str) -> str:
    row = await conn.fetchrow(
        "SELECT id FROM tenants WHERE slug = $1 AND deleted_at IS NULL", slug
    )
    if row is None:
        raise SystemExit(f"Tenant '{slug}' no encontrado.")
    return str(row["id"])


async def _get_current_extra(conn: asyncpg.Connection, tenant_id: str) -> dict:
    row = await conn.fetchrow(
        "SELECT extra FROM tenant_configurations WHERE tenant_id = $1::uuid", tenant_id
    )
    if row is None:
        raise SystemExit(f"tenant_configurations no existe para tenant_id={tenant_id}")
    raw = row["extra"]
    if raw is None:
        return {}
    # asyncpg puede devolver jsonb como str o como dict según el codec configurado.
    return json.loads(raw) if isinstance(raw, str) else raw


async def run(tenant_slug: str, dry_run: bool, revert: bool) -> None:
    domain = os.environ.get("SHOPIFY_TEST_DOMAIN", "").strip()
    token = os.environ.get("SHOPIFY_TEST_ACCESS_TOKEN", "").strip()
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if not database_url:
        raise SystemExit("DATABASE_URL no está en .env")

    if not revert:
        if not domain or not token:
            raise SystemExit(
                "Faltan SHOPIFY_TEST_DOMAIN o SHOPIFY_TEST_ACCESS_TOKEN en .env"
            )
        print(f"Validando credenciales Shopify para '{domain}'...")
        shop = await _validate_shopify_creds(domain, token)
        print(f"  OK — tienda: {shop.get('name')} ({shop.get('email')})")

    conn: asyncpg.Connection = await asyncpg.connect(database_url)
    try:
        tenant_id = await _get_tenant_id(conn, tenant_slug)
        print(f"  tenant_id: {tenant_id}")
        current_extra = await _get_current_extra(conn, tenant_id)
        print(f"  extra actual: {json.dumps(current_extra, ensure_ascii=False)}")

        if revert:
            new_extra = {
                k: v
                for k, v in current_extra.items()
                if k not in {"allowed_skills", "max_tool_iterations", "shopify_domain", "shopify_token"}
            }
        else:
            new_extra = {
                **current_extra,
                "allowed_skills": ALLOWED_SKILLS,
                "max_tool_iterations": MAX_TOOL_ITERATIONS,
                "shopify_domain": domain,
                "shopify_token": token,
            }

        print(f"\n  extra nuevo: {json.dumps(new_extra, ensure_ascii=False)}")

        if dry_run:
            print("\n[dry-run] No se hicieron cambios en la DB.")
            return

        await conn.execute(
            "UPDATE tenant_configurations SET extra = $1::jsonb WHERE tenant_id = $2::uuid",
            json.dumps(new_extra),
            tenant_id,
        )
        action = "revertido" if revert else "activado"
        print(f"\n✓ Shopify {action} para tenant '{tenant_slug}'.")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Activa/desactiva Shopify para un tenant.")
    parser.add_argument("--tenant", default="lunaria", help="Slug del tenant (default: lunaria)")
    parser.add_argument("--dry-run", action="store_true", help="Muestra el cambio sin aplicarlo")
    parser.add_argument("--revert", action="store_true", help="Elimina creds y skills del tenant")
    args = parser.parse_args()
    asyncio.run(run(args.tenant, args.dry_run, args.revert))


if __name__ == "__main__":
    main()
