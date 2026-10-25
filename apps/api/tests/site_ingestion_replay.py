"""Respuestas grabadas de tiendas reales (AuyanBot, sesión 87) para los tests de la ingesta.

Recortes respecto a la grabación: la Storefront API de Thinking MU conserva 7 de sus 100 páginas
(con `hasNextPage` a false) y del MCP se guardan las 3 respuestas con contenido; el resto de
preguntas devuelve la lista vacía que dio la tienda. Lo que no está grabado responde 404.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).parent / "fixtures" / "site_ingestion"

Override = Callable[[httpx.Request], httpx.Response | None]


@dataclass
class Replay:
    stores: tuple[str, ...]
    overrides: list[Override] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._entries: list[tuple[Path, dict[str, Any]]] = []
        for store in self.stores:
            folder = FIXTURES / store
            for entry in json.loads((folder / "manifest.json").read_text()):
                self._entries.append((folder, entry))

    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for override in self.overrides:
            response = override(request)
            if response is not None:
                return response
        body = request.content.decode() if request.content else ""
        for folder, entry in self._entries:
            if entry["method"] != request.method or not _url_matches(entry["url"], request):
                continue
            if entry.get("match") and entry["match"] not in body:
                continue
            return httpx.Response(
                entry["status"],
                headers=entry["headers"],
                content=(folder / entry["file"]).read_bytes(),
            )
        return httpx.Response(404, text="not recorded")


def _url_matches(pattern: str, request: httpx.Request) -> bool:
    url = str(request.url)
    return url.startswith(pattern[:-1]) if pattern.endswith("*") else url == pattern


class SleepLog:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
