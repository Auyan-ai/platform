"""Formato de salida para WhatsApp (integrations/zernio_format)."""

from __future__ import annotations

import pytest
from apps.api.integrations.zernio_format import to_whatsapp_messages, to_whatsapp_text


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("**Pedido #1432** enviado", "Pedido #1432 enviado"),
        ("__hola__", "hola"),
        ("es *importante*", "es importante"),
        ("es _importante_", "es importante"),
        ("# Estado del pedido\nEn camino", "Estado del pedido\nEn camino"),
        ("Mira [aquí](https://tienda.es/a?b=1)", "Mira aquí: https://tienda.es/a?b=1"),
        ("Hola<br>qué&nbsp;tal <b>ok</b>", "Hola\nqué tal ok"),
        ("- uno\n- dos", "uno\ndos"),
        ("a\n\n\n\nb", "a\n\nb"),
        ("3 * 4 = 12 y 2*3", "3 * 4 = 12 y 2*3"),
        ("**negrita** con *cursiva*", "negrita con cursiva"),
    ],
)
def test_to_whatsapp_text(source: str, expected: str) -> None:
    assert to_whatsapp_text(source) == expected


def test_messages_are_cut_by_paragraphs_under_the_limit() -> None:
    text = "\n\n".join(f"**Párrafo {i}** " + "x" * 60 for i in range(10))
    messages = to_whatsapp_messages(text, limit=200)
    assert len(messages) > 1
    assert all(len(m) <= 200 for m in messages)
    assert messages[0].startswith("Párrafo 0 x")


def test_empty_text_produces_no_messages() -> None:
    assert to_whatsapp_messages("<br>&nbsp;") == []
