"""Qué catálogo de demo lee cada plataforma (ADR 0016 §7).

La plataforma sale de la última ingesta de la demo (`site_ingestions.platform`). Una plataforma
sin catálogo público (WordPress sin tienda, otra) recibe el catálogo base, que rechaza toda
operación con `DemoCatalogUnavailable`: el agente escala con razón explícita. Sin plataforma
conocida (la ingesta aún no terminó) se mantiene Shopify, que era el único catálogo.
"""

from __future__ import annotations

from apps.api.integrations.demo_catalog import DemoCatalogAdapter, DemoCatalogBase
from apps.api.integrations.demo_catalog_woocommerce import WooCommerceDemoCatalogAdapter
from apps.api.services.site_ingestion.models import Platform

_CATALOGS: dict[Platform, type[DemoCatalogBase]] = {
    Platform.SHOPIFY: DemoCatalogAdapter,
    Platform.WOOCOMMERCE: WooCommerceDemoCatalogAdapter,
}


def demo_catalog_for(domain: str, platform: str | None) -> DemoCatalogBase:
    if not platform:
        return DemoCatalogAdapter(domain)
    return _CATALOGS.get(Platform(platform), DemoCatalogBase)(domain)
