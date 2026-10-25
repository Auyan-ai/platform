"""Qué skills puede usar el turno (ADR 0013 §5): tools visibles y veredicto del gate.

Puro y determinista. El LLM solo ve las skills que el tenant tiene encendidas, que la
tienda del turno sabe hacer (ADR 0016 §3) y que la identidad del turno permite; el gate de
`execute_skill` repite las comprobaciones con `capability_missing` y, sobre el pedido
concreto, con `identity_verdict`.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from apps.api.integrations.commerce import CommerceCapability
from apps.api.services.identity import ClaimHash, IdentityContext, level_at_least
from apps.api.skills.base import Skill
from apps.api.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

IdentityVerdict = Literal["identity_required", "verified_required"]


def skill_enabled(perm: dict[str, Any] | None) -> bool:
    """Encendida en `tenant_tool_permissions`. Sin fila = apagada (fail-closed)."""
    return perm is not None and bool(perm.get("is_enabled", False))


def capability_missing(
    skill_cls: type[Skill], capabilities: frozenset[CommerceCapability] | None
) -> CommerceCapability | None:
    """La capacidad que la skill necesita y el adapter del turno no tiene, o None.

    `capabilities=None` es un turno sin adapter de comercio: no falta ninguna, y la skill
    falla al ejecutar con `commerce_not_configured`."""
    need = skill_cls.required_capability
    if need is None or capabilities is None or need in capabilities:
        return None
    return need


def skill_visible(skill_cls: type[Skill], identity: IdentityContext) -> bool:
    """¿La identidad del turno basta para ofrecer la skill? `order` pide algún grant y
    `own_orders` uno `verified`."""
    if skill_cls.identity_scope == "public":
        return True
    if skill_cls.identity_scope == "own_orders":
        return identity.has_grant("verified")
    return identity.has_grant()


def visible_skills(
    slugs: list[str],
    tool_permissions: dict[str, Any],
    identity: IdentityContext,
    *,
    capabilities: frozenset[CommerceCapability] | None = None,
) -> list[str]:
    """Las `slugs` del AOP que el LLM puede ver: encendidas, registradas, que la tienda
    sabe hacer y permitidas por la identidad. Conserva el orden. `capabilities` son las del
    adapter de comercio del turno (None = sin comercio). Con comercio, suma las skills
    `core` del sistema (la de respaldo del nivel `guest`) solo si el AOP ofrece alguna
    skill de pedido y el turno aún no tiene ningún grant: en el resto de turnos no
    aparece."""
    visible: list[str] = []
    has_order_skill = False
    for slug in slugs:
        if not skill_enabled(tool_permissions.get(slug)):
            continue
        try:
            skill_cls = SkillRegistry.get(slug)
        except ValueError:
            logger.warning("allowed_skill_not_in_registry: %s", slug)
            continue
        if capability_missing(skill_cls, capabilities) is not None:
            continue
        has_order_skill = has_order_skill or skill_cls.identity_scope == "order"
        if skill_visible(skill_cls, identity):
            visible.append(slug)
    if capabilities is not None and has_order_skill and not identity.has_grant():
        visible.extend(
            s
            for s in SkillRegistry.core_slugs()
            if s not in visible and capability_missing(SkillRegistry.get(s), capabilities) is None
        )
    return visible


def identity_verdict(
    skill_cls: type[Skill],
    identity: IdentityContext,
    *,
    claims: frozenset[ClaimHash] | None,
    order_id: int | None,
) -> IdentityVerdict | None:
    """Veredicto del gate para una skill sobre un pedido. None = puede ejecutar.

    `claims=None` es un pedido que no se resolvió: fail-closed.
    """
    if skill_cls.identity_scope == "public":
        return None
    if skill_cls.identity_scope == "own_orders":
        return None if identity.has_grant("verified") else "identity_required"
    if claims is None:
        return "identity_required"
    level = identity.level_for(claims, order_id)
    if level is None:
        return "identity_required"
    return None if level_at_least(level, skill_cls.min_level) else "verified_required"
