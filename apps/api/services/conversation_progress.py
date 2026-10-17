"""Conversación de pedidos sin avance: el código la pasa al equipo (EX-03).

Si el cliente no da ningún pedido ni hay uno identificado tras varias respuestas del
agente, seguir pidiéndole datos solo lo frustra. La regla es determinista y corre antes
del LLM, en la primera vuelta del turno.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from apps.api.skills.registry import SkillRegistry

NO_PROGRESS_AGENT_REPLIES = 3

NO_PROGRESS_MESSAGE = (
    "Para no hacerte perder más tiempo, paso tu caso a una persona del equipo, que lo "
    "revisará y te responderá por aquí."
)

_ORDER_SCOPES = frozenset({"order", "own_orders"})


def is_order_aop(allowed_skills: Iterable[str]) -> bool:
    """El AOP trabaja sobre pedidos: alguna de sus skills toca un pedido."""
    for slug in allowed_skills:
        try:
            if SkillRegistry.get(slug).identity_scope in _ORDER_SCOPES:
                return True
        except ValueError:
            continue
    return False


def order_found_in(read_outputs: Iterable[tuple[str, Mapping[str, Any]]]) -> bool:
    """Alguna lectura de la conversación ya identificó un pedido del cliente."""
    for slug, output in read_outputs:
        try:
            scope = SkillRegistry.get(slug).identity_scope
        except ValueError:
            continue
        if scope == "order":
            # El gate de identidad solo deja correr una skill `order` con el pedido resuelto.
            return True
        if scope == "own_orders" and int(output.get("total_found") or 0) > 0:
            return True
        if output.get("verified") is True:
            return True
    return False


def agent_replies(history: Sequence[Mapping[str, Any]] | None) -> int:
    return sum(1 for m in history or () if m.get("role") == "agent_ai")


def no_progress_reason(
    *,
    allowed_skills: Iterable[str],
    history: Sequence[Mapping[str, Any]] | None,
    order_refs_given: bool,
    order_in_context: bool,
) -> str | None:
    """Motivo de escalado si la conversación de pedidos no avanza; None si avanza."""
    if order_refs_given or order_in_context:
        return None
    replies = agent_replies(history)
    if replies < NO_PROGRESS_AGENT_REPLIES or not is_order_aop(allowed_skills):
        return None
    return (
        f"no_progress: el cliente no ha dado ningún pedido ni hay uno identificado tras "
        f"{replies} respuestas del agente"
    )
