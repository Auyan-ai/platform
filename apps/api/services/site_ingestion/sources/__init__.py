from __future__ import annotations

from apps.api.services.site_ingestion.sources import (
    agent_files,
    html_pages,
    storefront_api,
    storefront_mcp,
    wordpress_api,
)
from apps.api.services.site_ingestion.sources.base import SourceContext, SourceSpec

SOURCES: tuple[SourceSpec, ...] = (
    storefront_api.SPEC,
    storefront_mcp.SPEC,
    wordpress_api.SPEC,
    agent_files.SPEC,
    html_pages.SPEC,
)

__all__ = ["SOURCES", "SourceContext", "SourceSpec"]
