"""Redacta el mensaje al cliente tras aprobar/rechazar una skill L3.

Antes el endpoint de approvals le volcaba al cliente el output crudo de la skill
(slug + dict con IDs internos). Esto genera un mensaje natural y cálido para el
cliente final, vía Haiku (barato/rápido), partiendo de una plantilla limpia. Si
el cliente Anthropic no está disponible o la llamada falla, devuelve la plantilla
tal cual (fallback) — nunca jerga interna.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import anthropic

logger = logging.getLogger(__name__)

# Modelo barato/rápido para reescribir una frase de confirmación.
REPLY_MODEL = "claude-haiku-4-5-20251001"

# Confirmación limpia por skill (sirve de base para Haiku y de fallback).
_SKILL_DONE: dict[str, str] = {
    "shopify.update_shipping_address": "Hemos actualizado la dirección de envío de tu pedido.",
    "shopify.cancel_order": "Hemos cancelado tu pedido.",
    "shopify.refund_partial": "Hemos procesado el reembolso de tu pedido.",
    "shopify.start_return": "Hemos iniciado la devolución de tu pedido.",
}
_DEFAULT_DONE = "Hemos completado tu solicitud."
_FAILED = (
    "Lo sentimos, no hemos podido completar tu solicitud en este momento. "
    "Un agente de nuestro equipo lo revisará y te contactará en breve."
)

# Mensaje del "gate" L3: el agente recogió todo lo que necesita y la acción queda
# pendiente de una última comprobación humana. Cálido y contextual por skill, para
# no romper el tono de la conversación con una plantilla fría. Determinista (no
# pasa por LLM): vive dentro del grafo, lo emite el nodo escalate.
_SKILL_GATE: dict[str, str] = {
    "shopify.update_shipping_address": (
        "¡Genial! Ya tengo todos los datos para cambiar la dirección de tu pedido. "
        "Lo paso a mi equipo para una última comprobación y te confirmo en cuanto esté hecho. 😊"
    ),
    "shopify.cancel_order": (
        "Entendido. Voy a tramitar la cancelación de tu pedido; lo paso a mi equipo "
        "para confirmarlo y te aviso en cuanto esté listo. 😊"
    ),
    "shopify.refund_partial": (
        "¡Perfecto! Estoy gestionando el reembolso de tu pedido; lo paso a mi equipo "
        "para confirmarlo y te aviso en cuanto esté hecho. 😊"
    ),
    "shopify.start_return": (
        "¡Listo! Voy a iniciar la devolución de tu pedido; lo paso a mi equipo para "
        "confirmarlo y te aviso en cuanto esté en marcha. 😊"
    ),
}
_DEFAULT_GATE = (
    "¡Perfecto! Ya tengo lo que necesito. Lo paso a mi equipo para una última "
    "comprobación y te confirmo en cuanto esté listo. 😊"
)


def gate_message(skill_slug: str | None) -> str:
    """Mensaje cálido del gate L3 (acción pendiente de aprobación humana)."""
    if skill_slug is None:
        return _DEFAULT_GATE
    return _SKILL_GATE.get(skill_slug, _DEFAULT_GATE)

_SYSTEM = (
    "Eres el asistente de atención al cliente de una tienda de e-commerce. "
    "Reescribe el mensaje que te doy como una confirmación breve, cálida y natural "
    "para el cliente final, en español. Una o dos frases. NO incluyas tecnicismos, "
    "nombres de funciones, identificadores internos ni JSON, y no inventes datos."
)


def fallback_message(skill_slug: str, *, success: bool, reject_comment: str | None = None) -> str:
    """Mensaje limpio determinista (base para Haiku y fallback si el LLM no está)."""
    if reject_comment is not None:
        return (
            "Hemos revisado tu solicitud y, por el momento, no podremos realizarla. "
            f"{reject_comment}"
        )
    if not success:
        return _FAILED
    return _SKILL_DONE.get(skill_slug, _DEFAULT_DONE)


async def generate_customer_reply(
    client: anthropic.AsyncAnthropic | None,
    skill_slug: str,
    *,
    success: bool,
    reject_comment: str | None = None,
    model: str = REPLY_MODEL,
    timeout_seconds: int = 15,
) -> str:
    """Devuelve el mensaje al cliente. Usa Haiku para darle calidez; cae a plantilla."""
    base = fallback_message(skill_slug, success=success, reject_comment=reject_comment)
    if client is None:
        return base
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=200,
            system=_SYSTEM,
            messages=[{"role": "user", "content": base}],
            timeout=timeout_seconds,
        )
        for block in resp.content:
            if getattr(block, "type", None) == "text" and block.text.strip():
                return block.text.strip()
        return base
    except Exception:
        logger.warning("approval_reply_generation_failed skill=%s", skill_slug, exc_info=True)
        return base
