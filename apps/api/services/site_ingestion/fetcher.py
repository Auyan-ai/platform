from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from apps.api.integrations.demo_catalog import BOT_USER_AGENT, retry_after_seconds
from apps.api.services.site_ingestion.models import IngestionStats, Limits, SourceStats

logger = logging.getLogger(__name__)

ROBOTS_AGENT = "AuyanBot"
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_MAX_CRAWL_DELAY_SECONDS = 5.0


@dataclass
class _HostRobots:
    parser: RobotFileParser | None
    blocked: bool
    sitemaps: list[str]
    crawl_delay: float


class FetchSession:
    def __init__(self, fetcher: PoliteFetcher, stats: SourceStats) -> None:
        self._fetcher = fetcher
        self.stats = stats

    @property
    def abandoned(self) -> bool:
        return self.stats.abandoned is not None

    async def get(self, url: str) -> httpx.Response | None:
        return await self._fetcher.fetch(self, "GET", url)

    async def post_json(self, url: str, payload: dict[str, Any]) -> httpx.Response | None:
        return await self._fetcher.fetch(self, "POST", url, payload)

    def abandon(self, reason: str) -> None:
        if self.stats.abandoned is None:
            self.stats.abandoned = reason
            logger.info("site_ingestion_source_abandoned", extra={"reason": reason})


class PoliteFetcher:
    def __init__(
        self,
        stats: IngestionStats,
        *,
        limits: Limits | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.limits = limits or Limits()
        self._stats = stats
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            transport=transport,
            headers={"User-Agent": BOT_USER_AGENT},
            follow_redirects=False,
            timeout=self.limits.request_timeout_seconds,
        )
        self._robots: dict[str, _HostRobots] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}
        self._host_slots: dict[str, asyncio.Semaphore] = {}
        self._last_request_at: dict[str, float] = {}
        self._requests = 0

    async def __aenter__(self) -> PoliteFetcher:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    def session(self, name: str) -> FetchSession:
        return FetchSession(self, self._stats.source(name))

    async def sitemaps(self, url: str) -> list[str]:
        return list((await self._host_robots(url)).sitemaps)

    async def fetch(
        self,
        session: FetchSession,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response | None:
        for _ in range(self.limits.max_redirects + 1):
            if session.abandoned:
                return None
            robots = await self._host_robots(url)
            if robots.blocked or (
                robots.parser is not None and not robots.parser.can_fetch(ROBOTS_AGENT, url)
            ):
                session.stats.blocked_by_robots += 1
                return None
            response = await self._send(session, method, url, payload, robots.crawl_delay)
            if response is None or response.status_code not in _REDIRECTS:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            url = urljoin(url, location)
            if response.status_code == 303:
                method, payload = "GET", None
        session.stats.errors += 1
        return None

    async def _send(
        self,
        session: FetchSession,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
        crawl_delay: float,
    ) -> httpx.Response | None:
        host = _host(url)
        slots = self._host_slots.setdefault(
            host, asyncio.Semaphore(self.limits.per_domain_concurrency)
        )
        async with slots:
            while True:
                if session.abandoned:
                    return None
                if self._requests >= self.limits.max_requests:
                    self._stats.budget_exhausted = True
                    return None
                await self._respect_crawl_delay(host, crawl_delay)
                self._requests += 1
                session.stats.requests += 1
                try:
                    response = await self._client.request(method, url, json=payload)
                except httpx.HTTPError as exc:
                    session.stats.errors += 1
                    logger.info(
                        "site_ingestion_request_error",
                        extra={"url": url, "error": type(exc).__name__},
                    )
                    return None
                if response.status_code != 429:
                    return response
                session.stats.rate_limited += 1
                wait = retry_after_seconds(response)
                if wait > self.limits.max_retry_after_seconds:
                    session.abandon(f"rate_limited: retry_after={wait:g}s")
                    return None
                if session.stats.rate_limited >= self.limits.max_rate_limited_per_source:
                    session.abandon(f"rate_limited: {session.stats.rate_limited}x429")
                    return None
                await self._sleep(wait)

    async def _respect_crawl_delay(self, host: str, crawl_delay: float) -> None:
        if crawl_delay <= 0:
            return
        last = self._last_request_at.get(host)
        now = time.monotonic()
        if last is not None and now - last < crawl_delay:
            await self._sleep(crawl_delay - (now - last))
        self._last_request_at[host] = time.monotonic()

    async def _host_robots(self, url: str) -> _HostRobots:
        host = _host(url)
        cached = self._robots.get(host)
        if cached is not None:
            return cached
        async with self._robots_locks.setdefault(host, asyncio.Lock()):
            cached = self._robots.get(host)
            if cached is None:
                cached = await self._load_robots(url)
                self._robots[host] = cached
                if self._stats.robots == "unknown":
                    self._stats.robots = _robots_label(cached)
            return cached

    async def _load_robots(self, url: str) -> _HostRobots:
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        session = FetchSession(self, self._stats.robots_txt)
        response: httpx.Response | None = None
        for _ in range(self.limits.max_redirects + 1):
            response = await self._send(session, "GET", robots_url, None, 0.0)
            if response is None or response.status_code not in _REDIRECTS:
                break
            robots_url = urljoin(robots_url, response.headers.get("location", ""))
        # RFC 9309 §2.3.1.4: robots.txt inaccesible (5xx o error de red) veta todo el host.
        if response is None or response.status_code >= 500 or response.status_code == 429:
            return _HostRobots(parser=None, blocked=True, sitemaps=[], crawl_delay=0.0)
        if response.status_code >= 400:
            return _HostRobots(parser=None, blocked=False, sitemaps=[], crawl_delay=0.0)
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        delay = parser.crawl_delay(ROBOTS_AGENT)
        return _HostRobots(
            parser=parser,
            blocked=False,
            sitemaps=list(parser.site_maps() or []),
            crawl_delay=min(float(delay or 0), _MAX_CRAWL_DELAY_SECONDS),
        )


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _robots_label(robots: _HostRobots) -> str:
    if robots.blocked:
        return "unavailable"
    return "missing" if robots.parser is None else "ok"
