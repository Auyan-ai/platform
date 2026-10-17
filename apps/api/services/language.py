"""Idioma de la conversación, decidido en código (lingua), nunca por el LLM.

El idioma es un dato de la conversación (`conversations.language`), como el
`active_language` de Zendesk: se fija con la primera detección fiable y solo cambia si
el cliente escribe claramente en otro idioma. El tenant elige su idioma por defecto y
los que soporta en `tenant_configurations.extra.languages`:

    {"default": "es", "supported": ["es", "en", "ca"]}

El agente recibe el idioma como una línea de control del turno y la respuesta se
verifica con el mismo detector antes de entregarla.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

if TYPE_CHECKING:
    from uuid import UUID

    import asyncpg

LANGUAGES: dict[str, Language] = {
    "es": Language.SPANISH,
    "en": Language.ENGLISH,
    "ca": Language.CATALAN,
    "fr": Language.FRENCH,
    "pt": Language.PORTUGUESE,
    "de": Language.GERMAN,
    "it": Language.ITALIAN,
}
# Cómo se nombra cada idioma en la línea de control (el prompt de plataforma es español).
LANGUAGE_NAMES: dict[str, str] = {
    "es": "español",
    "en": "inglés",
    "ca": "catalán",
    "fr": "francés",
    "pt": "portugués",
    "de": "alemán",
    "it": "italiano",
}
DEFAULT_LANGUAGE = "es"

# Un mensaje cuenta si el idioma ganador saca este margen al segundo ("ok" no lo saca).
MIN_MARGIN = 0.15
MIN_WORDS = 2
# Para cambiar el idioma ya fijado hace falta un mensaje con algo más de texto.
MIN_WORDS_TO_SWITCH = 3

_NOISE = re.compile(
    r"https?://\S+|www\.\S+|\S+@\S+|\S*\d\S*|[^\w\s'\u2019]",
    re.UNICODE,
)


def tenant_languages(config_extra: Mapping[str, Any] | None) -> tuple[str, frozenset[str]]:
    """(idioma por defecto, idiomas soportados) del tenant; el defecto siempre soportado."""
    raw = (config_extra or {}).get("languages") or {}
    default = raw.get("default") if raw.get("default") in LANGUAGES else DEFAULT_LANGUAGE
    supported = {code for code in raw.get("supported") or LANGUAGES if code in LANGUAGES}
    return default, frozenset(supported | {default})


@lru_cache(maxsize=32)
def _detector(codes: frozenset[str]) -> LanguageDetector:
    languages = [LANGUAGES[c] for c in sorted(codes)]
    if len(languages) == 1:
        # lingua exige al menos dos idiomas; el inglés solo sirve de contraste.
        languages.append(Language.ENGLISH if languages[0] != Language.ENGLISH else Language.SPANISH)
    return LanguageDetectorBuilder.from_languages(*languages).build()


def _words(text: str) -> list[str]:
    return _NOISE.sub(" ", text).split()


def detect(text: str, supported: Iterable[str]) -> str | None:
    """Código ISO del idioma de `text` entre `supported`, o None si no es fiable."""
    words = _words(text)
    if len(words) < MIN_WORDS:
        return None
    codes = frozenset(set(supported) & LANGUAGES.keys())
    if not codes:
        return None
    values = _detector(codes).compute_language_confidence_values(" ".join(words))
    if not values:
        return None
    top = values[0]
    second = values[1].value if len(values) > 1 else 0.0
    if top.value - second < MIN_MARGIN:
        return None
    code = top.language.iso_code_639_1.name.lower()
    return code if code in codes else None


def conversation_language(
    current: str | None,
    customer_messages: Sequence[str],
    *,
    default: str,
    supported: frozenset[str],
) -> str:
    """Idioma con el que se responde este turno.

    `customer_messages`: los mensajes del cliente aún sin respuesta, el último al final.
    Sin idioma fijado, vale la primera detección fiable (o el defecto del tenant). Con
    idioma fijado, solo cambia si el último mensaje con texto suficiente es claramente
    de otro idioma soportado.
    """
    if current not in supported:
        current = None
    if current is None:
        for text in customer_messages:
            detected = detect(text, supported)
            if detected is not None:
                return detected
        return default
    for text in reversed(customer_messages):
        if len(_words(text)) < MIN_WORDS_TO_SWITCH:
            continue
        detected = detect(text, supported)
        if detected is not None:
            return detected
        break
    return current


def reply_language_mismatch(text: str, target: str, supported: frozenset[str]) -> str | None:
    """Idioma detectado de una respuesta si NO es `target`; None si coincide o no se sabe."""
    detected = detect(text, supported | {target})
    return detected if detected is not None and detected != target else None


def state_languages(state: Mapping[str, Any]) -> tuple[str, str]:
    """(idioma de la conversación, idioma por defecto del tenant) dentro del grafo.

    `load_conversation` fija `response_language`; si falta (nodo que no corrió), el
    idioma por defecto del tenant.
    """
    default, _ = tenant_languages((state.get("tenant_config") or {}).get("extra"))
    return state.get("response_language") or default, default


async def conversation_text_languages(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    conversation_id: UUID,
    config_extra: Mapping[str, Any] | None,
) -> tuple[str, str]:
    """(idioma, defecto del tenant) para un texto fijo fuera del grafo.

    El idioma es el fijado en `conversations.language`; sin él, el defecto del tenant.
    """
    from apps.api.db.queries import get_conversation_language

    default, _ = tenant_languages(config_extra)
    language = await get_conversation_language(conn, tenant_id, conversation_id)
    return language or default, default


def response_language_block(code: str) -> str:
    """Línea de control del turno: va en el bloque volátil, lo último antes de generar."""
    return f"## Idioma de la respuesta\n\nEscribe al cliente en {LANGUAGE_NAMES[code]} ({code})."
