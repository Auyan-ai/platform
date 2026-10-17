"""Idioma de la conversación decidido en código (services/language.py)."""

from __future__ import annotations

import pytest
from apps.api.agents.graph import route_after_respond
from apps.api.agents.nodes.respond import LANGUAGE_MISMATCH, REGENERATE, check_reply_language
from apps.api.agents.prompts.builder import build_system_blocks, conversation_context_block
from apps.api.services.language import (
    conversation_language,
    detect,
    reply_language_mismatch,
    tenant_languages,
)

ALL = frozenset({"es", "en", "ca", "fr", "pt", "de", "it"})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hi, I need to track my order #1234", "en"),
        ("Hola, ¿cómo va el pedido #1234?", "es"),
        ("Bon dia, on és la meva comanda?", "ca"),
        ("Can you answer in English please", "en"),
        ("ok", None),
        ("#1234", None),
        ("ana@tienda.com 600111222", None),
        ("https://wwwapps.ups.com/tracking/1Z999", None),
    ],
)
def test_detect(text: str, expected: str | None) -> None:
    assert detect(text, ALL) == expected


def test_detect_only_among_supported_languages() -> None:
    assert detect("Bon dia, on és la meva comanda?", frozenset({"es", "en"})) != "ca"


def test_tenant_languages_defaults_and_validation() -> None:
    assert tenant_languages(None) == ("es", ALL)
    default, supported = tenant_languages({"languages": {"default": "en", "supported": ["es"]}})
    assert default == "en" and supported == {"es", "en"}
    assert tenant_languages({"languages": {"default": "xx", "supported": ["zz"]}})[0] == "es"


def test_first_reliable_detection_fixes_the_language() -> None:
    assert conversation_language(None, ["Hi, I need my order"], default="es", supported=ALL) == "en"


def test_without_reliable_text_the_tenant_default_wins() -> None:
    assert conversation_language(None, ["ok", "#1234"], default="es", supported=ALL) == "es"


def test_a_short_message_keeps_the_language() -> None:
    assert conversation_language("en", ["vale"], default="es", supported=ALL) == "en"


def test_a_clear_message_in_another_language_switches_it() -> None:
    assert (
        conversation_language(
            "es", ["Can you answer in English please"], default="es", supported=ALL
        )
        == "en"
    )


def test_an_unsupported_stored_language_is_detected_again() -> None:
    assert (
        conversation_language(
            "fr",
            ["Hola, quiero saber de mi pedido"],
            default="es",
            supported=frozenset({"es", "en"}),
        )
        == "es"
    )


def test_reply_language_mismatch() -> None:
    reply = "¡Hola! Tu pedido #1234 ya ha sido enviado con UPS."
    assert reply_language_mismatch(reply, "en", ALL) == "es"
    assert reply_language_mismatch("Your order #1234 has shipped with UPS.", "en", ALL) is None
    assert reply_language_mismatch("1Z999AA10123456784", "en", ALL) is None


def _state(**extra: object) -> dict:
    return {
        "tenant_id": "t",
        "conversation_id": "c",
        "response_language": "en",
        "supported_languages": sorted(ALL),
        **extra,
    }


def test_wrong_reply_language_is_regenerated_once_then_escalated() -> None:
    reply = "¡Hola! Tu pedido #1234 ya ha sido enviado con UPS, ¿necesitas algo más?"
    first = check_reply_language(_state(), reply)
    assert first is not None and first["decision"] == REGENERATE
    assert "inglés" in first["supervisor_feedback"]
    assert route_after_respond({**first}) == "reason"

    second = check_reply_language(_state(language_retry=True), reply)
    assert second is not None and second["decision"] == "escalate"
    assert second["escalation_reason"].startswith(LANGUAGE_MISMATCH)
    assert route_after_respond({**second}) == "escalate"


def test_right_reply_language_is_delivered() -> None:
    assert check_reply_language(_state(), "Your order #1234 has shipped with UPS.") is None
    assert check_reply_language({}, "cualquier cosa") is None


def test_the_language_control_line_is_the_last_thing_before_generating() -> None:
    blocks = build_system_blocks(
        "AOP", [], current_date="2026-10-18", supervisor_feedback="x", response_language="en"
    )
    assert blocks[-1]["text"].endswith("Escribe al cliente en inglés (en).")


def test_the_greeting_has_no_literal_in_spanish() -> None:
    block = conversation_context_block([], {"full_name": "Ana López"})
    assert "¡Hola" not in block
    assert "Ana" in block
