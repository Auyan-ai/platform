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


@dataclass
class SourceContext:
    origin: str
    platform: Platform
    fetcher: PoliteFetcher
    session: FetchSession
    remaining_pages: int
    accepted_keys: frozenset[str] = frozenset()

    @property
    def stats(self) -> SourceStats:
        return self.session.stats


@dataclass(frozen=True)
class SourceSpec:
    name: SourceName
    platforms: frozenset[Platform]
    collect: Callable[[SourceContext], Awaitable[list[SourceDoc]]]
