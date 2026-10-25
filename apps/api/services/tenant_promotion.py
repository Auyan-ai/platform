"""Convertir una demo en cliente (ADR 0015 §6).

Orden: validar demo y slug, invitar al admin (`attach_tenant_admin`, antes de tocar el tenant
para que un correo fallido lo deje intacto) y después, en una sola transacción, pasar el tenant
a `client`. Repetirla con el mismo email y slug converge al mismo estado.

`demo_source_url` se conserva: es la procedencia del contenido ingerido y la base de la
resincronización semanal (PR 11). Nada en el runtime depende de ese campo para decidir el
modo de comercio (`demo_state_overrides` mira `origin`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

import asyncpg
import httpx
from apps.api.aops.canonical import CANONICAL_TOOL_PERMISSIONS
from apps.api.core.config import Settings
from apps.api.core.errors import ConflictError, NotFoundError
from apps.api.db.models import PlanTier, Tenant
from apps.api.db.queries import get_tenant_by_id, upsert_tool_permission
from apps.api.services.demo_tenants import DEMO_ALLOWED_SKILLS
from apps.api.services.tenant_provisioning import SlugTakenError, attach_tenant_admin

logger = logging.getLogger(__name__)

_SLUG_UNIQUE_CONSTRAINT = "tenants_slug_key"


@dataclass(frozen=True)
class PromotionResult:
    tenant: Tenant
    tenant_admin_user_id: UUID


async def promote_demo_tenant(
    conn: asyncpg.Connection,
    http: httpx.AsyncClient,
    settings: Settings,
    *,
    tenant_id: UUID,
    admin_email: str,
    admin_name: str,
    plan_tier: PlanTier,
    slug: str,
    creator_internal_user_id: UUID,
) -> PromotionResult:
    """Convierte la demo `tenant_id` en cliente.

    Raises:
        NotFoundError: el tenant no existe.
        ConflictError: `tenant_not_demo` si ya es cliente (salvo reintento exacto, que
            devuelve el tenant tal cual), o `slug_taken` si otro tenant usa el slug.
        SupabaseAdminError: el correo de acceso no salió; el tenant queda intacto.
    """
    tenant = await get_tenant_by_id(conn, tenant_id)
    if tenant is None:
        raise NotFoundError(f"tenant {tenant_id} not found", code="tenant_not_found")
    if tenant.origin != "demo":
        return await _already_promoted_or_conflict(
            conn, tenant, slug=slug, admin_email=admin_email
        )

    # El slug es único incluso entre tenants borrados (ADR 0015 §5): no filtrar por deleted_at.
    if await conn.fetchval("SELECT 1 FROM tenants WHERE slug = $1 AND id <> $2", slug, tenant_id):
        raise SlugTakenError(slug)

    auth_user_id = await attach_tenant_admin(
        conn,
        http,
        settings,
        tenant_id=tenant_id,
        email=admin_email,
        name=admin_name,
        creator_internal_user_id=creator_internal_user_id,
    )

    try:
        async with conn.transaction():
            promoted = await _convert_to_client(conn, tenant_id, slug=slug, plan_tier=plan_tier)
            if promoted is None:
                raise ConflictError(
                    "el tenant dejó de ser una demo mientras se convertía", code="tenant_not_demo"
                )
            await _restore_canonical_permissions(conn, tenant_id)
    except asyncpg.UniqueViolationError as exc:
        if exc.constraint_name != _SLUG_UNIQUE_CONSTRAINT:
            raise
        raise SlugTakenError(slug) from exc

    logger.info(
        "demo_tenant_promoted tenant_id=%s old_slug=%s new_slug=%s plan_tier=%s",
        tenant_id,
        tenant.slug,
        promoted.slug,
        plan_tier,
    )
    return PromotionResult(tenant=promoted, tenant_admin_user_id=auth_user_id)


async def _already_promoted_or_conflict(
    conn: asyncpg.Connection, tenant: Tenant, *, slug: str, admin_email: str
) -> PromotionResult:
    """Reintento tras una conversión completada: mismo slug y el email ya es su admin."""
    admin_id = (
        await conn.fetchval(
            """
            SELECT id FROM users
             WHERE tenant_id = $1 AND lower(email) = lower($2)
               AND role = 'tenant_admin' AND deleted_at IS NULL
            """,
            tenant.id,
            admin_email,
        )
        if tenant.demo_source_url and tenant.slug == slug
        else None
    )
    if admin_id is None:
        raise ConflictError("solo se pueden convertir tenants de demo", code="tenant_not_demo")
    return PromotionResult(tenant=tenant, tenant_admin_user_id=admin_id)


async def _convert_to_client(
    conn: asyncpg.Connection, tenant_id: UUID, *, slug: str, plan_tier: PlanTier
) -> Tenant | None:
    row = await conn.fetchrow(
        """
        UPDATE tenants
           SET origin = 'client',
               demo_expires_at = NULL,
               slug = $2,
               plan_tier = $3,
               agent_lifecycle_state = CASE
                 WHEN agent_lifecycle_state = 'initial' THEN 'discovery'::agent_lifecycle_state
                 ELSE agent_lifecycle_state
               END
         WHERE id = $1 AND origin = 'demo' AND deleted_at IS NULL
        RETURNING id, slug, name, status, agent_lifecycle_state, plan_tier,
                  origin, demo_expires_at, demo_source_url
        """,
        tenant_id,
        slug,
        plan_tier,
    )
    return None if row is None else Tenant(**dict(row))


async def _restore_canonical_permissions(conn: asyncpg.Connection, tenant_id: UUID) -> None:
    """Devuelve a su valor canónico lo que la demo apagó (todo lo que no es de solo lectura).

    Las L3 siguen exigiendo aprobación humana; `refund_partial` sigue apagada, como en cualquier
    alta nueva.
    """
    for perm in CANONICAL_TOOL_PERMISSIONS:
        if perm["skill_slug"] in DEMO_ALLOWED_SKILLS:
            continue
        await upsert_tool_permission(
            conn,
            tenant_id=tenant_id,
            skill_slug=perm["skill_slug"],
            is_enabled=perm["is_enabled"],
            human_approval_required=perm["human_approval_required"],
        )
