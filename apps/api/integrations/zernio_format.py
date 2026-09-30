"""Formato de salida para WhatsApp: Markdown del agente → marcado de WhatsApp + cortes.

Determinista (sin LLM). WhatsApp entiende `*negrita*`, `_cursiva_`, `~tachado~` y
```monoespaciado```; no entiende encabezados, enlaces Markdown ni HTML.

    **x**            → *x*
    __x__ / *x*      → _x_   (cursiva de WhatsApp)
    # Título         → *Título*
    [texto](url)     → texto: url
    HTML / &nbsp;    → fuera
"""

from __future__ import annotations

import html
import re

from apps.api.integrations.zernio import WHATSAPP_MAX_CHARS, split_for_whatsapp

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_DOUBLE_UNDERSCORE_RE = re.compile(r"__(.+?)__", re.DOTALL)
# Cursiva Markdown con un solo asterisco (no pegado a otro asterisco).
_ITALIC_STAR_RE = re.compile(r"(?<![\*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\*\w])")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+", re.MULTILINE)
_BLANK_LINES_RE = re.compile(r"\n{3,}")
# Marcador interno para la negrita ya convertida (evita que la cursiva la reprocese).
_BOLD_MARK = "\x00"


def to_whatsapp_text(text: str) -> str:
    """Convierte el Markdown/HTML del agente al marcado de WhatsApp (sin cortar)."""
    out = _BR_RE.sub("\n", text)
    out = _TAG_RE.sub("", out)
    out = html.unescape(out).replace("\xa0", " ")
    out = _LINK_RE.sub(lambda m: f"{m.group(1)}: {m.group(2)}", out)
    out = _BULLET_RE.sub(lambda m: f"{m.group(1)}• ", out)
    out = _HEADING_RE.sub(lambda m: f"{_BOLD_MARK}{m.group(1).strip()}{_BOLD_MARK}", out)
    out = _BOLD_RE.sub(lambda m: f"{_BOLD_MARK}{m.group(1)}{_BOLD_MARK}", out)
    out = _DOUBLE_UNDERSCORE_RE.sub(lambda m: f"_{m.group(1)}_", out)
    out = _ITALIC_STAR_RE.sub(lambda m: f"_{m.group(1)}_", out)
    out = out.replace(_BOLD_MARK, "*")
    out = "\n".join(line.rstrip() for line in out.split("\n"))
    return _BLANK_LINES_RE.sub("\n\n", out).strip()


def to_whatsapp_messages(text: str, limit: int = WHATSAPP_MAX_CHARS) -> list[str]:
    """Texto formateado para WhatsApp y partido en mensajes de ≤`limit` caracteres."""
    return split_for_whatsapp(to_whatsapp_text(text), limit)
