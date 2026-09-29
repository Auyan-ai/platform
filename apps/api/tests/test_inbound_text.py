"""Limpieza del texto entrante del cliente (casos reales del E2E en Zendesk)."""

from __future__ import annotations

from apps.api.services.inbound_text import clean_inbound_text

_SIGNATURE = (
    "Kenny Medina\n\nCustomer Service, AhoraCrypto\n\nkenny.medina@ahoracrypto.com | "
    "ahoracrypto.com\n\nC/ Gabriel Garcia Marquez 4, Planta 1, Las Rozas\n\n "
    "![AhoraCrypto](https://ahoracrypto.com/assets/logo.png)"
)


def test_cuts_rfc_signature_delimiter() -> None:
    body = f"Hola\n\n\n\n--\n\n{_SIGNATURE}"
    assert clean_inbound_text(body) == "Hola"


def test_cuts_signature_starting_with_sender_name() -> None:
    body = f"Vale, quiero anularlo, cancelalo\n\n\n\n{_SIGNATURE}"
    assert clean_inbound_text(body, sender_name="Kenny Medina") == (
        "Vale, quiero anularlo, cancelalo"
    )


def test_sender_name_in_first_line_is_kept() -> None:
    """ "Kenny Medina aquí, …" al principio no es firma."""
    body = "Kenny Medina aquí, mi pedido no llegó"
    assert clean_inbound_text(body, sender_name="Kenny Medina") == body


def test_decodes_html_entities_and_nbsp() -> None:
    assert clean_inbound_text("pedido&nbsp;1428 &amp; más\u00a0") == "pedido 1428 & más"


def test_cuts_mobile_signature() -> None:
    assert clean_inbound_text("¿Dónde está?\n\nEnviado desde mi iPhone") == "¿Dónde está?"
    assert clean_inbound_text("Where is it?\n\nSent from my iPhone") == "Where is it?"


def test_removes_markdown_images_and_collapses_blank_lines() -> None:
    body = "Mira la foto\n\n\n\n![foto](https://x/y.png)\n\nestá rota"
    assert clean_inbound_text(body) == "Mira la foto\n\nestá rota"


def test_never_returns_empty_when_there_was_text() -> None:
    """Si la heurística se lo comiera todo, se devuelve el texto sin firma-cut."""
    assert clean_inbound_text("--\nsolo esto") == "--\nsolo esto"
