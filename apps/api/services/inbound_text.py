"""Limpieza del texto entrante del cliente antes de que llegue al grafo.

Los helpdesks entregan el cuerpo del email tal cual: entidades HTML (`&nbsp;`),
firmas corporativas con dirección, logos y avisos legales, "Enviado desde mi
iPhone"… Todo eso gasta tokens, mete ruido (y PII de terceros) en el contexto
del LLM y en los traces. Heurísticas conservadoras: si la limpieza dejara el
mensaje vacío, se devuelve el texto sin recortar firma.
"""

from __future__ import annotations

import html
import re

_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_SIGNATURE_DELIMITER = re.compile(r"^\s*--\s*$")
_MOBILE_SIGNATURE = re.compile(
    r"^\s*(enviado desde mi|sent from my|get outlook for)\b", re.IGNORECASE
)
_BLANK_RUNS = re.compile(r"\n{3,}")


def _normalize(text: str) -> str:
    text = html.unescape(text).replace("\u00a0", " ")
    text = _MARKDOWN_IMAGE.sub("", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return _BLANK_RUNS.sub("\n\n", "\n".join(lines)).strip()


def _cut_signature(text: str, sender_name: str | None) -> str:
    lines = text.splitlines()
    name = (sender_name or "").strip().casefold()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if _SIGNATURE_DELIMITER.match(line) or _MOBILE_SIGNATURE.match(line):
            return "\n".join(lines[:idx])
        # Firma que empieza con el nombre del remitente en su propia línea (no la
        # primera: "Kenny Medina aquí, …" al inicio es contenido).
        if idx > 0 and name and stripped.casefold() == name:
            return "\n".join(lines[:idx])
    return text


def clean_inbound_text(text: str, *, sender_name: str | None = None) -> str:
    """Texto del cliente sin entidades HTML, imágenes, firma ni líneas en blanco extra."""
    normalized = _normalize(text)
    cut = _cut_signature(normalized, sender_name).strip()
    return _BLANK_RUNS.sub("\n\n", cut) if cut else normalized
