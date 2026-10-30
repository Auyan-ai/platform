from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from apps.api.services.kb_source_key import canonical_source_key, content_sha256


class IngestionStatus(StrEnum):
    QUEUED = "queued"
    FETCHING = "fetching"
    EXTRACTING = "extracting"
    READY = "ready"
    FAILED = "failed"


TRANSITIONS: dict[IngestionStatus, frozenset[IngestionStatus]] = {
    IngestionStatus.QUEUED: frozenset({IngestionStatus.FETCHING}),
    IngestionStatus.FETCHING: frozenset(
        {
            IngestionStatus.FETCHING,
            IngestionStatus.EXTRACTING,
            IngestionStatus.QUEUED,
            IngestionStatus.FAILED,
        }
    ),
    IngestionStatus.EXTRACTING: frozenset(
        {
            IngestionStatus.FETCHING,
            IngestionStatus.READY,
            IngestionStatus.QUEUED,
            IngestionStatus.FAILED,
        }
    ),
    IngestionStatus.READY: frozenset(),
    IngestionStatus.FAILED: frozenset(),
}

ACTIVE_STATUSES: frozenset[IngestionStatus] = frozenset(
    s for s, targets in TRANSITIONS.items() if targets
)


def predecessors_of(target: IngestionStatus) -> list[str]:
    return sorted(s.value for s, targets in TRANSITIONS.items() if target in targets)


class Platform(StrEnum):
    SHOPIFY = "shopify"
    WOOCOMMERCE = "woocommerce"
    WORDPRESS = "wordpress"
    OTHER = "other"


class SourceName(StrEnum):
    STOREFRONT_API = "storefront_api"
    STOREFRONT_MCP = "storefront_mcp"
    WORDPRESS_API = "wordpress_api"
    AGENT_FILES = "agent_files"
    HTML = "html"


class SourceKind(StrEnum):
    SHOP_PROFILE = "shop_profile"
    SHOP_POLICY = "shop_policy"
    SHOP_PAGE = "shop_page"
    BLOG_ARTICLE = "blog_article"
    FAQ_ANSWER = "faq_answer"
    AGENT_FILE = "agent_file"
    WEB_PAGE = "web_page"


MIN_WORDS: dict[SourceKind, int] = {
    SourceKind.SHOP_PROFILE: 25,
    SourceKind.SHOP_POLICY: 25,
    SourceKind.SHOP_PAGE: 25,
    SourceKind.BLOG_ARTICLE: 25,
    SourceKind.FAQ_ANSWER: 8,
    SourceKind.AGENT_FILE: 25,
    SourceKind.WEB_PAGE: 25,
}


class Priority(StrEnum):
    NORMAL = "normal"
    LOW = "low"


class DiscardReason(StrEnum):
    TOO_SHORT = "too_short"
    BOILERPLATE_ONLY = "boilerplate_only"
    NOISE_PAGE = "noise_page"
    NOT_CX_RELEVANT = "not_cx_relevant"
    SHOPIFY_DEFAULT_AGENT_FILE = "shopify_default_agent_file"
    GENERIC_MCP_ANSWER = "generic_mcp_answer"
    NOT_PLAIN_TEXT = "not_plain_text"
    EMPTY_EXTRACTION = "empty_extraction"
    DUPLICATE_CONTENT = "duplicate_content"
    DUPLICATE_SOURCE_KEY = "duplicate_source_key"
    PAGE_BUDGET = "page_budget"
    UNCHANGED = "unchanged"
    ALREADY_PENDING = "already_pending"


@dataclass(frozen=True)
class SourceDoc:
    source_key: str
    url: str
    kind: SourceKind
    title: str
    markdown: str
    sha256: str
    priority: Priority = Priority.NORMAL

    @classmethod
    def build(
        cls,
        *,
        url: str,
        kind: SourceKind,
        title: str,
        markdown: str,
        source_key: str | None = None,
        priority: Priority = Priority.NORMAL,
    ) -> SourceDoc:
        text = markdown.strip()
        return cls(
            source_key=source_key or canonical_source_key(url),
            url=url,
            kind=kind,
            title=title.strip() or url,
            markdown=text,
            sha256=content_sha256(text),
            priority=priority,
        )

    @property
    def words(self) -> int:
        return len(self.markdown.split())


@dataclass
class SourceStats:
    docs: int = 0
    words: int = 0
    requests: int = 0
    rate_limited: int = 0
    blocked_by_robots: int = 0
    errors: int = 0
    seconds: float = 0.0
    abandoned: str | None = None
    discarded: Counter[str] = field(default_factory=Counter)

    def discard(self, reason: DiscardReason, n: int = 1) -> None:
        self.discarded[reason.value] += n


@dataclass
class IngestionStats:
    root_url: str
    origin: str = ""
    platform: Platform | None = None
    seconds: float = 0.0
    budget_exhausted: bool = False
    robots: str = "unknown"
    sources: dict[str, SourceStats] = field(default_factory=dict)
    robots_txt: SourceStats = field(default_factory=SourceStats)
    created: int = 0
    # Nombre oficial de la tienda según su fuente (Shopify `shop.name`, WordPress `name`...).
    store_name: str | None = None

    def source(self, name: str) -> SourceStats:
        return self.sources.setdefault(name, SourceStats())

    @property
    def requests(self) -> int:
        return self.robots_txt.requests + sum(s.requests for s in self.sources.values())

    @property
    def rate_limited(self) -> int:
        return self.robots_txt.rate_limited + sum(s.rate_limited for s in self.sources.values())

    @property
    def docs(self) -> int:
        return sum(s.docs for s in self.sources.values())

    @property
    def words(self) -> int:
        return sum(s.words for s in self.sources.values())

    def to_json(self) -> dict[str, Any]:
        return {
            "root_url": self.root_url,
            "origin": self.origin,
            "platform": self.platform.value if self.platform else None,
            "seconds": round(self.seconds, 1),
            "budget_exhausted": self.budget_exhausted,
            "robots": self.robots,
            "requests": self.requests,
            "rate_limited": self.rate_limited,
            "docs": self.docs,
            "words": self.words,
            "created": self.created,
            "store_name": self.store_name,
            "robots_txt": _source_json(self.robots_txt),
            "sources": {name: _source_json(s) for name, s in self.sources.items()},
        }


def _source_json(stats: SourceStats) -> dict[str, Any]:
    return {**asdict(stats), "seconds": round(stats.seconds, 1), "discarded": dict(stats.discarded)}


@dataclass(frozen=True)
class Limits:
    max_pages: int = 60
    max_requests: int = 150
    per_domain_concurrency: int = 2
    max_retry_after_seconds: float = 10.0
    max_rate_limited_per_source: int = 3
    request_timeout_seconds: float = 20.0
    max_redirects: int = 3
