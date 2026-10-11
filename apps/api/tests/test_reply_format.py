"""Normalizador de salida por superficie (código, sin LLM)."""

from __future__ import annotations

import pytest
from apps.api.services.reply_format import (
    email_signature,
    finalize_reply,
    has_emoji,
    has_markdown,
    remove_trailing_signoff,
    strip_emojis,
    strip_formatting,
)

# ─── Markdown fuera ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tu pedido **#1001** va en camino", "Tu pedido #1001 va en camino"),
        ("Tu pedido __#1001__ va en camino", "Tu pedido #1001 va en camino"),
        ("Es *importante* que revises", "Es importante que revises"),
        ("Es _importante_ que revises", "Es importante que revises"),
        ("*Tu pedido* sale hoy", "Tu pedido sale hoy"),
        ("Antes ~~costaba 20~~ ahora 15", "Antes costaba 20 ahora 15"),
        ("## Resumen\nTodo listo", "Resumen\nTodo listo"),
        ("Usa el código `ABC-123` al pagar", "Usa el código ABC-123 al pagar"),
        ("> cita del cliente\nrespuesta", "cita del cliente\nrespuesta"),
        ("Hola<br>mundo", "Hola\nmundo"),
        ("Café &amp; té&nbsp;frío", "Café & té frío"),
    ],
)
def test_strip_formatting_inline(raw: str, expected: str) -> None:
    assert strip_formatting(raw) == expected


def test_code_fence_keeps_content_drops_fences() -> None:
    raw = 'Mira:\n```json\n{"a": 1}\n```\nlisto'
    assert strip_formatting(raw) == 'Mira:\n{"a": 1}\nlisto'


def test_table_rows_become_plain_lines_without_separator() -> None:
    raw = "| Pedido | Estado |\n|---|---|\n| #1001 | Enviado |"
    assert strip_formatting(raw) == "Pedido, Estado\n#1001, Enviado"


def test_horizontal_rule_removed() -> None:
    assert strip_formatting("uno\n\n---\n\ndos") == "uno\n\ndos"


def test_link_at_end_of_line_uses_colon() -> None:
    raw = "Sigue tu envío en [este enlace](https://t.co/x?id=1)"
    assert strip_formatting(raw) == "Sigue tu envío en este enlace: https://t.co/x?id=1"


def test_link_mid_sentence_uses_parentheses() -> None:
    raw = "Mira [las condiciones](https://t.co/c) antes de pedir"
    assert strip_formatting(raw) == "Mira las condiciones (https://t.co/c) antes de pedir"


def test_link_with_url_as_text_collapses_to_url() -> None:
    assert strip_formatting("[https://t.co/x](https://t.co/x)") == "https://t.co/x"


def test_autolink_and_image() -> None:
    assert strip_formatting("Web: <https://t.co/x>") == "Web: https://t.co/x"
    assert strip_formatting("![foto](https://t.co/i.png)") == "foto: https://t.co/i.png"


# ─── Viñetas ─────────────────────────────────────────────────────────────────


def test_bullets_lose_symbol_keep_one_item_per_line() -> None:
    raw = "Puedes:\n- cambiar la talla\n* devolverlo\n• pedir reembolso"
    assert strip_formatting(raw) == "Puedes:\ncambiar la talla\ndevolverlo\npedir reembolso"


def test_numbered_lists_keep_their_numbers() -> None:
    raw = "Pasos:\n1. Entra\n2. Pulsa devolver"
    assert strip_formatting(raw) == raw


def test_bullet_regex_does_not_eat_negative_numbers_or_dashes_in_words() -> None:
    raw = "Hace -5 grados y el pedido ABC-123 llega"
    assert strip_formatting(raw) == raw


# ─── Nada de datos se altera ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "safe",
    [
        "Tu pedido #1001 cuesta 1.234,50 € y llega el 12/03/2026",
        "Escríbenos a ayuda_ventas@marea_studio.com o a soporte@tienda.com",
        "Rastrea en https://track.example.com/a_b_c/_x_?ref=1&n=2 hoy",
        "Pedido ORD_123_X con total $1,299.00 (IVA incl.)",
        "2 * 3 = 6 y 4*5=20",
        "Son ~5 días, tal vez ~6",
        "Llama al +34 910 123 456 o al (555) 123-4567",
        "Código SKU-9_9-A y 100% algodón",
    ],
)
def test_data_is_never_altered(safe: str) -> None:
    assert strip_formatting(safe) == safe


def test_formatting_around_protected_tokens_still_stripped() -> None:
    raw = "**Pedido #A_1_B** a ana_b@x_y.com y https://t.co/_k_"
    assert strip_formatting(raw) == "Pedido #A_1_B a ana_b@x_y.com y https://t.co/_k_"


def test_strip_formatting_is_idempotent() -> None:
    raw = "## Hola\n**uno** y _dos_\n- a\n- b\n[x](https://t.co) fin"
    once = strip_formatting(raw)
    assert strip_formatting(once) == once


# ─── has_markdown / has_emoji ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    ["**hola**", "# Título", "- uno\n- dos", "[a](https://b.co)", "```x```", "| a | b |\n|-|-|"],
)
def test_has_markdown_true(text: str) -> None:
    assert has_markdown(text)


@pytest.mark.parametrize(
    "text",
    ["Hola, tu pedido #1001 sale hoy.", "Mira https://t.co/a_b_c ya", "2 * 3 = 6", ""],
)
def test_has_markdown_false(text: str) -> None:
    assert not has_markdown(text)


def test_has_emoji() -> None:
    assert has_emoji("Gracias 😊")
    assert has_emoji("Listo ✅")
    assert has_emoji("Va en camino 🚚")
    assert not has_emoji("Gracias. Precio 5 € ™ © ® ¡Hola! ¿Qué tal? → ok")


# ─── Emojis ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("¡Gracias! 😊", "¡Gracias!"),
        ("Listo ✅ tu pedido va en camino", "Listo tu pedido va en camino"),
        ("Gracias 😊.", "Gracias."),
        ("🚚 Tu pedido sale hoy", "Tu pedido sale hoy"),
        ("Hola 👋🏽, ¿qué tal?", "Hola, ¿qué tal?"),
        ("Pedido 1️⃣ de 2", "Pedido 1 de 2"),
        ("Línea uno 😊\nLínea dos", "Línea uno\nLínea dos"),
    ],
)
def test_strip_emojis(raw: str, expected: str) -> None:
    assert strip_emojis(raw) == expected


def test_strip_emojis_keeps_currency_and_accents() -> None:
    raw = "Total 25,90 € (IVA incl.) ñandú ™"
    assert strip_emojis(raw) == raw


# ─── Firma de correo ─────────────────────────────────────────────────────────


def test_signature_prefers_tenant_fact() -> None:
    assert email_signature({"email_signature": "Ana · Soporte"}, "Marea SL") == "Ana · Soporte"


def test_signature_default_uses_company_name_fact() -> None:
    sig = email_signature({"company_name": "Marea Studio"}, "marea-sl")
    assert sig == "El equipo de Marea Studio"


def test_signature_falls_back_to_tenant_name() -> None:
    assert email_signature({"email_signature": "  "}, "Marea SL") == "El equipo de Marea SL"
    assert email_signature(None, "Marea SL") == "El equipo de Marea SL"


def test_signature_none_without_any_name() -> None:
    assert email_signature(None, None) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tu pedido sale hoy.\n\nSaludos,", "Tu pedido sale hoy."),
        ("Tu pedido sale hoy.\n\nSaludos,\nLucía", "Tu pedido sale hoy."),
        ("Tu pedido sale hoy.\n\nUn saludo\nEl equipo de Marea", "Tu pedido sale hoy."),
        ("Tu pedido sale hoy.\n\nAtentamente,\nAna García\n", "Tu pedido sale hoy."),
        ("Tu pedido sale hoy.\n\nSaludos cordiales, Lucía", "Tu pedido sale hoy."),
        ("Tu pedido sale hoy.\nGracias,\nMarea Studio", "Tu pedido sale hoy."),
        ("Tu pedido sale hoy.\n\nCordialmente.", "Tu pedido sale hoy."),
    ],
)
def test_trailing_signoff_removed(raw: str, expected: str) -> None:
    assert remove_trailing_signoff(raw) == expected


@pytest.mark.parametrize(
    "keep",
    [
        "Muchas gracias por tu paciencia.",
        "Te mando saludos a tu familia en el siguiente correo, mira el pedido 5.",
        "Saludos, tu pedido sale hoy y llega el 12.",
        "Hola Ana,\n\nTu pedido sale hoy.\n\nCualquier duda, aquí estamos.",
        "Gracias,\nTu pedido #1001 llega mañana 12/03.",
    ],
)
def test_trailing_signoff_is_conservative(keep: str) -> None:
    assert remove_trailing_signoff(keep) == keep


# ─── finalize_reply ──────────────────────────────────────────────────────────


def test_finalize_chat_strips_markdown_and_emojis_without_signature() -> None:
    out = finalize_reply(
        "**Hola** 😊\n- uno\n- dos", surface="chat", allow_emojis=False, signature="Equipo X"
    )
    assert out == "Hola\nuno\ndos"


def test_finalize_keeps_emojis_when_tenant_opted_in() -> None:
    out = finalize_reply("¡Gracias! 😊 **ya**", surface="chat", allow_emojis=True, signature=None)
    assert out == "¡Gracias! 😊 ya"


def test_finalize_whatsapp_has_no_markup_and_no_signature() -> None:
    out = finalize_reply(
        "*Hola* Ana, _gracias_ por escribir\n\nSaludos,\nEquipo",
        surface="whatsapp",
        allow_emojis=False,
        signature="Equipo X",
    )
    assert "*" not in out
    assert "_" not in out
    assert "Equipo X" not in out
    assert out.startswith("Hola Ana, gracias por escribir")


def test_finalize_email_appends_signature_after_removing_signoff() -> None:
    out = finalize_reply(
        "Hola Ana,\n\nTu pedido **#1001** sale hoy.\n\nSaludos,\nLucía",
        surface="email",
        allow_emojis=False,
        signature="El equipo de Marea Studio",
    )
    assert out == "Hola Ana,\n\nTu pedido #1001 sale hoy.\n\nEl equipo de Marea Studio"


def test_finalize_email_does_not_duplicate_signature_if_llm_wrote_it() -> None:
    out = finalize_reply(
        "Hola Ana,\n\nTodo listo.\n\nEl equipo de Marea Studio",
        surface="email",
        allow_emojis=False,
        signature="El equipo de Marea Studio",
    )
    assert out == "Hola Ana,\n\nTodo listo.\n\nEl equipo de Marea Studio"


def test_finalize_email_signature_is_not_normalized() -> None:
    sig = "Ana García\nSoporte Marea\nhttps://marea.com/_ayuda_"
    out = finalize_reply("Hola.", surface="email", allow_emojis=False, signature=sig)
    assert out == f"Hola.\n\n{sig}"


def test_finalize_email_without_signature_leaves_body() -> None:
    out = finalize_reply("Hola.\n\nSaludos,", surface="email", allow_emojis=False, signature=None)
    assert out == "Hola."


def test_finalize_is_idempotent_for_email() -> None:
    sig = "El equipo de Marea Studio"
    once = finalize_reply("**Hola**\n\nListo.", surface="email", allow_emojis=False, signature=sig)
    assert finalize_reply(once, surface="email", allow_emojis=False, signature=sig) == once


def test_finalize_blank_text_stays_blank() -> None:
    assert finalize_reply("  ", surface="email", allow_emojis=False, signature="X") == ""
