"""Qué skills puede usar el turno (ADR 0013 §5): tools visibles y veredicto del gate.

Puro y determinista. El LLM solo ve las skills que el tenant tiene encendidas y que la
identidad del turno permite; el gate de `execute_skill` repite la comprobación sobre el
pedido concreto con `identity_verdict`.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from apps.api.services.identity import ClaimHash, IdentityContext, level_at_least
from apps.api.skills.base import Skill
from apps.api.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

IdentityVerdict = Literal["identity_required", "verified_required"]


def skill_enabled(perm: dict[str, Any] | None) -> bool:
    """Encendida en `tenant_tool_permissions`. Sin fila = apagada (fail-closed)."""
    return perm is not None and bool(perm.get("is_enabled", False))


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
    commerce: bool = False,
) -> list[str]:
    """Las `slugs` del AOP que el LLM puede ver: encendidas, registradas y permitidas
    por la identidad. Conserva el orden. Con `commerce`, suma las skills `core` del
    sistema (la de respaldo del nivel `guest`), que no dependen del AOP ni del tenant."""
    visible: list[str] = []
    for slug in slugs:
        if not skill_enabled(tool_permissions.get(slug)):
            continue
        try:
            skill_cls = SkillRegistry.get(slug)
        except ValueError:
            logger.warning("allowed_skill_not_in_registry: %s", slug)
            continue
        if skill_visible(skill_cls, identity):
            visible.append(slug)
    if commerce:
        visible.extend(s for s in SkillRegistry.core_slugs() if s not in visible)
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
