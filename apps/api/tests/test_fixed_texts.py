"""Catálogo de textos fijos: completo por idioma y con overrides por tenant."""

from __future__ import annotations

import string

import pytest
from apps.api.services.fixed_texts import CATALOG, LANGUAGE_CODES, fixed_text


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.mark.parametrize("key", sorted(CATALOG))
def test_every_key_has_every_language(key: str) -> None:
    texts = CATALOG[key]
    assert set(texts) == set(LANGUAGE_CODES), key
    assert all(t.strip() for t in texts.values()), key


@pytest.mark.parametrize("key", sorted(CATALOG))
def test_every_language_has_the_same_placeholders(key: str) -> None:
    found = {lang: _placeholders(text) for lang, text in CATALOG[key].items()}
    assert len({frozenset(p) for p in found.values()}) == 1, (key, found)


def test_translations_are_not_copies_of_the_spanish() -> None:
    copied = [
        (key, lang)
        for key, texts in CATALOG.items()
        for lang in ("en", "fr")
        if texts[lang] == texts["es"]
    ]
    assert copied == []


def test_each_language_in_its_own_words() -> None:
    assert fixed_text("unsupported", "es").startswith("¿En qué")
    assert (
        fixed_text("unsupported", "en") == "How can we help you? Please write your question for us."
    )
    assert fixed_text("unsupported", "ca").startswith("En què")
    assert fixed_text("unsupported", "fr").startswith("Comment")


def test_language_outside_the_catalog_falls_to_tenant_default_then_spanish() -> None:
    assert fixed_text("unsupported", "de", tenant_default="en").startswith("How can")
    assert fixed_text("unsupported", "de", tenant_default="pt").startswith("¿En qué")
    assert fixed_text("unsupported", None).startswith("¿En qué")


def test_params_fill_the_catalog_text() -> None:
    assert fixed_text("address_details", "en", address="Calle 1") == (
        "New shipping address: Calle 1."
    )


class TestOverrides:
    def test_plain_string_applies_only_to_the_tenant_default_language(self) -> None:
        overrides = {"unsupported": "  Dinos qué necesitas.  "}
        assert fixed_text("unsupported", "es", overrides=overrides) == "Dinos qué necesitas."
        assert fixed_text("unsupported", "en", overrides=overrides).startswith("How can")

    def test_plain_string_follows_a_non_spanish_tenant_default(self) -> None:
        overrides = {"unsupported": "Tell us what you need."}
        assert (
            fixed_text("unsupported", "en", tenant_default="en", overrides=overrides)
            == "Tell us what you need."
        )
        assert fixed_text("unsupported", "es", tenant_default="en", overrides=overrides).startswith(
            "¿En qué"
        )

    def test_dict_override_is_per_language(self) -> None:
        overrides = {"unsupported": {"en": "Tell us what you need.", "ca": "Digues-nos-ho."}}
        assert fixed_text("unsupported", "en", overrides=overrides) == "Tell us what you need."
        assert fixed_text("unsupported", "ca", overrides=overrides) == "Digues-nos-ho."
        assert fixed_text("unsupported", "fr", overrides=overrides).startswith("Comment")

    def test_language_without_override_or_catalog_uses_the_tenant_override(self) -> None:
        overrides = {"unsupported": "Dinos qué necesitas."}
        assert fixed_text("unsupported", "de", overrides=overrides) == "Dinos qué necesitas."

    def test_blank_or_malformed_overrides_are_ignored(self) -> None:
        for bad in ("   ", 5, None, {"es": " "}, ["x"]):
            assert fixed_text("unsupported", "es", overrides={"unsupported": bad}).startswith(
                "¿En qué"
            )

    def test_override_text_is_not_formatted(self) -> None:
        overrides = {"rejected": "Rechazado {sin_formato}"}
        assert fixed_text("rejected", "es", overrides=overrides, comment="x") == (
            "Rechazado {sin_formato}"
        )
