"""Ingesta de WordPress/WooCommerce contra respuestas grabadas de un WooCommerce real.

Grabación: WordPress Playground local con WooCommerce de wordpress.org (s88), servido como
`tienda-prueba-auyan.test`. Los casos marcados "sintético" fabrican la respuesta que el
Playground no tiene (página de política de WooCommerce, paginación, entradas).
"""

from __future__ import annotations

import httpx
from apps.api.services.site_ingestion.models import Platform, Priority, SourceKind, SourceName
from apps.api.services.site_ingestion.orchestrator import collect_site
from apps.api.tests.site_ingestion_replay import Replay, SleepLog

ORIGIN = "https://tienda-prueba-auyan.test"
INDEX_QUERY = "_fields=name,description,namespaces"
INDEX = {
    "name": "Tienda X",
    "description": "",
    "namespaces": ["wp/v2", "wc/store/v1"],
}
LONG = "<p>" + "Plazo de devolución de treinta días desde la entrega. " * 6 + "</p>"


def _page(slug: str, title: str, html: str = "") -> dict:
    return {
        "slug": slug,
        "title": {"rendered": title},
        "content": {"rendered": html or f"{LONG}<p>Página {slug}.</p>"},
        "link": f"{ORIGIN}/{slug}/",
        "modified": "2026-10-25T10:00:00",
    }


def _json(body: object, **headers: str) -> httpx.Response:
    return httpx.Response(200, json=body, headers=headers)


def _wp(replay: Replay, *, index=INDEX, pages=(), posts=()) -> None:
    def override(request: httpx.Request) -> httpx.Response | None:
        url = str(request.url)
        if url in (f"{ORIGIN}/wp-json/?{INDEX_QUERY}", f"{ORIGIN}/?rest_route=/&{INDEX_QUERY}"):
            return _json(index)
        if "/wp/v2/pages" in url:
            return _json(list(pages), **{"X-WP-TotalPages": "1"})
        if "/wp/v2/posts" in url:
            return _json(list(posts), **{"X-WP-TotalPages": "1"})
        return None

    replay.overrides.insert(0, override)


async def test_recorded_woocommerce_is_detected_and_pages_come_from_the_rest_api() -> None:
    replay = Replay(("woocommerce",))

    collection = await collect_site(ORIGIN, transport=replay.transport(), sleep=SleepLog())

    assert collection.platform is Platform.WOOCOMMERCE
    assert collection.stats.store_name == "Tienda Prueba Auyan"
    wp_docs = collection.docs_by_source[SourceName.WORDPRESS_API]
    assert [(d.source_key, d.kind, d.title) for d in wp_docs] == [
        ("tienda-prueba-auyan.test/faq", SourceKind.SHOP_PAGE, "Preguntas frecuentes")
    ]
    assert "Baleares y Canarias de 3 a 5 días" in wp_docs[0].markdown
    stats = collection.stats.to_json()["sources"]["wordpress_api"]
    assert stats["discarded"] == {"noise_page": 4, "not_cx_relevant": 1, "too_short": 2}
    assert "tienda-prueba-auyan.test/faq" not in [
        d.source_key for d in collection.docs_by_source.get(SourceName.HTML, [])
    ]
    pages_request = next(u for u in replay.urls() if "/wp/v2/pages" in u)
    assert pages_request == (
        f"{ORIGIN}/wp-json/wp/v2/pages?per_page=100&page=1&_fields=slug,title,content,link,modified"
    )


async def test_recorded_rest_route_form_when_wp_json_is_blocked() -> None:
    replay = Replay(("woocommerce",))
    replay.overrides.append(
        lambda r: httpx.Response(403, text="blocked") if "/wp-json" in str(r.url) else None
    )

    collection = await collect_site(ORIGIN, transport=replay.transport(), sleep=SleepLog())

    assert collection.platform is Platform.WOOCOMMERCE
    assert collection.stats.store_name == "Tienda Prueba Auyan"
    assert [d.source_key for d in collection.docs_by_source[SourceName.WORDPRESS_API]] == [
        "tienda-prueba-auyan.test/faq"
    ]
    assert f"{ORIGIN}/?rest_route=/&{INDEX_QUERY}" in replay.urls()
    assert any("rest_route=/wp/v2/pages" in u for u in replay.urls())


async def test_wp_json_html_catch_all_falls_back_to_rest_route() -> None:
    replay = Replay(("woocommerce",))
    replay.overrides.append(
        lambda r: (
            httpx.Response(200, text="<html>home</html>", headers={"content-type": "text/html"})
            if str(r.url) == f"{ORIGIN}/wp-json/?{INDEX_QUERY}"
            else None
        )
    )

    collection = await collect_site(ORIGIN, transport=replay.transport(), sleep=SleepLog())

    assert collection.platform is Platform.WOOCOMMERCE


async def test_robots_veto_on_wp_json_does_not_open_the_same_api_through_rest_route() -> None:
    replay = Replay(("woocommerce",))
    replay.overrides.append(
        lambda r: (
            httpx.Response(200, text="User-agent: *\nDisallow: /wp-json/\n")
            if str(r.url).endswith("/robots.txt")
            else None
        )
    )

    collection = await collect_site(ORIGIN, transport=replay.transport(), sleep=SleepLog())

    assert collection.platform is Platform.OTHER
    assert not any("rest_route" in u for u in replay.urls())
    assert SourceName.WORDPRESS_API not in collection.docs_by_source


async def test_wordpress_without_store_api_is_wordpress() -> None:
    replay = Replay(("woocommerce",))
    _wp(
        replay,
        index={"name": "Blog", "description": "", "namespaces": ["wp/v2"]},
        pages=[_page("envios", "Envíos")],
    )

    collection = await collect_site(ORIGIN, transport=replay.transport(), sleep=SleepLog())

    assert collection.platform is Platform.WORDPRESS
    assert collection.stats.store_name == "Blog"
    assert [d.source_key for d in collection.docs_by_source[SourceName.WORDPRESS_API]] == [
        "tienda-prueba-auyan.test/envios"
    ]


async def test_woocommerce_refund_page_is_the_policy_and_legal_pages_are_low_priority() -> None:
    replay = Replay(("woocommerce",))
    _wp(
        replay,
        pages=[
            _page("refund_returns", "Refund and Returns Policy"),
            _page("terminos-y-condiciones", "Términos y condiciones"),
            _page("politica-de-privacidad", "Política de privacidad"),
            _page("carrito", "Carrito"),
        ],
    )

    collection = await collect_site(ORIGIN, transport=replay.transport(), sleep=SleepLog())

    docs = {d.source_key: d for d in collection.docs_by_source[SourceName.WORDPRESS_API]}
    assert sorted(docs) == [
        "tienda-prueba-auyan.test/refund_returns",
        "tienda-prueba-auyan.test/terminos-y-condiciones",
    ]
    policy = docs["tienda-prueba-auyan.test/refund_returns"]
    assert policy.kind is SourceKind.SHOP_POLICY
    assert policy.priority is Priority.NORMAL
    assert docs["tienda-prueba-auyan.test/terminos-y-condiciones"].priority is Priority.LOW


async def test_pages_are_paginated_by_total_pages_header() -> None:
    replay = Replay(("woocommerce",))
    seen: list[str] = []

    def override(request: httpx.Request) -> httpx.Response | None:
        url = str(request.url)
        if url == f"{ORIGIN}/wp-json/?{INDEX_QUERY}":
            return _json(INDEX)
        if "/wp/v2/pages" in url:
            seen.append(url)
            n = 1 if "&page=1&" in url else 2
            return _json(
                [
                    _page(
                        f"envios-{n}",
                        f"Envíos {n}",
                        f"<p>{f'Envío a la zona {n} en 48 horas laborables. ' * 6}</p>",
                    )
                ],
                **{"X-WP-TotalPages": "2"},
            )
        if "/wp/v2/posts" in url:
            return _json([])
        return None

    replay.overrides.insert(0, override)

    collection = await collect_site(ORIGIN, transport=replay.transport(), sleep=SleepLog())

    assert [d.source_key for d in collection.docs_by_source[SourceName.WORDPRESS_API]] == [
        "tienda-prueba-auyan.test/envios-1",
        "tienda-prueba-auyan.test/envios-2",
    ]
    assert [u.split("&page=")[1].split("&")[0] for u in seen] == ["1", "2"]


async def test_only_cx_relevant_posts_are_kept() -> None:
    replay = Replay(("woocommerce",))
    _wp(
        replay,
        posts=[
            _page("guia-de-tallas", "Guía de tallas"),
            _page("nuestra-receta-de-verano", "Nuestra receta de verano"),
        ],
    )

    collection = await collect_site(ORIGIN, transport=replay.transport(), sleep=SleepLog())

    posts = [
        d
        for d in collection.docs_by_source[SourceName.WORDPRESS_API]
        if d.kind is SourceKind.BLOG_ARTICLE
    ]
    assert [d.source_key for d in posts] == ["tienda-prueba-auyan.test/guia-de-tallas"]
    discarded = collection.stats.sources["wordpress_api"].discarded
    assert discarded["not_cx_relevant"] >= 1
