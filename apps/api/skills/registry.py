"""SkillRegistry — registro central de todas las skills disponibles."""

from __future__ import annotations

from typing import ClassVar

from apps.api.skills.base import Skill


class SkillRegistry:
    """Singleton de clase que mapea slug → clase Skill.

    Uso normal: decorar la clase con @SkillRegistry.register.
    Uso en el grafo: list_for_aop(aop.allowed_skills) devuelve las clases listas
    para convertir a tool definitions.
    """

    _by_slug: ClassVar[dict[str, type[Skill]]] = {}

    @classmethod
    def register(cls, skill_class: type[Skill]) -> type[Skill]:
        """Registra una skill. Usable como decorador de clase.

        Una skill que toca datos de un cliente (`identity_scope` distinto de `public`)
        declara `min_level`: sin él el gate no sabría qué exigirle.
        """
        if skill_class.identity_scope != "public" and skill_class.min_level is None:
            raise ValueError(f"skill_without_min_level: {skill_class.slug}")
        cls._by_slug[skill_class.slug] = skill_class
        return skill_class

    @classmethod
    def get(cls, slug: str) -> type[Skill]:
        """Devuelve la clase para el slug dado. Lanza ValueError si no existe."""
        if slug not in cls._by_slug:
            raise ValueError(f"unknown_skill: {slug}")
        return cls._by_slug[slug]

    @classmethod
    def list_for_aop(cls, allowed_slugs: list[str]) -> list[type[Skill]]:
        """Devuelve las clases para los slugs del AOP, en el mismo orden."""
        return [cls.get(s) for s in allowed_slugs]

    @classmethod
    def _reset(cls) -> None:
        """Limpia el registry. Solo para tests — no llamar en producción."""
        cls._by_slug.clear()
