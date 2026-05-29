"""Crea órdenes reales de prueba en Shopify para 0.11A.

Usa la Shopify test store configurada en `.env` y crea un set mínimo de órdenes
marcadas con tag `auyan-e2e`. El script es idempotente por `note_attributes`:
si una orden con el mismo `auyan_scenario_id` ya existe, la reutiliza.

Uso:
    cd apps/api

    # Ver qué falta sin escribir en Shopify.
    poetry run python -m scripts.seed_shopify_e2e_orders --dry-run

    # Crear sólo las órdenes faltantes.
    poetry run python -m scripts.seed_shopify_e2e_orders
"""

# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.api.scripts.configure_staging_integrations import (
    DEFAULT_E2E_ORDER_TAG,
    SHOPIFY_API_VERSION,
)

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)

SCENARIO_ATTR = "auyan_scenario_id"


@dataclass(frozen=True)
class SeedOrder:
    scenario_id: str
    email: str
    first_name: str
    last_name: str
    title: str
    price: str
    quantity: int
    financial_status: str
    fulfillment_status: Literal["fulfilled"] | None = None
    tracking_number: str | None = None
    tracking_company: str | None = None
    tracking_url: str | None = None


SEED_ORDERS: tuple[SeedOrder, ...] = (
    SeedOrder(
        scenario_id="CE-TRACKING",
        email="laura.gomez+auyan-e2e@example.com",
        first_name="Laura",
        last_name="Gomez",
        title="Collar Luna Plata",
        price="49.90",
        quantity=1,
        financial_status="paid",
        fulfillment_status="fulfilled",
        tracking_number="1Z999AA10123456784",
        tracking_company="UPS",
        tracking_url="https://wwwapps.ups.com/tracking/1Z999AA10123456784",
    ),
    SeedOrder(
        scenario_id="CE-NO-TRACKING",
        email="ana.ruiz+auyan-e2e@example.com",
        first_name="Ana",
        last_name="Ruiz",
        title="Pendientes Aurora",
        price="29.90",
        quantity=1,
        financial_status="paid",
    ),
    SeedOrder(
        scenario_id="RETURNS-IN-WINDOW",
        email="marta.soler+auyan-e2e@example.com",
        first_name="Marta",
        last_name="Soler",
        title="Anillo Nova Ajustable",
        price="39.90",
        quantity=1,
        financial_status="paid",
        fulfillment_status="fulfilled",
        tracking_number="1Z999AA10123456785",
        tracking_company="UPS",
        tracking_url="https://wwwapps.ups.com/tracking/1Z999AA10123456785",
    ),
)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} no está configurado en apps/api/.env")
    return value


def _normalize_domain(domain: str) -> str:
    return domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/")


class ShopifySeedClient:
    def __init__(self, domain: str, token: str) -> None:
        self.domain = _normalize_domain(domain)
        self.token = token

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}/admin/api/{SHOPIFY_API_VERSION}"

    def headers(self) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json",
        }

    async def shop(self) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/shop.json",
                headers=self.headers(),
                timeout=15,
            )
        response.raise_for_status()
        shop = response.json().get("shop")
        if not isinstance(shop, dict):
            raise RuntimeError("Respuesta Shopify inválida: falta shop")
        return shop

    async def primary_location_id(self) -> int | None:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/locations.json",
                headers=self.headers(),
                timeout=15,
            )
        if response.status_code == 403:
            return None
        response.raise_for_status()
        locations = response.json().get("locations", [])
        if not locations:
            return None
        return int(locations[0]["id"])

    async def list_e2e_orders(self, tag: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/orders.json",
                headers=self.headers(),
                params={
                    "status": "any",
                    "limit": 250,
                    "fields": (
                        "id,name,email,tags,note_attributes,fulfillment_status,"
                        "financial_status,fulfillments,created_at"
                    ),
                },
                timeout=20,
            )
        response.raise_for_status()
        orders = response.json().get("orders", [])
        if not isinstance(orders, list):
            raise RuntimeError("Respuesta Shopify inválida: orders no es lista")
        return [order for order in orders if _has_tag(order, tag)]

    async def create_order(
        self,
        seed: SeedOrder,
        *,
        tag: str,
        location_id: int | None,
    ) -> dict[str, Any]:
        order_payload = _build_order_payload(seed, tag=tag, location_id=location_id)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/orders.json",
                headers=self.headers(),
                json={
                    "order": order_payload,
                    "send_receipt": False,
                    "send_fulfillment_receipt": False,
                },
                timeout=20,
            )
        response.raise_for_status()
        order = response.json().get("order")
        if not isinstance(order, dict):
            raise RuntimeError("Respuesta Shopify inválida: falta order")
        return order

    async def update_tracking(self, fulfillment_id: int, seed: SeedOrder) -> dict[str, Any]:
        if not seed.tracking_number:
            raise ValueError("tracking_number required")
        tracking_info: dict[str, str] = {"number": seed.tracking_number}
        if seed.tracking_company:
            tracking_info["company"] = seed.tracking_company
        if seed.tracking_url:
            tracking_info["url"] = seed.tracking_url

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/fulfillments/{fulfillment_id}/update_tracking.json",
                headers=self.headers(),
                json={"fulfillment": {"notify_customer": False, "tracking_info": tracking_info}},
                timeout=20,
            )
        response.raise_for_status()
        fulfillment = response.json().get("fulfillment")
        if not isinstance(fulfillment, dict):
            raise RuntimeError("Respuesta Shopify inválida: falta fulfillment")
        return fulfillment


def _has_tag(order: dict[str, Any], tag: str) -> bool:
    tags = {part.strip() for part in str(order.get("tags") or "").split(",") if part.strip()}
    return tag in tags


def _scenario_id(order: dict[str, Any]) -> str | None:
    attrs = order.get("note_attributes") or []
    for attr in attrs:
        if attr.get("name") == SCENARIO_ATTR:
            value = attr.get("value")
            return str(value) if value else None
    return None


def _build_order_payload(
    seed: SeedOrder,
    *,
    tag: str,
    location_id: int | None,
) -> dict[str, Any]:
    order: dict[str, Any] = {
        "email": seed.email,
        "financial_status": seed.financial_status,
        "tags": f"{tag}, {seed.scenario_id}",
        "note": "Auyan E2E staging order. Safe to delete after verification.",
        "note_attributes": [
            {"name": SCENARIO_ATTR, "value": seed.scenario_id},
            {"name": "auyan_e2e", "value": "true"},
        ],
        "customer": {
            "first_name": seed.first_name,
            "last_name": seed.last_name,
            "email": seed.email,
        },
        "billing_address": _address(seed),
        "shipping_address": _address(seed),
        "line_items": [
            {
                "title": seed.title,
                "price": seed.price,
                "quantity": seed.quantity,
                "requires_shipping": True,
            }
        ],
    }
    if seed.fulfillment_status:
        order["fulfillment_status"] = seed.fulfillment_status
    if seed.fulfillment_status == "fulfilled" and location_id is not None:
        order["fulfillments"] = [{"location_id": location_id}]
    return order


def _address(seed: SeedOrder) -> dict[str, str]:
    return {
        "first_name": seed.first_name,
        "last_name": seed.last_name,
        "address1": "Calle de Serrano 1",
        "city": "Madrid",
        "province": "Madrid",
        "country": "Spain",
        "zip": "28001",
        "phone": "+34600123456",
    }


async def run(*, dry_run: bool, tag: str) -> None:
    client = ShopifySeedClient(
        _require_env("SHOPIFY_TEST_DOMAIN"),
        _require_env("SHOPIFY_TEST_ACCESS_TOKEN"),
    )
    shop = await client.shop()
    location_id = await client.primary_location_id()
    existing_orders = await client.list_e2e_orders(tag)
    existing_by_scenario = {
        scenario_id: order
        for order in existing_orders
        if (scenario_id := _scenario_id(order)) is not None
    }

    print(f"Shopify: {shop.get('name')} ({client.domain})")
    print(f"Location ID para fulfillments: {location_id or 'no disponible'}")
    if location_id is None:
        print(
            "WARN: no se pudo leer locations. Las órdenes con tracking requieren "
            "permiso de locations o un token con scope suficiente."
        )
    print(f"Órdenes {tag} existentes: {len(existing_orders)}")

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    repaired: list[dict[str, Any]] = []

    for seed in SEED_ORDERS:
        existing = existing_by_scenario.get(seed.scenario_id)
        if existing:
            if _needs_tracking_repair(existing, seed):
                fulfillments = existing.get("fulfillments") or []
                if not fulfillments:
                    print(f"BLOCKED {seed.scenario_id}: existe {existing.get('name')} sin fulfillment")
                    continue
                print(f"{'DRY' if dry_run else 'REPAIR'} {seed.scenario_id}: tracking en {existing.get('name')}")
                if not dry_run:
                    fulfillment_id = int(fulfillments[0]["id"])
                    await client.update_tracking(fulfillment_id, seed)
                    repaired_order = await _fetch_order(client, int(existing["id"]))
                    repaired.append(repaired_order)
                continue
            skipped.append(existing)
            print(f"SKIP {seed.scenario_id}: ya existe {existing.get('name')}")
            continue

        if seed.fulfillment_status == "fulfilled" and location_id is None:
            print(f"BLOCKED {seed.scenario_id}: falta location_id para crear fulfillment")
            continue

        print(f"{'DRY' if dry_run else 'CREATE'} {seed.scenario_id}: {seed.email}")
        if dry_run:
            continue

        order = await client.create_order(seed, tag=tag, location_id=location_id)
        fulfillments = order.get("fulfillments") or []
        if seed.tracking_number and fulfillments:
            fulfillment_id = int(fulfillments[0]["id"])
            await client.update_tracking(fulfillment_id, seed)
            order = await _fetch_order(client, int(order["id"]))
        created.append(order)
        print(f"  OK {order.get('name')} id={order.get('id')}")

    print(
        json.dumps(
            {
                "created": [_summary(order) for order in created],
                "repaired": [_summary(order) for order in repaired],
                "skipped": [_summary(order) for order in skipped],
                "dry_run": dry_run,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


async def _fetch_order(client: ShopifySeedClient, order_id: int) -> dict[str, Any]:
    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(
            f"{client.base_url}/orders/{order_id}.json",
            headers=client.headers(),
            params={"status": "any"},
            timeout=15,
        )
    response.raise_for_status()
    order = response.json().get("order")
    if not isinstance(order, dict):
        raise RuntimeError("Respuesta Shopify inválida: falta order")
    return order


def _summary(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "name": order.get("name"),
        "email": order.get("email"),
        "scenario_id": _scenario_id(order),
        "financial_status": order.get("financial_status"),
        "fulfillment_status": order.get("fulfillment_status"),
        "tracking_numbers": [
            fulfillment.get("tracking_number")
            for fulfillment in (order.get("fulfillments") or [])
            if fulfillment.get("tracking_number")
        ],
    }


def _needs_tracking_repair(order: dict[str, Any], seed: SeedOrder) -> bool:
    if not seed.tracking_number:
        return False
    return seed.tracking_number not in _tracking_numbers(order)


def _tracking_numbers(order: dict[str, Any]) -> list[str]:
    return [
        str(fulfillment.get("tracking_number"))
        for fulfillment in (order.get("fulfillments") or [])
        if fulfillment.get("tracking_number")
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Shopify auyan-e2e orders.")
    parser.add_argument("--dry-run", action="store_true", help="No escribe en Shopify")
    parser.add_argument("--tag", default=DEFAULT_E2E_ORDER_TAG, help="Tag E2E")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    asyncio.run(run(dry_run=args.dry_run, tag=args.tag))


if __name__ == "__main__":
    main()
