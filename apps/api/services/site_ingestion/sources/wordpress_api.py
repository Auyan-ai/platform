"""`GET /wp-json/wp/v2/pages` devuelve sin credenciales las páginas publicadas con su HTML, y
`wp/v2/posts` las entradas. Es la fuente de WordPress y WooCommerce antes que el HTML renderizado
(mismos filtros de relevancia y ruido que la Storefront API de Shopify).

WooCommerce crea sola la página "Refund and Returns Policy" (slug `refund_returns`): es la
política de devoluciones de la tienda. Las páginas del carrito, el checkout y la cuenta son
bloques de la tienda sin texto útil y se descartan como ruido.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from apps.api.services.site_ingestion.markdown import fragment_to_markdown
from apps.api.services.site_ingestion.models import (
    DiscardReason,
    Platform,
    Priority,
    SourceDoc,
    SourceKind,
    SourceName,
)
from apps.api.services.site_ingestion.relevance import is_cx_topic, is_noise, priority_of
from apps.api.services.site_ingestion.sources.base import SourceContext, SourceSpec

if TYPE_CHECKING:
    from apps.api.services.site_ingestion.wordpress import WordPressIndex

_MAX_PAGE_REQUESTS = 3
_PER_PAGE = 100
_POSTS_PER_PAGE = 20
_FIELDS = "slug,title,content,link,modified"
_REFUND_POLICY_SLUG = re.compile(r"^refund[_-]returns(-\d+)?$")
_SHOP_UTILITY_SLUG = re.compile(
    r"^(cart|carrito|checkout|finalizar-compra|my-account|mi-cuenta|sample-page)(-\d+)?$"
)
_SHOP_UTILITY_BLOCK = re.compile(r"wp-block-woocommerce-(cart|checkout)|class=\"woocommerce\"")


def _title(item: dict[str, Any], slug: str) -> str:
    raw = str((item.get("title") or {}).get("rendered") or "")
    return html.unescape(re.sub(r"<[^>]+>", "", raw)).strip() or slug


def _html(item: dict[str, Any]) -> str:
    return str((item.get("content") or {}).get("rendered") or "")


def _public_url(origin: str, link: str, slug: str) -> str:
    """La URL de la entrada sobre `origin`: el `link` de WordPress trae el `siteurl` de la
    instalación, que puede ser http o ir sin `www`."""
    if not link:
        return f"{origin}/{slug}/"
    parts = urlsplit(link)
    return origin + (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


async def _get_items(
    ctx: SourceContext, index: WordPressIndex, route: str, *, per_page: int, max_requests: int
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    total_pages = 1
    page = 1
    while page <= min(total_pages, max_requests):
        response = await ctx.session.get(
            index.url(route, per_page=per_page, page=page, _fields=_FIELDS)
        )
        if response is None or response.status_code != 200:
            break
        try:
            body = response.json()
        except ValueError:
            ctx.stats.errors += 1
            break
        if not isinstance(body, list):
            ctx.stats.errors += 1
            break
        items.extend(item for item in body if isinstance(item, dict))
        try:
            total_pages = int(response.headers.get("X-WP-TotalPages", "1"))
        except ValueError:
            total_pages = 1
        page += 1
    return items


async def collect(ctx: SourceContext) -> list[SourceDoc]:
    index = ctx.wordpress
    if index is None:
        return []
    if index.name:
        ctx.store_name = index.name
    docs: list[SourceDoc] = []
    if index.description:
        docs.append(
            SourceDoc.build(
                url=ctx.origin,
                kind=SourceKind.SHOP_PROFILE,
                title=index.name or ctx.origin,
                markdown=index.description,
            )
        )

    pages = await _get_items(
        ctx, index, "/wp/v2/pages", per_page=_PER_PAGE, max_requests=_MAX_PAGE_REQUESTS
    )
    for page in pages:
        slug = str(page.get("slug") or "")
        body_html = _html(page)
        if (
            is_noise(slug)
            or _SHOP_UTILITY_SLUG.match(slug)
            or _SHOP_UTILITY_BLOCK.search(body_html)
        ):
            ctx.stats.discard(DiscardReason.NOISE_PAGE)
            continue
        docs.append(
            SourceDoc.build(
                url=_public_url(ctx.origin, str(page.get("link") or ""), slug),
                kind=(
                    SourceKind.SHOP_POLICY
                    if _REFUND_POLICY_SLUG.match(slug)
                    else SourceKind.SHOP_PAGE
                ),
                title=_title(page, slug),
                markdown=await fragment_to_markdown(body_html),
                priority=priority_of(slug),
            )
        )

    posts = await _get_items(ctx, index, "/wp/v2/posts", per_page=_POSTS_PER_PAGE, max_requests=1)
    for post in posts:
        slug = str(post.get("slug") or "")
        title = _title(post, slug)
        if is_noise(slug) or not is_cx_topic(f"{slug} {title}"):
            ctx.stats.discard(DiscardReason.NOT_CX_RELEVANT)
            continue
        docs.append(
            SourceDoc.build(
                url=_public_url(ctx.origin, str(post.get("link") or ""), slug),
                kind=SourceKind.BLOG_ARTICLE,
                title=title,
                markdown=await fragment_to_markdown(_html(post)),
                priority=Priority.NORMAL,
            )
        )
    return docs


SPEC = SourceSpec(
    name=SourceName.WORDPRESS_API,
    platforms=frozenset({Platform.WOOCOMMERCE, Platform.WORDPRESS}),
    collect=collect,
)
