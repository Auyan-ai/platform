"""Normalizador de la respuesta al cliente, por superficie (código, sin LLM).

El LLM pone las palabras y el registro; el código pone el formato. Un único punto
(`finalize_reply`) se aplica justo antes de persistir y entregar la respuesta:

- Markdown, marcado de WhatsApp (`*x*`, `_x_`, `~x~`) y HTML fuera, en TODAS las superficies.
- Emojis fuera salvo opt-in del tenant (`tenant_config.extra["allow_emojis"] is True`).
- Viñetas: se quita el símbolo (`-`, `*`, `•`, `+`) y cada elemento queda en su propia
  línea. Es lo que haría una persona escribiendo en un chat o un correo sin editor de
  texto enriquecido; las listas numeradas (`1.`) se respetan tal cual.
- Email: se elimina una despedida final que el LLM haya añadido y el código añade la firma.

Nunca se tocan números, ids de pedido, emails, URLs ni importes: URLs y emails se
protegen con marcadores durante la limpieza y las listas numeradas no se reescriben.
"""

from __future__ import annotations

import html
import re
from typing import Any

from apps.api.services.writing_surface import Surface

# ─── Limpieza de formato ─────────────────────────────────────────────────────

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_AUTOLINK_URL_RE = re.compile(r"<(https?://[^>\s]+)>")
_AUTOLINK_MAIL_RE = re.compile(r"<([\w.+-]+@[\w-]+(?:\.[\w-]+)+)>")
_LINK_RE = re.compile(r"(!?)\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_URL_RE = re.compile(r"https?://[^\s<>\"]+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_FENCE_LINE_RE = re.compile(r"^\s*```[\w-]*\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_QUOTE_RE = re.compile(r"^\s{0,3}>\s?")
_HR_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_TABLE_SEP_RE = re.compile(r"^\|?[\s:|-]*-[\s:|-]*\|?$")
_BULLET_RE = re.compile(r"^\s*[-*+•]\s+")
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)
_DOUBLE_UNDERSCORE_RE = re.compile(r"__(?=\S)(.+?)(?<=\S)__", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")
_TILDE_RE = re.compile(r"(?<![\w~])~(?=\S)([^~\n]+?)(?<=\S)~(?![\w~])")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_PLACEHOLDER_RE = re.compile("\ue000(\\d+)\ue001")


def _tidy(text: str) -> str:
    out = "\n".join(line.rstrip() for line in text.split("\n"))
    return _BLANK_LINES_RE.sub("\n\n", out).strip()


def _link_to_text(match: re.Match[str]) -> str:
    is_image, label, url = match.group(1), match.group(2).strip(), match.group(3)
    if label.rstrip("/") == url.rstrip("/") or label.startswith(("http://", "https://")):
        return url
    rest = match.string[match.end() :].split("\n", 1)[0]
    if re.fullmatch(r"[.,;:!?]*\s*", rest) or is_image:
        return f"{label}: {url}"
    return f"{label} ({url})"


def _protect(text: str, store: list[str]) -> str:
    def stash(match: re.Match[str]) -> str:
        store.append(match.group(0))
        return f"\ue000{len(store) - 1}\ue001"

    return _EMAIL_RE.sub(stash, _URL_RE.sub(stash, text))


def _restore(text: str, store: list[str]) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: store[int(m.group(1))], text)


def _clean_line(line: str) -> str | None:
    """Limpieza de bloque de una línea; None = la línea desaparece."""
    if _FENCE_LINE_RE.match(line) or _HR_RE.match(line):
        return None
    stripped = line.strip()
    if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1:
        if _TABLE_SEP_RE.match(stripped):
            return None
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        return ", ".join(c for c in cells if c)
    line = line.replace("```", "")
    heading = _HEADING_RE.match(line)
    if heading:
        return heading.group(1).strip()
    line = _QUOTE_RE.sub("", line)
    return _BULLET_RE.sub("", line)


def strip_formatting(text: str) -> str:
    """Markdown, marcado de WhatsApp y HTML fuera. Idempotente."""
    out = _BR_RE.sub("\n", text)
    out = _AUTOLINK_URL_RE.sub(r"\1", out)
    out = _AUTOLINK_MAIL_RE.sub(r"\1", out)
    out = _TAG_RE.sub("", out)
    out = html.unescape(out).replace("\xa0", " ")
    out = _LINK_RE.sub(_link_to_text, out)
    store: list[str] = []
    out = _protect(out, store)
    lines = [_clean_line(line) for line in out.split("\n")]
    out = "\n".join(line for line in lines if line is not None)
    for pattern in (_BOLD_RE, _DOUBLE_UNDERSCORE_RE, _STRIKE_RE):
        out = pattern.sub(r"\1", out)
    for pattern in (_ITALIC_STAR_RE, _ITALIC_UNDERSCORE_RE, _TILDE_RE, _INLINE_CODE_RE):
        out = pattern.sub(r"\1", out)
    return _tidy(_restore(out, store))


def has_markdown(text: str) -> bool:
    """True si `strip_formatting` cambiaría el texto (queda formato por quitar)."""
    return strip_formatting(text) != _tidy(text)


# ─── Emojis ──────────────────────────────────────────────────────────────────

_EMOJI_CHARS = (
    "\U0001f000-\U0001faff"  # pictogramas, emoticonos, banderas, tonos de piel
    "\u2600-\u27bf"  # símbolos varios y dingbats (✅ ❤ ☎ ✓ ...)
    "\u2b50\u2b55\u2b05-\u2b07\u2b1b\u2b1c"
    "\u231a\u231b\u23e9-\u23fa"
    "\u2934\u2935\u3030\u303d\u3297\u3299"
)
_EMOJI_RUN_RE = re.compile(f"[ \\t]*[{_EMOJI_CHARS}\ufe0f\u200d\u20e3]+[ \\t]*")
_EMOJI_SEARCH_RE = re.compile(f"[{_EMOJI_CHARS}\u20e3]")
_NO_SPACE_BEFORE = ".,;:!?)]}"


def has_emoji(text: str) -> bool:
    return _EMOJI_SEARCH_RE.search(text) is not None


def _drop_emoji_run(match: re.Match[str]) -> str:
    before = match.string[: match.start()]
    after = match.string[match.end() :]
    has_left = bool(before) and before[-1] != "\n"
    has_right = bool(after) and after[0] != "\n" and after[0] not in _NO_SPACE_BEFORE
    return " " if has_left and has_right else ""


def strip_emojis(text: str) -> str:
    return _tidy(_EMOJI_RUN_RE.sub(_drop_emoji_run, text))


# ─── Firma de correo ─────────────────────────────────────────────────────────

_SIGNOFF_RE = re.compile(
    r"^(?:"
    r"(?:un\s+)?(?:cordial\s+)?saludo|"
    r"(?:(?:cordiales|muchos|buenos|calurosos)\s+)?saludos|"
    r"atentamente|cordialmente|un\s+abrazo|"
    r"best\s+regards|kind\s+regards|regards|sincerely"
    r")(?:\s+cordiales)?"
    r"(?:\s*,\s*(?P<name>[^\n.!?;:¡¿\d@/]{1,50}))?\s*[,.!]*$"
    r"|^(?:muchas\s+)?gracias\s*,(?:\s*(?P<gname>[^\n.!?;:¡¿\d@/]{1,50}))?$",
    re.IGNORECASE,
)
_NAME_LINE_RE = re.compile(r"^[^\W\d_][^\n,;:!?¡¿@/\d]{0,49}[^\s.,;:!?¡¿\d]$|^[^\W\d_]$")


def _is_name_line(line: str) -> bool:
    return len(line.split()) <= 5 and _NAME_LINE_RE.match(line) is not None


def remove_trailing_signoff(text: str) -> str:
    """Quita una despedida al final (con o sin nombre debajo). Conservador: solo
    despedidas típicas en una línea propia, y un nombre corto sin cifras ni puntuación."""
    lines = text.rstrip().split("\n")
    if not lines or not lines[-1].strip():
        return text.rstrip()
    last = lines[-1].strip()
    cut: int | None = None
    if _SIGNOFF_RE.match(last):
        cut = len(lines) - 1
    elif _is_name_line(last) and len(lines) >= 2 and _SIGNOFF_RE.match(lines[-2].strip()):
        cut = len(lines) - 2
    if cut is None:
        return text.rstrip()
    return "\n".join(lines[:cut]).rstrip()


def email_signature(facts: dict[str, Any] | None, tenant_name: str | None) -> str | None:
    """Firma del correo: `tenant_facts.email_signature`; si no, `El equipo de {marca}`."""
    facts = facts or {}
    custom = str(facts.get("email_signature") or "").strip()
    if custom:
        return custom
    brand = str(facts.get("company_name") or "").strip() or (tenant_name or "").strip()
    return f"El equipo de {brand}" if brand else None


def _drop_trailing_signature(body: str, signature: str) -> str:
    sig = signature.strip()
    if sig and body.casefold().endswith(sig.casefold()) and len(body) > len(sig):
        return body[: len(body) - len(sig)].rstrip()
    return body


# ─── Punto único ─────────────────────────────────────────────────────────────


def finalize_reply(
    text: str,
    *,
    surface: Surface,
    allow_emojis: bool,
    signature: str | None,
) -> str:
    """Respuesta final al cliente: formato limpio y, en email, despedida + firma del sistema."""
    body = strip_formatting(text)
    if not allow_emojis:
        body = strip_emojis(body)
    if not body or surface != "email":
        return body
    body = remove_trailing_signoff(body)
    if signature:
        body = _drop_trailing_signature(body, signature)
        return f"{body}\n\n{signature.strip()}" if body else signature.strip()
    return body
