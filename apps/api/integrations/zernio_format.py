"""Formato de salida para WhatsApp: texto plano + cortes.

Determinista (sin LLM). El agente escribe en prosa natural: nada de Markdown ni del
marcado de WhatsApp (`*negrita*`, `_cursiva_`, `~tachado~`, monoespaciado). Si algo se
cuela, se quita en vez de convertirse (ADR 0012). La limpieza es la misma que aplica el
nodo antes de persistir (`services.reply_format.strip_formatting`), así que aquí es
idempotente.

    **x** / *x* / _x_   → x
    # Título            → Título
    [texto](url)        → texto: url  (o `texto (url)` a mitad de frase)
    - elemento          → elemento
    HTML / &nbsp;       → fuera
"""

from __future__ import annotations

from apps.api.integrations.zernio import WHATSAPP_MAX_CHARS, split_for_whatsapp
from apps.api.services.reply_format import strip_formatting


def to_whatsapp_text(text: str) -> str:
    """Texto plano para WhatsApp (sin cortar)."""
    return strip_formatting(text)


def to_whatsapp_messages(text: str, limit: int = WHATSAPP_MAX_CHARS) -> list[str]:
    """Texto plano para WhatsApp, partido en mensajes de ≤`limit` caracteres."""
    return split_for_whatsapp(to_whatsapp_text(text), limit)
