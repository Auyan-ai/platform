"""Superficie de escritura de una conversación: `chat | whatsapp | email`.

Código determinista (sin LLM). La superficie decide el formato de la respuesta (firma de
correo, longitud, registro); la voz de marca del tenant no se toca.

- `whatsapp` → WhatsApp (Zernio); `chat`/`widget`/`instagram`/`intercom` → chat.
- `email` → canal email.
- Helpdesk (zendesk/gorgias/chatwoot): depende del origen del ticket. El intake guarda el
  campo de origen del proveedor en `messages.metadata.source_channel` (Zendesk
  `via.channel`, Gorgias `message.channel`, Chatwoot `conversation.channel`), y aquí se
  lee el del último mensaje del cliente. Origen desconocido o ausente → `email`, el
  registro más seguro (un saludo y una firma de más no rompen nada; un tuteo cortado en
  un correo sí se nota).
"""

from __future__ import annotations

from typing import Any, Literal

Surface = Literal["chat", "whatsapp", "email"]

HELPDESK_CHANNELS = frozenset({"zendesk", "gorgias", "chatwoot"})
_CHAT_CHANNELS = frozenset({"chat", "widget", "instagram", "intercom"})

# Orígenes de ticket, normalizados (minúsculas, sin `Channel::`, sin `-`/`_`/espacios).
_CHAT_SOURCES = frozenset(
    {
        "chat",
        "nativemessaging",
        "messaging",
        "webwidget",
        "widget",
        "mobilesdk",
        "whatsapp",
        "facebook",
        "facebookmessenger",
        "facebookpage",
        "messenger",
        "instagram",
        "instagramdirectmessage",
        "instagramdm",
        "instagramcomment",
        "sms",
        "twiliosms",
        "twitter",
        "twitterprofile",
        "telegram",
        "line",
        "wechat",
    }
)


def _normalize_source(raw: str) -> str:
    token = raw.strip().lower().removeprefix("channel::")
    return "".join(ch for ch in token if ch not in "-_ ")


def surface_for_source(raw: str | None) -> Surface:
    """Superficie de un origen de ticket del helpdesk. Desconocido → `email`."""
    if not raw:
        return "email"
    token = _normalize_source(raw)
    if token in _CHAT_SOURCES:
        return "chat"
    return "email"


def _latest_customer_source(history: list[dict[str, Any]] | None) -> str | None:
    for message in reversed(history or []):
        if message.get("role") != "customer":
            continue
        source = (message.get("metadata") or {}).get("source_channel")
        if source:
            return str(source)
    return None


def resolve_surface(channel: str, history: list[dict[str, Any]] | None = None) -> Surface:
    """Superficie de escritura de la conversación.

    `history` es el historial del state (dicts de `Message` con `role` y `metadata`)."""
    if channel == "whatsapp":
        return "whatsapp"
    if channel in _CHAT_CHANNELS:
        return "chat"
    if channel in HELPDESK_CHANNELS:
        return surface_for_source(_latest_customer_source(history))
    return "email"
