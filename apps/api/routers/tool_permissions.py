"""Endpoints para gestionar permisos de skills por tenant.

Permite a super_admin y tenant_admin ver y modificar qué skills están habilitadas
para el tenant, incluyendo si requieren aprobación humana.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from apps.api.core.errors import ForbiddenError, NotFoundError
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    list_tool_permissions,
    upsert_tool_permission,
)
from apps.api.skills.registry import SkillRegistry
from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/tenants/me/tool-permissions", tags=["tool-permissions"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]


class ToolPermissionOut(BaseModel):
    skill_slug: str
    is_enabled: bool
    human_approval_required: bool
    threshold_override: float | None = None
    tier: str | None = None

    model_config = {"from_attributes": True}


class UpdatePermissionRequest(BaseModel):
    is_enabled: bool
    human_approval_required: bool = False
    threshold_override: float | None = None


# ----------------------------------------------------------------
# GET /tenants/me/tool-permissions
# ----------------------------------------------------------------


@router.get("", summary="Listar permisos de skills del tenant")
async def list_permissions(
    tenant_id: TenantIdDep,
) -> dict:
    async with tenant_scope(tenant_id) as conn:
        perms = await list_tool_permissions(conn, tenant_id)

    # Enriquecer con tier del registry (si la skill está registrada)
    result = []
    for p in perms:
        tier: str | None = None
        try:
            skill_cls = SkillRegistry.get(p.skill_slug)
            tier = skill_cls.tier
        except ValueError:
            pass
        result.append(
            ToolPermissionOut(
                skill_slug=p.skill_slug,
                is_enabled=p.is_enabled,
                human_approval_required=p.human_approval_required,
                threshold_override=p.threshold_override,
                tier=tier,
            )
        )
    return {"permissions": result}


# ----------------------------------------------------------------
# PUT /tenants/me/tool-permissions/{slug}
# ----------------------------------------------------------------


@router.put("/{skill_slug:path}", summary="Actualizar permiso de una skill")
async def update_permission(
    skill_slug: str,
    body: UpdatePermissionRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> ToolPermissionOut:
    # Solo super_admin o tenant_admin pueden modificar permisos
    if auth.role not in ("super_admin", "tenant_admin"):
        raise ForbiddenError("Se requiere tenant_admin o super_admin", code="insufficient_role")

    # Validar que la skill existe en el registry
    try:
        skill_cls = SkillRegistry.get(skill_slug)
    except ValueError as exc:
        raise NotFoundError(f"skill not found: {skill_slug}", code="skill_not_found") from exc

    async with tenant_scope(tenant_id) as conn:
        perm = await upsert_tool_permission(
            conn,
            tenant_id=tenant_id,
            skill_slug=skill_slug,
            is_enabled=body.is_enabled,
            human_approval_required=body.human_approval_required,
            threshold_override=body.threshold_override,
            enabled_by=auth.user_id,
        )

    return ToolPermissionOut(
        skill_slug=perm.skill_slug,
        is_enabled=perm.is_enabled,
        human_approval_required=perm.human_approval_required,
        threshold_override=perm.threshold_override,
        tier=skill_cls.tier,
    )
