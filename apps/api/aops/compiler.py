"""AOP compiler — convierte un AopWithContent + TenantConfiguration en el input
que Claude necesita: system_prompt compilado + tool definitions scopeadas al AOP.

Cada request al grafo pasa por compile_aop antes de llamar a Claude. Para evitar
DB y CPU innecesarios, load_aop cachea el AopWithContent (TTL 60s por worker).
Esto permite hot-reload casi instantáneo desde el dashboard con delay máximo de 60s.

Importante: el cache es por (tenant_id, slug, workspace) sin version — la invalidación
es por TTL. Para forzar actualización inmediata (ej: botón "test inmediato"), usar
bypass_cache=True en load_aop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from apps.api.db.models import AopWithContent, KnowledgeChunk, TenantConfiguration
from apps.api.db.queries import get_active_aops, get_aop_by_slug
from apps.api.skills.registry import SkillRegistry
from cachetools import TTLCache

if TYPE_CHECKING:
    import asyncpg

# ─── Cache ───────────────────────────────────────────────────────────────────

_AOP_CACHE: TTLCache[tuple, AopWithContent] = TTLCache(maxsize=1000, ttl=60)


# ─── Output del compiler ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class CompiledAOP:
    """Resultado del compiler: todo lo que el nodo reason necesita para llamar a Claude."""

    system_prompt: str
    tool_definitions: list[dict[str, Any]]
    allowed_skills: list[str]
    max_iterations: int
    confidence_threshold: float
    require_supervision: bool
    escalation_triggers: list[str] = field(default_factory=list)


# ─── Función principal ───────────────────────────────────────────────────────


def compile_aop(
    aop: AopWithContent,
    tenant_config: TenantConfiguration,
    kb_chunks: list[KnowledgeChunk] | None = None,
) -> CompiledAOP:
    """Compila un AOP a system prompt + tool definitions para Claude.

    Función pura: sin I/O, determinista para los mismos inputs. El cache vive en
    load_aop — aquí no hay estado.
    """
    fm = aop.yaml_frontmatter
    allowed_skills: list[str] = fm.get("allowed_skills", [])

    tool_definitions = _resolve_tool_definitions(allowed_skills)

    blocks = [
        _render_tenant_identity(tenant_config),
        _render_aop_procedure(aop.body_markdown, fm),
        _render_guardrails(fm.get("guardrails", [])),
        _render_required_data(fm.get("required_data", [])),
        _render_kb_chunks(kb_chunks or []),
        _render_global_rules(fm.get("escalation_triggers", [])),
    ]

    system_prompt = "\n\n---\n\n".join(b for b in blocks if b.strip())

    return CompiledAOP(
        system_prompt=system_prompt,
        tool_definitions=tool_definitions,
        allowed_skills=allowed_skills,
        max_iterations=int(fm.get("max_tool_iterations", 5)),
        confidence_threshold=float(fm.get("confidence_threshold", 0.70)),
        require_supervision=bool(fm.get("require_supervision", False)),
        escalation_triggers=list(fm.get("escalation_triggers", [])),
    )


# ─── Cache + DB load ─────────────────────────────────────────────────────────


async def load_aop(
    conn: asyncpg.Connection,
    tenant_id: Any,
    slug: str,
    workspace: str = "production",
    *,
    bypass_cache: bool = False,
) -> AopWithContent | None:
    """Carga un AOP de DB con TTL cache de 60s por (tenant_id, slug, workspace).

    bypass_cache=True: ignora el cache y va directo a DB. Usar desde el endpoint
    de "test inmediato" del editor del dashboard.
    """
    cache_key = (str(tenant_id), slug, workspace)

    if not bypass_cache and cache_key in _AOP_CACHE:
        return _AOP_CACHE[cache_key]

    aop = await get_aop_by_slug(conn, tenant_id, slug, workspace)  # type: ignore[arg-type]
    if aop is not None:
        _AOP_CACHE[cache_key] = aop
    return aop


async def load_active_aops(
    conn: asyncpg.Connection,
    tenant_id: Any,
    workspace: str = "production",
) -> list[AopWithContent]:
    """Carga todos los AOPs activos del tenant. Sin cache — se usa al inicio de
    select_aop para construir el catálogo de clasificación.
    """
    return await get_active_aops(conn, tenant_id, workspace)  # type: ignore[arg-type]


# ─── Block renderers ─────────────────────────────────────────────────────────


def _render_tenant_identity(tenant_config: TenantConfiguration) -> str:
    agent_voice = (
        tenant_config.extra.get("agent_voice")
        or tenant_config.branding.get("agent_voice")
        or ""
    )
    if agent_voice:
        return f"## Identidad\n\n{agent_voice}"
    return (
        "## Identidad\n\n"
        "Eres un agente de soporte de atención al cliente. "
        "Sé claro, empático y conciso en tus respuestas."
    )


def _render_aop_procedure(body: str, fm: dict[str, Any]) -> str:
    name = fm.get("name", "Procedimiento")
    return f"## Procedimiento: {name}\n\n{body.strip()}"


def _render_guardrails(guardrails: list[str]) -> str:
    if not guardrails:
        return ""
    lines = "\n".join(f"- {g}" for g in guardrails)
    return (
        "## Reglas NO negociables\n"
        "Estas reglas no las puedes romper bajo ninguna circunstancia:\n\n"
        f"{lines}"
    )


def _render_required_data(required_data: list[str]) -> str:
    if not required_data:
        return ""
    lines = "\n".join(f"- {d}" for d in required_data)
    return (
        "## Datos requeridos\n"
        "Necesitas estos datos para resolver. Si no los tienes, pídelos antes de usar tools:\n\n"
        f"{lines}"
    )


def _render_kb_chunks(chunks: list[KnowledgeChunk]) -> str:
    if not chunks:
        return ""
    parts = []
    for i, c in enumerate(chunks, start=1):
        parts.append(
            f"### Fragmento {i} — '{c.document_title}' (similitud {c.similarity:.2f})\n"
            f"{c.content.strip()}"
        )
    return (
        "## Contexto de la base de conocimiento\n\n"
        + "\n\n".join(parts)
        + "\n\nSi la respuesta no está respaldada por este contexto, NO inventes — "
        "escala con razón explícita."
    )


def _render_global_rules(escalation_triggers: list[str]) -> str:
    lines = [
        "## Reglas globales",
        "",
        "- Siempre responde en el idioma del cliente.",
        "- Si no puedes resolver con las herramientas disponibles, "
        "escala a un agente humano con contexto completo.",
        "- Nunca inventes información que no tengas.",
    ]
    if escalation_triggers:
        lines.append("")
        lines.append("**Escala inmediatamente si ocurre alguno de estos:**")
        for t in escalation_triggers:
            lines.append(f"- {t}")
    return "\n".join(lines)


def _resolve_tool_definitions(allowed_slugs: list[str]) -> list[dict[str, Any]]:
    """Convierte slugs a Anthropic tool defs. Slugs no registrados se omiten con warning."""
    import logging

    logger = logging.getLogger(__name__)
    defs = []
    for slug in allowed_slugs:
        try:
            skill_class = SkillRegistry.get(slug)
            defs.append(skill_class().to_anthropic_tool())
        except ValueError:
            logger.warning("aop_compiler.unknown_skill slug=%s", slug)
    return defs
