"""Redacta el mensaje al cliente tras aprobar/rechazar una skill L3.

Antes el endpoint de approvals le volcaba al cliente el output crudo de la skill
(slug + dict con IDs internos). Esto genera un mensaje natural y cálido para el
cliente final, vía Haiku (barato/rápido), partiendo de una plantilla limpia. Si
el cliente Anthropic no está disponible, la llamada falla o la redacción sale en otro
idioma que el de la conversación, devuelve la plantilla tal cual (fallback): nunca jerga
interna ni un idioma equivocado.

Las skills que releen el pedido tras actuar devuelven un `outcome`. Para ellas el
mensaje es una plantilla fija por resultado y no pasa por el LLM: lo que se le dice
al cliente sobre su dinero o su envío no se reescribe (issue #318).

Todas las plantillas viven en `services/fixed_texts.py`, por idioma. Cada función recibe
el idioma de la conversación y el idioma por defecto del tenant.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.api.integrations.anthropic_client import call_claude_text
from apps.api.services.fixed_texts import CATALOG, FALLBACK_LANGUAGE, LANGUAGE_CODES, fixed_text
from apps.api.services.language import LANGUAGE_NAMES, reply_language_mismatch
from apps.api.services.reply_format import strip_emojis, strip_formatting
from apps.api.services.returns import ReturnPlan
from apps.api.skills.shopify._order_guard import ActionOutcome

if TYPE_CHECKING:
    import anthropic

logger = logging.getLogger(__name__)


def _skill_key(prefix: str, skill_slug: str | None) -> str:
    """`prefix.<skill>` si el catálogo lo tiene; si no, `prefix.default`."""
    if skill_slug is not None:
        key = f"{prefix}.{skill_slug.removeprefix('shopify.')}"
        if key in CATALOG:
            return key
    return f"{prefix}.default"


def gate_message(
    skill_slug: str | None, language: str | None = None, tenant_default: str = FALLBACK_LANGUAGE
) -> str:
    """Mensaje cálido del gate L3 (acción pendiente de aprobación humana).

    Determinista (no pasa por LLM): vive dentro del grafo, lo emite el nodo escalate.
    """
    return fixed_text(_skill_key("gate", skill_slug), language, tenant_default=tenant_default)


def waiting_message(
    skill_slug: str | None, language: str | None = None, tenant_default: str = FALLBACK_LANGUAGE
) -> str:
    """Mensaje cuando el cliente pregunta de nuevo y su acción sigue pendiente.

    No repite el gate ("lo paso a mi equipo…"), que sonaría a empezar de cero.
    """
    return fixed_text(_skill_key("waiting", skill_slug), language, tenant_default=tenant_default)


def done_followup_message(
    skill_slug: str | None, language: str | None = None, tenant_default: str = FALLBACK_LANGUAGE
) -> str:
    """Mensaje cuando el cliente reescribe y su acción YA fue aprobada/aplicada.

    No dice "sigue en revisión" (contradiría el "ya está hecho" que ya recibió).
    """
    return fixed_text(
        _skill_key("done_followup", skill_slug), language, tenant_default=tenant_default
    )


def outcome_message(
    skill_slug: str,
    output: dict[str, Any],
    language: str | None = None,
    tenant_default: str = FALLBACK_LANGUAGE,
) -> str | None:
    """Mensaje fijo para una skill que devolvió `outcome`. None si no lo devolvió.

    Nunca promete que el paquete llegará a la nueva dirección ni plazos de la pasarela:
    solo lo que Shopify confirmó.
    """
    raw = output.get("outcome")
    if raw is None:
        return None
    outcome = ActionOutcome(raw)
    key = f"outcome.{skill_slug.removeprefix('shopify.')}.{outcome.value}"
    if key not in CATALOG:
        key = _skill_key("done", skill_slug) if outcome.settled else "outcome.unsettled"
    text = fixed_text(key, language, tenant_default=tenant_default)
    details = (
        action_details(skill_slug, output, language, tenant_default)
        if outcome is ActionOutcome.CONFIRMED
        else None
    )
    return f"{text}\n\n{details}" if details else text


def action_details(
    skill_slug: str,
    output: dict[str, Any] | None,
    language: str | None = None,
    tenant_default: str = FALLBACK_LANGUAGE,
) -> str | None:
    """Resumen determinista de lo que hizo la skill, para repetírselo al cliente
    (p. ej. la dirección nueva). None si no hay nada concreto que confirmar."""
    if not output:
        return None
    if skill_slug == "shopify.update_shipping_address":
        street = ", ".join(p for p in (output.get("new_address1"), output.get("new_address2")) if p)
        locality = " ".join(p for p in (output.get("new_zip"), output.get("new_city")) if p)
        address = ", ".join(p for p in (street, locality) if p)
        if not address:
            return None
        return fixed_text(
            "address_details", language, tenant_default=tenant_default, address=address
        )
    if skill_slug in _RETURN_SKILLS and output.get("plan"):
        plan = ReturnPlan.model_validate(output["plan"])
        return return_next_steps(plan, language or tenant_default, tenant_default)
    return None


_RETURN_SKILLS = frozenset({"shopify.start_return", "shopify.start_exchange"})


def _money(amount: Decimal, currency: str, language: str) -> str:
    text = f"{amount:.2f}"
    return f"{text if language == 'en' else text.replace('.', ',')} {currency}"


def return_next_steps(plan: ReturnPlan, language: str, tenant_default: str) -> str:
    """Qué pasa ahora, según la política del tenant con la que se abrió: cómo vuelve el
    paquete, quién paga el envío, la tarifa y el plazo. Nunca dice que el dinero ya vuelve."""

    def text(key: str, **params: str) -> str:
        return fixed_text(key, language, tenant_default=tenant_default, **params)

    s = plan.settlement
    steps = [
        text("returns.ship_to", address=plan.return_address)
        if plan.shipping_method == "customer_ships" and plan.return_address
        else text("returns.label")
    ]
    if s.fee_pending is not None:
        steps.append(text("returns.shipping_fee_pending"))
    elif s.fee:
        steps.append(text("returns.shipping_fee", fee=_money(s.fee, s.currency, language)))
    elif s.shipping_payer == "customer":
        steps.append(text("returns.shipping_paid_by_customer"))
    elif plan.shipping_method == "customer_ships":
        steps.append(text("returns.shipping_reimbursed"))
    else:
        steps.append(text("returns.shipping_paid_by_store"))
    if s.restocking_fee:
        fee = _money(s.restocking_fee, s.currency, language)
        steps.append(text("returns.restocking_fee", fee=fee))
    days = str(plan.refund_days)
    credit = s.refund_as == "store_credit"
    if not plan.exchange_lines:
        key = "returns.credit_after_receipt" if credit else "returns.refund_after_receipt"
        steps.append(text(key, days=days))
        return " ".join(steps)
    steps.append(
        text(
            "returns.exchange_ships_now"
            if plan.ship_replacement == "immediately"
            else "returns.exchange_ships_after_receipt"
        )
    )
    if s.price_rule == "store_absorbs":
        steps.append(text("returns.exchange_difference_absorbed"))
    elif s.price_rule == "no_refund":
        steps.append(text("returns.exchange_no_refund"))
    if s.balance is None:
        steps.append(text("returns.exchange_difference_pending"))
    elif s.balance < 0:
        owed = _money(-s.balance, s.currency, language)
        steps.append(text("returns.exchange_you_owe", amount=owed))
    elif s.balance > 0:
        amount = _money(s.balance, s.currency, language)
        key = "returns.exchange_credit" if credit else "returns.exchange_refund"
        steps.append(text(key, amount=amount, days=days))
    return " ".join(steps)


def fallback_message(
    skill_slug: str,
    *,
    success: bool,
    reject_comment: str | None = None,
    output: dict[str, Any] | None = None,
    language: str | None = None,
    tenant_default: str = FALLBACK_LANGUAGE,
) -> str:
    """Mensaje limpio determinista (base para Haiku y fallback si el LLM no está)."""
    if reject_comment is not None:
        return fixed_text(
            "rejected", language, tenant_default=tenant_default, comment=reject_comment
        )
    if not success:
        return fixed_text("failed", language, tenant_default=tenant_default)
    done = fixed_text(_skill_key("done", skill_slug), language, tenant_default=tenant_default)
    details = action_details(skill_slug, output, language, tenant_default)
    return f"{done} {details}" if details else done


def _system_prompt(language: str) -> str:
    return (
        "Eres el asistente de atención al cliente de una tienda de e-commerce. "
        "Reescribe el mensaje que te doy como una confirmación breve, cálida y natural "
        f"para el cliente final, en {LANGUAGE_NAMES.get(language, language)}. Una o dos "
        "frases. NO incluyas tecnicismos, nombres de funciones, identificadores internos "
        "ni JSON, y no inventes datos."
    )


async def generate_customer_reply(
    client: anthropic.AsyncAnthropic | None,
    skill_slug: str,
    *,
    success: bool,
    reject_comment: str | None = None,
    output: dict[str, Any] | None = None,
    timeout_seconds: int = 15,
    language: str | None = None,
    tenant_default: str = FALLBACK_LANGUAGE,
) -> str:
    """Devuelve el mensaje al cliente. Usa Haiku para darle calidez; cae a plantilla.

    Los datos concretos de la acción (p. ej. la dirección nueva) NO pasan por el
    LLM: se añaden literalmente al final, para que nunca se alteren. Si la skill
    devolvió `outcome`, el mensaje entero es la plantilla fija de ese resultado. Lo que
    redacta el LLM se verifica con el detector de idioma; si no está en el idioma de la
    conversación, se usa la plantilla fija.
    """
    language = language or tenant_default
    fixed = (
        outcome_message(skill_slug, output, language, tenant_default)
        if success and output
        else None
    )
    if fixed is not None:
        return fixed
    details = action_details(skill_slug, output, language, tenant_default) if success else None
    if client is None:
        return fallback_message(
            skill_slug,
            success=success,
            reject_comment=reject_comment,
            output=output,
            language=language,
            tenant_default=tenant_default,
        )
    base = fallback_message(
        skill_slug,
        success=success,
        reject_comment=reject_comment,
        language=language,
        tenant_default=tenant_default,
    )
    try:
        reply = await call_claude_text(
            client=client,
            role="reply_model",
            max_tokens=200,
            system=_system_prompt(language),
            messages=[{"role": "user", "content": base}],
            timeout_seconds=timeout_seconds,
        )
        warm = reply.text.strip() or base
    except Exception:
        logger.warning("approval_reply_generation_failed skill=%s", skill_slug, exc_info=True)
        warm = base
    # Lo redactado por el LLM pasa por el mismo filtro que las respuestas del agente
    # (ADR 0012); `details` son datos literales y no se tocan.
    warm = strip_emojis(strip_formatting(warm)) or base
    wrong = reply_language_mismatch(warm, language, frozenset(LANGUAGE_CODES))
    if wrong is not None:
        logger.warning(
            "approval_reply_language_mismatch skill=%s target=%s detected=%s",
            skill_slug,
            language,
            wrong,
        )
        warm = base
    return f"{warm}\n\n{details}" if details else warm
