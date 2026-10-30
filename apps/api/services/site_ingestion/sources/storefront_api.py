"""`POST https://<tienda>/api/<versión>/graphql.json` responde sin token en una tienda pública y
devuelve las políticas completas, las páginas con su texto y los artículos del blog. Las páginas
montadas con secciones del tema salen con el cuerpo vacío y se descartan por cortas.

La clave de una política es su URL pública en la tienda (`<dominio>/policies/<handle>`), no la
de checkout que devuelve la API (`checkout.shopify.com/<id>/policies/<n>.html`): esa lleva ids
internos y no es la que ve el comprador.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.api.integrations.demo_catalog import STOREFRONT_API_VERSION
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
    from apps.api.services.site_ingestion.fetcher import FetchSession

logger = logging.getLogger(__name__)

_MAX_PAGE_REQUESTS = 3
_POLICY_FIELDS = ("refundPolicy", "shippingPolicy", "termsOfService", "subscriptionPolicy")

PROBE_QUERY = "query AuyanShopProbe { shop { name primaryDomain { url } } }"
CONTENT_QUERY = """
query AuyanStoreContent {
  shop {
    name description
    refundPolicy { title handle body }
    shippingPolicy { title handle body }
    termsOfService { title handle body }
    subscriptionPolicy { title handle body }
  }
  pages(first: 100) {
    pageInfo { hasNextPage endCursor }
    nodes { title handle body onlineStoreUrl }
  }
  blogs(first: 5) {
    nodes {
      handle
      articles(first: 20, sortKey: PUBLISHED_AT, reverse: true) {
        nodes { title handle contentHtml onlineStoreUrl }
      }
    }
  }
}
"""
PAGES_QUERY = """
query AuyanStorePages($after: String!) {
  pages(first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { title handle body onlineStoreUrl }
  }
}
"""


def graphql_url(origin: str) -> str:
    return f"{origin}/api/{STOREFRONT_API_VERSION}/graphql.json"


async def _query(
    session: FetchSession, origin: str, query: str, variables: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    response = await session.post_json(
        graphql_url(origin), {"query": query, "variables": variables or {}}
    )
    if response is None or response.status_code != 200:
        return None
    try:
        body = response.json()
    except ValueError:
        session.stats.errors += 1
        return None
    if body.get("errors"):
        session.stats.errors += 1
        logger.warning(
            "storefront_graphql_errors", extra={"origin": origin, "errors": str(body["errors"])}
        )
    data = body.get("data")
    return data if isinstance(data, dict) else None


async def probe_primary_domain(session: FetchSession, origin: str) -> str | None:
    """URL del dominio principal si `origin` es una tienda Shopify; None si no lo es."""
    data = await _query(session, origin, PROBE_QUERY)
    shop = (data or {}).get("shop") or {}
    primary = (shop.get("primaryDomain") or {}).get("url")
    if not primary:
        return None
    return str(primary).rstrip("/")


async def collect(ctx: SourceContext) -> list[SourceDoc]:
    data = await _query(ctx.session, ctx.origin, CONTENT_QUERY)
    if data is None:
        return []
    docs: list[SourceDoc] = []
    shop = data.get("shop") or {}
    name = str(shop.get("name") or "").strip()
    if name:
        ctx.store_name = name
    if shop.get("description"):
        docs.append(
            SourceDoc.build(
                url=ctx.origin,
                kind=SourceKind.SHOP_PROFILE,
                title=str(shop.get("name") or ctx.origin),
                markdown=str(shop["description"]),
            )
        )
    for field in _POLICY_FIELDS:
        policy = shop.get(field)
        if not policy or not policy.get("body"):
            continue
        handle = str(policy.get("handle") or field)
        docs.append(
            SourceDoc.build(
                url=f"{ctx.origin}/policies/{handle}",
                kind=SourceKind.SHOP_POLICY,
                title=str(policy.get("title") or handle),
                markdown=await fragment_to_markdown(str(policy["body"])),
                priority=priority_of(handle),
            )
        )

    pages = list(((data.get("pages") or {}).get("nodes")) or [])
    page_info = (data.get("pages") or {}).get("pageInfo") or {}
    for _ in range(_MAX_PAGE_REQUESTS - 1):
        if not page_info.get("hasNextPage"):
            break
        more = await _query(
            ctx.session, ctx.origin, PAGES_QUERY, {"after": page_info.get("endCursor")}
        )
        if more is None:
            break
        pages.extend(((more.get("pages") or {}).get("nodes")) or [])
        page_info = (more.get("pages") or {}).get("pageInfo") or {}
    for page in pages:
        handle = str(page.get("handle") or "")
        if is_noise(handle):
            ctx.stats.discard(DiscardReason.NOISE_PAGE)
            continue
        docs.append(
            SourceDoc.build(
                url=str(page.get("onlineStoreUrl") or f"{ctx.origin}/pages/{handle}"),
                kind=SourceKind.SHOP_PAGE,
                title=str(page.get("title") or handle),
                markdown=await fragment_to_markdown(str(page.get("body") or "")),
                priority=priority_of(handle),
            )
        )

    for blog in ((data.get("blogs") or {}).get("nodes")) or []:
        for article in ((blog.get("articles") or {}).get("nodes")) or []:
            handle = str(article.get("handle") or "")
            title = str(article.get("title") or handle)
            if not is_cx_topic(f"{handle} {title}"):
                ctx.stats.discard(DiscardReason.NOT_CX_RELEVANT)
                continue
            docs.append(
                SourceDoc.build(
                    url=str(
                        article.get("onlineStoreUrl")
                        or f"{ctx.origin}/blogs/{blog.get('handle')}/{handle}"
                    ),
                    kind=SourceKind.BLOG_ARTICLE,
                    title=title,
                    markdown=await fragment_to_markdown(str(article.get("contentHtml") or "")),
                    priority=Priority.NORMAL,
                )
            )
    return docs


SPEC = SourceSpec(
    name=SourceName.STOREFRONT_API,
    platforms=frozenset({Platform.SHOPIFY}),
    collect=collect,
)
