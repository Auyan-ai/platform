from __future__ import annotations

from apps.api.services.site_ingestion.models import (
    DiscardReason,
    Platform,
    SourceDoc,
    SourceKind,
    SourceName,
)
from apps.api.services.site_ingestion.sources.base import SourceContext, SourceSpec

FILE_NAMES: tuple[str, ...] = ("llms-full.txt", "llms.txt", "agents.md")

# Shopify genera estos ficheros en todas las tiendas con un texto por defecto (instrucciones de
# compra por UCP, Universal Commerce Protocol) igual para cualquiera: solo vale el que la tienda
# reescribió.
SHOPIFY_DEFAULT_MARKERS: tuple[str, ...] = (
    "# Agent Instructions —",
    "Universal Commerce Protocol",
)


def is_shopify_default(text: str) -> bool:
    return any(marker in text for marker in SHOPIFY_DEFAULT_MARKERS)


def _is_plain_text(content_type: str, text: str) -> bool:
    if "text/plain" not in content_type and "markdown" not in content_type:
        return False
    return "<html" not in text[:500].lower()


async def collect(ctx: SourceContext) -> list[SourceDoc]:
    docs: list[SourceDoc] = []
    for name in FILE_NAMES:
        response = await ctx.session.get(f"{ctx.origin}/{name}")
        if response is None:
            if ctx.session.abandoned:
                break
            continue
        if response.status_code != 200:
            continue
        text = response.text
        if not _is_plain_text(response.headers.get("content-type", ""), text):
            ctx.stats.discard(DiscardReason.NOT_PLAIN_TEXT)
            continue
        if is_shopify_default(text):
            ctx.stats.discard(DiscardReason.SHOPIFY_DEFAULT_AGENT_FILE)
            continue
        docs.append(
            SourceDoc.build(
                url=str(response.url),
                kind=SourceKind.AGENT_FILE,
                title=name,
                markdown=text,
            )
        )
    return docs


SPEC = SourceSpec(
    name=SourceName.AGENT_FILES,
    platforms=frozenset(Platform),
    collect=collect,
)
