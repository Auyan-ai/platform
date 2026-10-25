from __future__ import annotations

import httpx
import pytest
from apps.api.services.site_ingestion.models import (
    TRANSITIONS,
    IngestionStatus,
    Limits,
    Platform,
    Priority,
    SourceName,
    predecessors_of,
)
from apps.api.services.site_ingestion.orchestrator import collect_site
from apps.api.tests.site_ingestion_replay import Replay, SleepLog

LLMS_FULL = "https://example-store.es/llms-full.txt"
OWN_LLMS = (
    "# Tienda de ejemplo\n\nDevoluciones gratis durante 30 días desde la entrega. Escríbenos a "
    "hola@example-store.es o llama al 910 000 000 de lunes a viernes de 9 a 18 h. Envío gratis "
    "en pedidos de más de 50 euros a la península."
)


def _keys(collection, source: SourceName) -> list[str]:
    return [d.source_key for d in collection.docs_by_source.get(source, [])]


async def test_thinkingmu_reads_official_shopify_sources_and_drops_the_noise() -> None:
    replay = Replay(("thinkingmu",))
    sleep = SleepLog()

    collection = await collect_site(
        "https://thinkingmu.com/es", transport=replay.transport(), sleep=sleep
    )

    assert collection.platform is Platform.SHOPIFY
    assert collection.origin == "https://thinkingmu.com"
    assert _keys(collection, SourceName.STOREFRONT_API) == [
        "thinkingmu.com",
        "thinkingmu.com/policies/refund-policy",
        "thinkingmu.com/policies/shipping-policy",
        "thinkingmu.com/policies/terms-of-service",
        "thinkingmu.com/policies/subscription-policy",
        "thinkingmu.com/pages/envios-costes",
        "thinkingmu.com/pages/cambios-devoluciones",
    ]
    by_key = {d.source_key: d for d in collection.docs}
    assert by_key["thinkingmu.com/policies/terms-of-service"].priority is Priority.LOW
    assert by_key["thinkingmu.com/policies/refund-policy"].priority is Priority.NORMAL
    shipping_page = by_key["thinkingmu.com/pages/envios-costes"]
    assert shipping_page.title == "Tiempos de entrega y costes de envío"
    assert "| Islas Canarias | 3-5 días hábiles | 19,90€ (envío gratuito a partir de 140€) |" in (
        shipping_page.markdown
    )
    stats = collection.stats.to_json()["sources"]
    assert stats["storefront_api"]["discarded"] == {"noise_page": 2, "too_short": 2}


async def test_thinkingmu_generic_mcp_answers_and_default_llms_full_are_discarded() -> None:
    collection = await collect_site(
        "thinkingmu.com", transport=Replay(("thinkingmu",)).transport(), sleep=SleepLog()
    )

    stats = collection.stats.to_json()["sources"]
    assert _keys(collection, SourceName.STOREFRONT_MCP) == []
    assert stats["storefront_mcp"]["requests"] == 18
    assert stats["storefront_mcp"]["discarded"] == {"generic_mcp_answer": 3}
    assert _keys(collection, SourceName.AGENT_FILES) == []
    assert stats["agent_files"]["discarded"] == {"shopify_default_agent_file": 1}


async def test_shopify_html_429_with_long_retry_after_abandons_only_the_html_source() -> None:
    replay = Replay(("thinkingmu",))
    sleep = SleepLog()

    collection = await collect_site("thinkingmu.com", transport=replay.transport(), sleep=sleep)

    html = collection.stats.to_json()["sources"]["html"]
    assert html["abandoned"] == "rate_limited: retry_after=60s"
    assert html["rate_limited"] == 1
    assert sleep.calls == []
    assert replay.urls()[-1] == "https://thinkingmu.com/pages/pagina-contacto"
    assert collection.stats.docs == 7


async def test_mimitos_html_from_sitemap_to_markdown() -> None:
    replay = Replay(("mimitos",))

    collection = await collect_site("mimitos.es", transport=replay.transport(), sleep=SleepLog())

    assert collection.platform is Platform.OTHER
    assert _keys(collection, SourceName.HTML) == [
        "mimitos.es",
        "mimitos.es/blog/cuidado-durante-las-vacaciones",
    ]
    blog = collection.docs_by_source[SourceName.HTML][1]
    assert blog.title == "Cuidado durante las vacaciones · mimitos.es"
    assert "Aprende cómo darle a tu mascota una experiencia de vacaciones segura" in blog.markdown
    assert "<div" not in blog.markdown
    assert replay.urls()[:8] == [
        "https://mimitos.es/robots.txt",
        "https://mimitos.es/api/2025-07/graphql.json",
        "https://mimitos.es/llms-full.txt",
        "https://mimitos.es/llms.txt",
        "https://mimitos.es/agents.md",
        "https://mimitos.es/sitemap.xml",
        "https://mimitos.es/",
        "https://mimitos.es/blog/cuidado-durante-las-vacaciones",
    ]


async def test_robots_disallow_is_honored() -> None:
    def robots(request: httpx.Request) -> httpx.Response | None:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: AuyanBot\nDisallow: /blog/\n")
        return None

    replay = Replay(("mimitos",), overrides=[robots])

    collection = await collect_site("mimitos.es", transport=replay.transport(), sleep=SleepLog())

    assert _keys(collection, SourceName.HTML) == ["mimitos.es"]
    assert not any("/blog/" in url for url in replay.urls())
    assert collection.stats.to_json()["sources"]["html"]["blocked_by_robots"] == 22


async def test_unreadable_robots_means_nothing_is_read() -> None:
    def robots(request: httpx.Request) -> httpx.Response | None:
        if request.url.path == "/robots.txt":
            return httpx.Response(503)
        return None

    replay = Replay(("mimitos",), overrides=[robots])

    collection = await collect_site("mimitos.es", transport=replay.transport(), sleep=SleepLog())

    assert collection.docs == []
    assert collection.stats.robots == "unavailable"
    assert replay.urls() == ["https://mimitos.es/robots.txt"]


def _agent_file_site(llms_full: list[httpx.Response]) -> Replay:
    queue = iter(llms_full)

    def handler(request: httpx.Request) -> httpx.Response | None:
        if str(request.url) == LLMS_FULL:
            return next(queue)
        return httpx.Response(404)

    return Replay((), overrides=[handler])


async def test_429_waits_retry_after_and_retries() -> None:
    replay = _agent_file_site(
        [
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(200, headers={"content-type": "text/plain"}, text=OWN_LLMS),
        ]
    )
    sleep = SleepLog()

    collection = await collect_site("example-store.es", transport=replay.transport(), sleep=sleep)

    assert sleep.calls == [3.0]
    assert [d.markdown for d in collection.docs] == [OWN_LLMS]
    agent_files = collection.stats.to_json()["sources"]["agent_files"]
    assert (agent_files["rate_limited"], agent_files["abandoned"]) == (1, None)


async def test_repeated_429_abandons_the_source() -> None:
    replay = _agent_file_site([httpx.Response(429, headers={"Retry-After": "1"})] * 5)
    sleep = SleepLog()

    collection = await collect_site("example-store.es", transport=replay.transport(), sleep=sleep)

    agent_files = collection.stats.to_json()["sources"]["agent_files"]
    assert agent_files["abandoned"] == "rate_limited: 3x429"
    assert sleep.calls == [1.0, 1.0]
    assert replay.urls().count(LLMS_FULL) == 3
    assert "https://example-store.es/llms.txt" not in replay.urls()


async def test_request_budget_stops_the_ingestion() -> None:
    replay = Replay(("mimitos",))

    collection = await collect_site(
        "mimitos.es",
        transport=replay.transport(),
        sleep=SleepLog(),
        limits=Limits(max_requests=8),
    )

    assert len(replay.requests) == 8
    assert collection.stats.budget_exhausted is True
    assert _keys(collection, SourceName.HTML) == [
        "mimitos.es",
        "mimitos.es/blog/cuidado-durante-las-vacaciones",
    ]


def test_ingestion_state_machine() -> None:
    assert TRANSITIONS[IngestionStatus.READY] == frozenset()
    assert TRANSITIONS[IngestionStatus.FAILED] == frozenset()
    assert predecessors_of(IngestionStatus.READY) == ["extracting"]
    assert predecessors_of(IngestionStatus.EXTRACTING) == ["fetching"]
    assert predecessors_of(IngestionStatus.FETCHING) == ["extracting", "fetching", "queued"]


async def test_a_finished_ingestion_logs_its_summary_without_breaking_logging(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from uuid import uuid4

    from apps.api.db.site_ingestions import ClaimedIngestion
    from apps.api.services.site_ingestion import worker as worker_module
    from apps.api.services.site_ingestion.models import IngestionStats, Platform

    async def fake_run(job: ClaimedIngestion, *, transport: object = None) -> IngestionStats:
        return IngestionStats(root_url=job.root_url, platform=Platform.SHOPIFY, created=11)

    monkeypatch.setattr(worker_module, "run_ingestion", fake_run)
    job = ClaimedIngestion(
        id=uuid4(), tenant_id=uuid4(), root_url="https://alohas.io", attempts=1,
        max_attempts=3, requested_by=None,
    )
    worker = worker_module.SiteIngestionWorker(lease_seconds=3600)

    with caplog.at_level("INFO", logger=worker_module.__name__):
        await worker.execute(job)

    ready = [r for r in caplog.records if r.getMessage() == "site_ingestion_ready"]
    assert len(ready) == 1
    assert ready[0].submissions_created == 11
