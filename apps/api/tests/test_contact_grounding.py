"""Contactos de una respuesta respaldados (o no) por la evidencia del agente (#327)."""

from __future__ import annotations

from apps.api.services.contact_grounding import Contact, contacts_in, unbacked_contacts


def test_extracts_emails_and_phones_normalized() -> None:
    text = "Escríbenos a Soporte@Tienda-Ejemplo.es o llama al 612 34 56 78."
    assert contacts_in(text, "ES") == {
        Contact("email", "soporte@tienda-ejemplo.es"),
        Contact("phone", "+34612345678"),
    }


def test_order_numbers_ids_and_dates_are_not_phones() -> None:
    text = "Pedido #1431 (id 7409804542232), entregado el 2026-09-30, total 145.90 USD."
    assert contacts_in(text, "ES") == set()


def test_store_contacts_written_differently_are_backed() -> None:
    evidence = "## Datos del cliente\n\n- Email de soporte: soporte@tienda-ejemplo.es\n- Teléfono de soporte: 612345678"
    response = "Llámanos al +34 612 34 56 78 o escribe a SOPORTE@tienda-ejemplo.es."
    assert unbacked_contacts(response, evidence, "ES") == []


def test_invented_contacts_are_unbacked() -> None:
    evidence = "- Email de soporte: soporte@tienda-ejemplo.es\n- Teléfono de soporte: 612345678"
    response = "Llama al 911 222 333 o escribe a devoluciones@tienda-ejemplo.es."
    assert unbacked_contacts(response, evidence, "ES") == [
        Contact("email", "devoluciones@tienda-ejemplo.es"),
        Contact("phone", "+34911222333"),
    ]


def test_masked_hides_the_contact() -> None:
    assert Contact("email", "devoluciones@tienda-ejemplo.es").masked() == "d***@tienda-ejemplo.es"
    assert Contact("phone", "+34911222333").masked() == "teléfono acabado en 2333"
