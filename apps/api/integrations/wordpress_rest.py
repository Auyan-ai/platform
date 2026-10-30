"""URLs de la REST API de WordPress en sus dos formas (`/wp-json/...` y `/?rest_route=/...`)."""

from __future__ import annotations

from urllib.parse import urlencode


def rest_url(origin: str, route: str, *, pretty: bool, **params: str | int) -> str:
    route = "/" + route.lstrip("/")
    if pretty:
        query = urlencode(params, safe=",")
        return f"{origin}/wp-json{route}" + (f"?{query}" if query else "")
    return f"{origin}/?" + urlencode({"rest_route": route, **params}, safe="/,")
