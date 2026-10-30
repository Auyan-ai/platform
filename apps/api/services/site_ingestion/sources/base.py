from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.api.services.site_ingestion.fetcher import FetchSession, PoliteFetcher
    from apps.api.services.site_ingestion.models import (
        Platform,
        SourceDoc,
        SourceName,
        SourceStats,
    )
    from apps.api.services.site_ingestion.wordpress import WordPressIndex


@dataclass
class SourceContext:
    origin: str
    platform: Platform
    fetcher: PoliteFetcher
    session: FetchSession
    remaining_pages: int
    accepted_keys: frozenset[str] = frozenset()
    # Cada fuente rellena aquí el nombre oficial de la tienda si lo trae; la ingesta lo recoge.
    store_name: str | None = None
    # Índice REST de WordPress que dejó la detección de plataforma (solo WordPress/WooCommerce).
    wordpress: WordPressIndex | None = None

    @property
    def stats(self) -> SourceStats:
        return self.session.stats


@dataclass(frozen=True)
class SourceSpec:
    name: SourceName
    platforms: frozenset[Platform]
    collect: Callable[[SourceContext], Awaitable[list[SourceDoc]]]
