"""Detección de WordPress y WooCommerce por el índice de su REST API (ADR 0016 §7, #422).

`GET <origen>/wp-json/` lista `name` y los espacios de nombres. Si `/wp-json` está bloqueado o
redirige mal, `GET <origen>/?rest_route=/` devuelve lo mismo. La forma que respondió queda en
el índice para que el resto de lecturas (páginas, entradas) use la misma.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from apps.api.integrations.wordpress_rest import rest_url
from apps.api.services.site_ingestion.models import Platform

if TYPE_CHECKING:
    from apps.api.services.site_ingestion.fetcher import FetchSession

STORE_API_PREFIX = "wc/store"
# El índice completo pesa más de 1 MB en una tienda con plugins; esto es todo lo que se lee.
INDEX_FIELDS = "name,description,namespaces"


@dataclass(frozen=True)
class WordPressIndex:
    origin: str
    pretty: bool
    name: str
    description: str
    namespaces: frozenset[str]

    @property
    def platform(self) -> Platform:
        if any(ns.startswith(STORE_API_PREFIX) for ns in self.namespaces):
            return Platform.WOOCOMMERCE
        if "wp/v2" in self.namespaces:
            return Platform.WORDPRESS
        return Platform.OTHER

    def url(self, route: str, **params: str | int) -> str:
        return rest_url(self.origin, route, pretty=self.pretty, **params)


def _index_from_json(origin: str, body: Any, *, pretty: bool) -> WordPressIndex | None:
    if not isinstance(body, dict) or not isinstance(body.get("namespaces"), list):
        return None
    return WordPressIndex(
        origin=origin,
        pretty=pretty,
        name=html.unescape(str(body.get("name") or "")).strip(),
        description=html.unescape(str(body.get("description") or "")).strip(),
        namespaces=frozenset(str(ns) for ns in body["namespaces"]),
    )


async def probe_wordpress(session: FetchSession, origin: str) -> WordPressIndex | None:
    """Índice REST de `origin` si es un WordPress; None si no lo es o su API está cerrada.

    El respaldo `?rest_route=` no se usa si robots.txt vetó `/wp-json/`: es la misma API por otra
    puerta y el dueño del sitio ya dijo que no.
    """
    for pretty in (True, False):
        blocked_before = session.stats.blocked_by_robots
        response = await session.get(rest_url(origin, "/", pretty=pretty, _fields=INDEX_FIELDS))
        if session.stats.blocked_by_robots > blocked_before:
            return None
        if response is None or response.status_code != 200:
            continue
        try:
            index = _index_from_json(origin, response.json(), pretty=pretty)
        except ValueError:
            continue
        if index is not None:
            return index
    return None
