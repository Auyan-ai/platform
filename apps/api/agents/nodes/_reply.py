"""Punto único donde la respuesta del agente se normaliza antes de persistirse y entregarse.

Lo llaman los dos nodos que persisten el mensaje al cliente (`respond` y `escalate`).
Su salida vuelve al state como `agent_response`, así que lo que se guarda en `messages`
es exactamente lo que recibe el cliente. Ver `services/reply_format.py`.
"""

from __future__ import annotations

from apps.api.agents.state import AgentState
from apps.api.services.reply_format import email_signature, finalize_reply
from apps.api.services.writing_surface import Surface, resolve_surface


def surface_of(state: AgentState) -> Surface:
    return resolve_surface(state.get("channel") or "chat", state.get("conversation_history"))


def finalize_agent_reply(state: AgentState, text: str) -> tuple[str, Surface]:
    """(texto final, superficie). Emojis solo con `tenant_config.extra.allow_emojis is True`."""
    surface = surface_of(state)
    extra = (state.get("tenant_config") or {}).get("extra") or {}
    signature = (
        email_signature(state.get("tenant_facts"), state.get("tenant_name"))
        if surface == "email"
        else None
    )
    final = finalize_reply(
        text,
        surface=surface,
        allow_emojis=extra.get("allow_emojis") is True,
        signature=signature,
    )
    return final, surface
