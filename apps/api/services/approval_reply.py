"""Redacta el mensaje al cliente tras aprobar/rechazar una skill L3.

Antes el endpoint de approvals le volcaba al cliente el output crudo de la skill
(slug + dict con IDs internos). Esto genera un mensaje natural y cálido para el
cliente final, vía Haiku (barato/rápido), partiendo de una plantilla limpia. Si
el cliente Anthropic no está disponible o la llamada falla, devuelve la plantilla
tal cual (fallback) — nunca jerga interna.

Las skills que releen el pedido tras actuar devuelven un `outcome`. Para ellas el
mensaje es una plantilla fija por resultado y no pasa por el LLM: lo que se le dice
al cliente sobre su dinero o su envío no se reescribe (issue #318).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.api.core.config import get_models
from apps.api.services.reply_format import strip_emojis, strip_formatting
from apps.api.skills.shopify._order_guard import ActionOutcome

if TYPE_CHECKING:
    import anthropic

logger = logging.getLogger(__name__)

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
        "Lo paso a mi equipo para una última comprobación y te confirmo en cuanto esté hecho."
    ),
    "shopify.cancel_order": (
        "Entendido. Voy a tramitar la cancelación de tu pedido; lo paso a mi equipo "
        "para confirmarlo y te aviso en cuanto esté listo."
    ),
    "shopify.refund_partial": (
        "¡Perfecto! Estoy gestionando el reembolso de tu pedido; lo paso a mi equipo "
        "para confirmarlo y te aviso en cuanto esté hecho."
    ),
    "shopify.start_return": (
        "¡Listo! Voy a iniciar la devolución de tu pedido; lo paso a mi equipo para "
        "confirmarlo y te aviso en cuanto esté en marcha."
    ),
}
_DEFAULT_GATE = (
    "¡Perfecto! Ya tengo lo que necesito. Lo paso a mi equipo para una última "
    "comprobación y te confirmo en cuanto esté listo."
)


def gate_message(skill_slug: str | None) -> str:
    """Mensaje cálido del gate L3 (acción pendiente de aprobación humana)."""
    if skill_slug is None:
        return _DEFAULT_GATE
    return _SKILL_GATE.get(skill_slug, _DEFAULT_GATE)


# Mensaje de espera: el cliente vuelve a escribir mientras su acción sigue en
# revisión. No repetimos el gate ("lo paso a mi equipo…"), que sonaría a empezar
# de cero; reconocemos que ya está en marcha.
_SKILL_WAITING: dict[str, str] = {
    "shopify.update_shipping_address": (
        "Tu cambio de dirección sigue en revisión con mi equipo; te confirmo en "
        "cuanto esté hecho. ¡Gracias por la paciencia!"
    ),
    "shopify.cancel_order": (
        "Tu cancelación sigue en revisión con mi equipo; te aviso en cuanto esté "
        "lista. ¡Gracias por la paciencia!"
    ),
    "shopify.refund_partial": (
        "Tu reembolso sigue en revisión con mi equipo; te aviso en cuanto esté "
        "hecho. ¡Gracias por la paciencia!"
    ),
    "shopify.start_return": (
        "Tu devolución sigue en revisión con mi equipo; te aviso en cuanto esté en "
        "marcha. ¡Gracias por la paciencia!"
    ),
}
_DEFAULT_WAITING = (
    "Tu solicitud sigue en revisión con mi equipo; te confirmo en cuanto esté "
    "lista. ¡Gracias por la paciencia!"
)


def waiting_message(skill_slug: str | None) -> str:
    """Mensaje cuando el cliente pregunta de nuevo y su acción sigue pendiente."""
    if skill_slug is None:
        return _DEFAULT_WAITING
    return _SKILL_WAITING.get(skill_slug, _DEFAULT_WAITING)


# Seguimiento cuando la acción YA fue aprobada/aplicada y el cliente vuelve a
# escribir (agradece, etc.). No decir "sigue en revisión" (contradiría el "ya está
# hecho" que el cliente ya recibió): confirmar que está aplicado y ofrecer ayuda.
_SKILL_DONE_FOLLOWUP: dict[str, str] = {
    "shopify.update_shipping_address": (
        "Tu cambio de dirección ya quedó aplicado. Si necesitas algo más, aquí estoy."
    ),
    "shopify.cancel_order": (
        "Tu cancelación ya quedó registrada. Si necesitas algo más, aquí estoy."
    ),
    "shopify.refund_partial": (
        "Tu reembolso ya quedó procesado. Si necesitas algo más, aquí estoy."
    ),
    "shopify.start_return": (
        "Tu devolución ya quedó en marcha. Si necesitas algo más, aquí estoy."
    ),
}
_DEFAULT_DONE_FOLLOWUP = "Tu solicitud ya quedó completada. Si necesitas algo más, aquí estoy."


def done_followup_message(skill_slug: str | None) -> str:
    """Mensaje cuando el cliente reescribe y su acción YA fue aprobada/aplicada."""
    if skill_slug is None:
        return _DEFAULT_DONE_FOLLOWUP
    return _SKILL_DONE_FOLLOWUP.get(skill_slug, _DEFAULT_DONE_FOLLOWUP)


_TEAM_WILL_WRITE = "Nuestro equipo ya está avisado y te escribirá en cuanto lo tenga resuelto."

# Mensaje por (skill, resultado). Nunca promete que el paquete llegará a la nueva
# dirección ni plazos de la pasarela: solo lo que Shopify confirmó.
_OUTCOME_REPLY: dict[tuple[str, ActionOutcome], str] = {
    ("shopify.update_shipping_address", ActionOutcome.CONFIRMED): (
        "Hemos actualizado la dirección de envío de tu pedido."
    ),
    ("shopify.update_shipping_address", ActionOutcome.NOT_CONFIRMED): (
        "No hemos podido confirmar el cambio de dirección de tu pedido. " + _TEAM_WILL_WRITE
    ),
    ("shopify.cancel_order", ActionOutcome.CONFIRMED): (
        "Hemos cancelado tu pedido y el reembolso ya está emitido a tu método de pago "
        "original. Según tu banco, puede tardar unos días en verse en tu cuenta."
    ),
    ("shopify.cancel_order", ActionOutcome.REFUND_PENDING): (
        "Hemos cancelado tu pedido. El reembolso a tu método de pago original está en "
        "proceso con la pasarela de pago."
    ),
    ("shopify.cancel_order", ActionOutcome.REFUND_MANUAL): (
        "Hemos cancelado tu pedido. Si ya realizaste el pago, la tienda te devolverá el "
        "importe por el mismo medio con el que pagaste. " + _TEAM_WILL_WRITE
    ),
    ("shopify.cancel_order", ActionOutcome.REFUND_FAILED): (
        "Hemos cancelado tu pedido, pero el reembolso no se ha podido completar de forma "
        "automática. " + _TEAM_WILL_WRITE
    ),
    ("shopify.cancel_order", ActionOutcome.NOT_CONFIRMED): (
        "No hemos podido confirmar la cancelación de tu pedido. " + _TEAM_WILL_WRITE
    ),
    ("shopify.refund_partial", ActionOutcome.CONFIRMED): (
        "Hemos emitido el reembolso a tu método de pago original. Según tu banco, puede "
        "tardar unos días en verse en tu cuenta."
    ),
    ("shopify.refund_partial", ActionOutcome.REFUND_PENDING): (
        "El reembolso a tu método de pago original está en proceso con la pasarela de pago."
    ),
    ("shopify.refund_partial", ActionOutcome.REFUND_MANUAL): (
        "La tienda te devolverá el importe por el mismo medio con el que pagaste. "
        + _TEAM_WILL_WRITE
    ),
    ("shopify.refund_partial", ActionOutcome.REFUND_FAILED): (
        "No hemos podido completar el reembolso de forma automática. " + _TEAM_WILL_WRITE
    ),
}
_OUTCOME_UNSETTLED_DEFAULT = (
    "No hemos podido confirmar que tu solicitud quedara completada. " + _TEAM_WILL_WRITE
)


def outcome_message(skill_slug: str, output: dict[str, Any]) -> str | None:
    """Mensaje fijo para una skill que devolvió `outcome`. None si no lo devolvió."""
    raw = output.get("outcome")
    if raw is None:
        return None
    outcome = ActionOutcome(raw)
    default = (
        _SKILL_DONE.get(skill_slug, _DEFAULT_DONE)
        if outcome.settled
        else _OUTCOME_UNSETTLED_DEFAULT
    )
    text = _OUTCOME_REPLY.get((skill_slug, outcome), default)
    details = action_details(skill_slug, output) if outcome is ActionOutcome.CONFIRMED else None
    return f"{text}\n\n{details}" if details else text


_SYSTEM = (
    "Eres el asistente de atención al cliente de una tienda de e-commerce. "
    "Reescribe el mensaje que te doy como una confirmación breve, cálida y natural "
    "para el cliente final, en español. Una o dos frases. NO incluyas tecnicismos, "
    "nombres de funciones, identificadores internos ni JSON, y no inventes datos."
)


def action_details(skill_slug: str, output: dict[str, Any] | None) -> str | None:
    """Resumen determinista de lo que hizo la skill, para repetírselo al cliente
    (p. ej. la dirección nueva). None si no hay nada concreto que confirmar."""
    if not output:
        return None
    if skill_slug == "shopify.update_shipping_address":
        street = ", ".join(p for p in (output.get("new_address1"), output.get("new_address2")) if p)
        locality = " ".join(p for p in (output.get("new_zip"), output.get("new_city")) if p)
        address = ", ".join(p for p in (street, locality) if p)
        return f"Nueva dirección de envío: {address}." if address else None
    return None


def fallback_message(
    skill_slug: str,
    *,
    success: bool,
    reject_comment: str | None = None,
    output: dict[str, Any] | None = None,
) -> str:
    """Mensaje limpio determinista (base para Haiku y fallback si el LLM no está)."""
    if reject_comment is not None:
        return (
            "Hemos revisado tu solicitud y, por el momento, no podremos realizarla. "
            f"{reject_comment}"
        )
    if not success:
        return _FAILED
    done = _SKILL_DONE.get(skill_slug, _DEFAULT_DONE)
    details = action_details(skill_slug, output)
    return f"{done} {details}" if details else done


async def generate_customer_reply(
    client: anthropic.AsyncAnthropic | None,
    skill_slug: str,
    *,
    success: bool,
    reject_comment: str | None = None,
    output: dict[str, Any] | None = None,
    timeout_seconds: int = 15,
) -> str:
    """Devuelve el mensaje al cliente. Usa Haiku para darle calidez; cae a plantilla.

    Los datos concretos de la acción (p. ej. la dirección nueva) NO pasan por el
    LLM: se añaden literalmente al final, para que nunca se alteren. Si la skill
    devolvió `outcome`, el mensaje entero es la plantilla fija de ese resultado.
    """
    fixed = outcome_message(skill_slug, output) if success and output else None
    if fixed is not None:
        return fixed
    details = action_details(skill_slug, output) if success else None
    if client is None:
        return fallback_message(
            skill_slug, success=success, reject_comment=reject_comment, output=output
        )
    base = fallback_message(skill_slug, success=success, reject_comment=reject_comment)
    try:
        resp = await client.messages.create(
            model=get_models().reply_model,
            max_tokens=200,
            system=_SYSTEM,
            messages=[{"role": "user", "content": base}],
            timeout=timeout_seconds,
        )
        warm = next(
            (
                block.text.strip()
                for block in resp.content
                if getattr(block, "type", None) == "text" and block.text.strip()
            ),
            base,
        )
    except Exception:
        logger.warning("approval_reply_generation_failed skill=%s", skill_slug, exc_info=True)
        warm = base
    # Lo redactado por el LLM pasa por el mismo filtro que las respuestas del agente
    # (ADR 0012); `details` son datos literales y no se tocan.
    warm = strip_emojis(strip_formatting(warm)) or base
    return f"{warm}\n\n{details}" if details else warm
