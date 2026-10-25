"""Consulta en vivo el catálogo público de una tienda con el DemoCatalogAdapter.

Uso (desde la raíz del repo):
    python -m apps.api.scripts.demo_catalog_probe --store thinkingmu.com --query "Tere"

Imprime título, precio, tallas disponibles y agotadas, y las etiquetas de material de cada
producto. Es la evidencia en vivo del PR 8: precio y stock por talla vienen de la
Storefront API pública, identificándonos como AuyanBot.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from apps.api.integrations.demo_catalog import BOT_USER_AGENT, DemoCatalogAdapter
from apps.api.skills.shopify._models import map_product_summary

_MATERIAL_HINTS = ("poli", "algod", "lino", "lana", "recicl", "orgán", "organ", "cotton", "wool")


async def probe(store: str, query: str, limit: int) -> int:
    adapter = DemoCatalogAdapter(store)
    currency = await adapter.get_shop_currency(None)
    raw_products = await adapter.search_products(None, query, limit=limit)
    print(f"tienda={adapter.domain} consulta={query!r} moneda={currency} ua={BOT_USER_AGENT}")
    if not raw_products:
        print("sin resultados")
        return 1
    for raw in raw_products:
        product = map_product_summary(raw, currency)
        price = product.variants[0].price if product.variants else None
        available = [v.title for v in product.variants if v.available]
        sold_out = [v.title for v in product.variants if not v.available]
        materials = [t for t in product.tags if any(h in t.lower() for h in _MATERIAL_HINTS)]
        print(f"- {product.title}")
        print(f"  precio: {price.amount} {price.currency}" if price else "  precio: n/d")
        print(f"  tallas disponibles: {', '.join(available) or 'ninguna'}")
        print(f"  tallas agotadas: {', '.join(sold_out) or 'ninguna'}")
        print(f"  material (etiquetas): {', '.join(materials) or 'n/d'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, help="dominio público, p. ej. thinkingmu.com")
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    return asyncio.run(probe(args.store, args.query, args.limit))


if __name__ == "__main__":
    sys.exit(main())
