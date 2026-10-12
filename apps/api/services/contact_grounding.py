"""Emails y teléfonos de una respuesta, y si la evidencia del agente los respalda.

La regla global del agente solo admite contactos de los datos de la tienda, la base de
conocimiento, una herramienta o el propio cliente. Que un contacto aparezca en esa
evidencia es una comprobación literal: la hace el código, no el supervisor LLM (#327).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import phonenumbers
from apps.api.services.pii import EMAIL_RE

ContactKind = Literal["email", "phone"]


@dataclass(frozen=True)
class Contact:
    kind: ContactKind
    # Email en minúsculas o teléfono en E.164.
    value: str

    def masked(self) -> str:
        if self.kind == "email":
            local, _, domain = self.value.partition("@")
            return f"{local[:1]}***@{domain}"
        return f"teléfono acabado en {self.value[-4:]}"


def contacts_in(text: str, region: str) -> set[Contact]:
    emails = {Contact("email", email.lower()) for email in EMAIL_RE.findall(text)}
    phones = {
        Contact(
            "phone",
            phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164),
        )
        for match in phonenumbers.PhoneNumberMatcher(text, region)
    }
    return emails | phones


def unbacked_contacts(response: str, evidence: str, region: str) -> list[Contact]:
    """Contactos de `response` que no aparecen en `evidence`, en orden estable."""
    unbacked = contacts_in(response, region) - contacts_in(evidence, region)
    return sorted(unbacked, key=lambda c: (c.kind, c.value))
