"""`canonical_source_key`: una fuente, una clave (ADR 0015 §3)."""

from __future__ import annotations

import pytest
from apps.api.services.kb_source_key import canonical_source_key, content_sha256


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://tienda.com/politica", "tienda.com/politica"),
        ("http://Tienda.COM/politica", "tienda.com/politica"),
        ("https://www.tienda.com/politica/", "tienda.com/politica"),
        ("https://tienda.com/politica?utm_source=x&a=1", "tienda.com/politica"),
        ("https://tienda.com/politica#devoluciones", "tienda.com/politica"),
        ("https://tienda.com/politica/?a=1#x", "tienda.com/politica"),
        ("https://tienda.com/", "tienda.com"),
        ("https://tienda.com?x=1", "tienda.com"),
        ("  HTTPS://WWW.Tienda.com/Politica/Envios//  ", "tienda.com/Politica/Envios"),
        ("tienda.com/faq", "tienda.com/faq"),
        ("https://tienda.com:8080/a", "tienda.com:8080/a"),
    ],
)
def test_canonical_source_key(url: str, expected: str) -> None:
    assert canonical_source_key(url) == expected


def test_variants_of_the_same_page_share_one_key() -> None:
    variants = [
        "https://www.tienda.com/envios/",
        "http://tienda.com/envios?ref=home",
        "HTTPS://TIENDA.COM/envios#plazos",
    ]
    assert len({canonical_source_key(v) for v in variants}) == 1


@pytest.mark.parametrize("url", ["", "   ", "https://", "https:///solo-path"])
def test_url_without_host_is_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        canonical_source_key(url)


def test_content_sha256_ignores_surrounding_whitespace() -> None:
    assert content_sha256("  hola\n") == content_sha256("hola")
    assert content_sha256("hola") != content_sha256("adiós")
