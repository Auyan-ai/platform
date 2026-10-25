from __future__ import annotations

import asyncio
import html
import re
from urllib.parse import urljoin, urlsplit

from apps.api.services.kb_source_key import canonical_source_key
from apps.api.services.site_ingestion.markdown import page_to_markdown
from apps.api.services.site_ingestion.models import (
    DiscardReason,
    Platform,
    SourceDoc,
    SourceKind,
    SourceName,
)
from apps.api.services.site_ingestion.relevance import crawl_rank, is_foreign_locale, priority_of
from apps.api.services.site_ingestion.sources.base import SourceContext, SourceSpec

_MAX_SITEMAPS = 10
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_HREF = re.compile(r"""href\s*=\s*["']([^"'#\s]+)""", re.IGNORECASE)
_SKIPPED_SITEMAP = re.compile(r"product|collection|image|video", re.IGNORECASE)
_NON_PAGE = re.compile(r"\.(jpe?g|png|gif|webp|svg|pdf|zip|xml|css|js|ico)$", re.IGNORECASE)


def sitemap_locs(xml: str) -> list[str]:
    return [html.unescape(m) for m in _LOC.findall(xml)]


def _same_site(url: str, host: str) -> bool:
    other = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return other == host.removeprefix("www.")


async def _discover_from_sitemaps(ctx: SourceContext, host: str) -> list[str]:
    queue = await ctx.fetcher.sitemaps(ctx.origin + "/") or [f"{ctx.origin}/sitemap.xml"]
    seen: set[str] = set()
    pages: list[str] = []
    while queue and len(seen) < _MAX_SITEMAPS and not ctx.session.abandoned:
        sitemap = queue.pop(0)
        if sitemap in seen or _SKIPPED_SITEMAP.search(sitemap):
            continue
        if is_foreign_locale(urlsplit(sitemap).path):
            continue
        seen.add(sitemap)
        response = await ctx.session.get(sitemap)
        if response is None or response.status_code != 200:
            continue
        for loc in sitemap_locs(response.text):
            if loc.lower().endswith(".xml") or "sitemap" in urlsplit(loc).path.lower():
                queue.append(loc)
            elif _same_site(loc, host):
                pages.append(loc)
    return pages


async def _discover_from_home(ctx: SourceContext, host: str) -> list[str]:
    response = await ctx.session.get(f"{ctx.origin}/")
    if response is None or response.status_code != 200:
        return []
    links = [urljoin(f"{ctx.origin}/", h) for h in _HREF.findall(response.text)]
    return [f"{ctx.origin}/", *(u for u in links if _same_site(u, host))]


def choose_pages(urls: list[str], budget: int, accepted_keys: frozenset[str]) -> list[str]:
    candidates: dict[str, int] = {}
    for url in urls:
        parts = urlsplit(url)
        if parts.query or _NON_PAGE.search(parts.path):
            continue
        if canonical_source_key(url) in accepted_keys:
            continue
        score = crawl_rank(parts.path)
        if score > 0:
            candidates.setdefault(url, score)
    ranked = sorted(candidates, key=lambda u: candidates[u], reverse=True)
    return ranked[: max(budget, 0)]


async def _read_page(ctx: SourceContext, url: str) -> SourceDoc | None:
    response = await ctx.session.get(url)
    if response is None or response.status_code != 200:
        return None
    if "html" not in response.headers.get("content-type", ""):
        ctx.stats.discard(DiscardReason.NOT_PLAIN_TEXT)
        return None
    markdown, title = await page_to_markdown(response.text, str(response.url))
    if not markdown:
        ctx.stats.discard(DiscardReason.EMPTY_EXTRACTION)
        return None
    return SourceDoc.build(
        url=str(response.url),
        kind=SourceKind.WEB_PAGE,
        title=title,
        markdown=markdown,
        priority=priority_of(urlsplit(str(response.url)).path),
    )


async def collect(ctx: SourceContext) -> list[SourceDoc]:
    host = (urlsplit(ctx.origin).hostname or "").lower()
    urls = await _discover_from_sitemaps(ctx, host)
    if not urls and not ctx.session.abandoned:
        urls = await _discover_from_home(ctx, host)
    pages = choose_pages(urls, ctx.remaining_pages, ctx.accepted_keys)
    results = await asyncio.gather(*(_read_page(ctx, url) for url in pages))
    return [doc for doc in results if doc is not None]


SPEC = SourceSpec(
    name=SourceName.HTML,
    platforms=frozenset(Platform),
    collect=collect,
)
