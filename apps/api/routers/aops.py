"""Endpoints de AOPs — gestión de Agent Operating Procedures desde el dashboard.

CRUD completo + endpoint de validación (test inmediato / preview del prompt compilado).
PATCH /aops/{id}/promote — gate de calidad antes de copiar staging → production.
Todos los endpoints requieren auth y operan sobre el tenant del caller.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

import yaml
from apps.api.aops.compiler import compile_aop
from apps.api.core.security import AuthContext, get_auth_context, get_tenant_id, require_role
from apps.api.db.client import tenant_scope
from apps.api.db.models import AopWithContent, AopWorkspace, TenantConfiguration
from apps.api.db.queries import (
    create_aop,
    get_aop_by_id,
    get_aop_by_slug,
    get_tenant_configuration,
    list_aops,
    save_aop_version,
    soft_delete_aop,
    toggle_aop_active,
)
from apps.api.evals.harness import run_eval
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aops", tags=["aops"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]
AdminDep = Depends(require_role("tenant_admin", "super_admin"))


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _parse_raw_source(raw: str) -> tuple[dict, str]:
    """Parsea un source con bloque YAML frontmatter + cuerpo markdown.

    Formato esperado:
        ---
        slug: mi_aop
        name: Mi AOP
        ---

        ## Procedimiento
        ...

    Retorna (frontmatter_dict, body_markdown).
    Levanta ValueError si el formato no es válido.
    """
    raw = raw.strip()
    if not raw.startswith("---"):
        raise ValueError(
            "El AOP debe empezar con '---' seguido del bloque YAML frontmatter."
        )
    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise ValueError(
            "Formato inválido: se esperan dos delimitadores '---' encerrando el frontmatter."
        )
    frontmatter_str = parts[1].strip()
    body = parts[2].strip()
    try:
        frontmatter = yaml.safe_load(frontmatter_str) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML inválido en frontmatter: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise ValueError("El frontmatter YAML debe ser un mapping (dict).")
    return frontmatter, body


# ─── Response schemas ─────────────────────────────────────────────────────────


class AopSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    slug: str
    workspace: AopWorkspace
    current_version: int
    is_active: bool
    name: str
    description: str

    @classmethod
    def from_aop(cls, aop: AopWithContent) -> AopSummaryResponse:
        fm = aop.yaml_frontmatter
        return cls(
            id=aop.id,
            tenant_id=aop.tenant_id,
            slug=aop.slug,
            workspace=aop.workspace,
            current_version=aop.current_version,
            is_active=aop.is_active,
            name=fm.get("name", aop.slug),
            description=(fm.get("triggers") or {}).get("description", ""),
        )


class AopDetailResponse(AopSummaryResponse):
    yaml_frontmatter: dict
    body_markdown: str
    raw_source: str

    @classmethod
    def from_aop(cls, aop: AopWithContent) -> AopDetailResponse:  # type: ignore[override]
        fm = aop.yaml_frontmatter
        return cls(
            id=aop.id,
            tenant_id=aop.tenant_id,
            slug=aop.slug,
            workspace=aop.workspace,
            current_version=aop.current_version,
            is_active=aop.is_active,
            name=fm.get("name", aop.slug),
            description=(fm.get("triggers") or {}).get("description", ""),
            yaml_frontmatter=aop.yaml_frontmatter,
            body_markdown=aop.body_markdown,
            raw_source=aop.raw_source,
        )


class AopValidateResponse(BaseModel):
    valid: bool
    system_prompt: str | None = None
    errors: list[str] = Field(default_factory=list)


# ─── Request schemas ──────────────────────────────────────────────────────────


class CreateAopRequest(BaseModel):
    raw_source: str = Field(..., description="AOP completo: '---\\nfrontmatter\\n---\\nbody'")
    workspace: AopWorkspace = "production"


class UpdateAopRequest(BaseModel):
    raw_source: str = Field(..., description="AOP completo: '---\\nfrontmatter\\n---\\nbody'")


class ToggleAopRequest(BaseModel):
    is_active: bool


class ValidateAopRequest(BaseModel):
    raw_source: str
    workspace: AopWorkspace = "production"


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[AopSummaryResponse],
    summary="Lista todos los AOPs del tenant (activos e inactivos)",
)
async def list_tenant_aops(
    tenant_id: TenantIdDep,
    workspace: AopWorkspace = "production",
) -> list[AopSummaryResponse]:
    async with tenant_scope(tenant_id) as conn:
        aops = await list_aops(conn, tenant_id, workspace)
    return [AopSummaryResponse.from_aop(a) for a in aops]


@router.get(
    "/{aop_id}",
    response_model=AopDetailResponse,
    summary="AOP con contenido completo por ID",
)
async def get_aop(
    aop_id: UUID,
    tenant_id: TenantIdDep,
) -> AopDetailResponse:
    async with tenant_scope(tenant_id) as conn:
        aop = await get_aop_by_id(conn, tenant_id, aop_id)
    if aop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="aop_not_found")
    return AopDetailResponse.from_aop(aop)


@router.post(
    "",
    response_model=AopDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea un nuevo AOP",
    dependencies=[AdminDep],
)
async def create_tenant_aop(
    body: CreateAopRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> AopDetailResponse:
    try:
        frontmatter, body_md = _parse_raw_source(body.raw_source)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    slug = frontmatter.get("slug")
    if not slug or not isinstance(slug, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El frontmatter debe incluir un campo 'slug' (string).",
        )

    try:
        async with tenant_scope(tenant_id) as conn:
            aop = await create_aop(
                conn,
                tenant_id=tenant_id,
                slug=slug,
                workspace=body.workspace,
                yaml_frontmatter=frontmatter,
                body_markdown=body_md,
                raw_source=body.raw_source,
                created_by=auth.user_id,
            )
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un AOP con slug '{slug}' en workspace '{body.workspace}'.",
            ) from exc
        raise

    logger.info("aop.created tenant=%s slug=%s workspace=%s", tenant_id, slug, body.workspace)
    return AopDetailResponse.from_aop(aop)


@router.put(
    "/{aop_id}",
    response_model=AopDetailResponse,
    summary="Guarda nueva versión del AOP (append-only)",
    dependencies=[AdminDep],
)
async def update_tenant_aop(
    aop_id: UUID,
    body: UpdateAopRequest,
    tenant_id: TenantIdDep,
    auth: AuthDep,
) -> AopDetailResponse:
    try:
        frontmatter, body_md = _parse_raw_source(body.raw_source)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    async with tenant_scope(tenant_id) as conn:
        existing = await get_aop_by_id(conn, tenant_id, aop_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="aop_not_found"
            )
        await save_aop_version(
            conn,
            tenant_id=tenant_id,
            aop_id=aop_id,
            yaml_frontmatter=frontmatter,
            body_markdown=body_md,
            raw_source=body.raw_source,
            created_by=auth.user_id,
        )
        # Bypass cache para retornar la versión recién guardada
        from apps.api.aops.compiler import _AOP_CACHE

        _AOP_CACHE.pop((tenant_id, existing.slug, existing.workspace), None)
        updated = await get_aop_by_id(conn, tenant_id, aop_id)

    assert updated is not None
    logger.info(
        "aop.updated tenant=%s slug=%s v=%d",
        tenant_id,
        updated.slug,
        updated.current_version,
    )
    return AopDetailResponse.from_aop(updated)


@router.patch(
    "/{aop_id}/toggle",
    response_model=AopSummaryResponse,
    summary="Activa o desactiva un AOP",
    dependencies=[AdminDep],
)
async def toggle_tenant_aop(
    aop_id: UUID,
    body: ToggleAopRequest,
    tenant_id: TenantIdDep,
) -> AopSummaryResponse:
    async with tenant_scope(tenant_id) as conn:
        existing = await get_aop_by_id(conn, tenant_id, aop_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="aop_not_found"
            )
        await toggle_aop_active(conn, tenant_id=tenant_id, aop_id=aop_id, is_active=body.is_active)
        updated = await get_aop_by_id(conn, tenant_id, aop_id)

    assert updated is not None
    return AopSummaryResponse.from_aop(updated)


@router.delete(
    "/{aop_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Soft-delete de un AOP",
    dependencies=[AdminDep],
)
async def delete_tenant_aop(
    aop_id: UUID,
    tenant_id: TenantIdDep,
) -> None:
    async with tenant_scope(tenant_id) as conn:
        existing = await get_aop_by_id(conn, tenant_id, aop_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="aop_not_found"
            )
        await soft_delete_aop(conn, tenant_id=tenant_id, aop_id=aop_id)
    logger.info("aop.deleted tenant=%s aop_id=%s", tenant_id, aop_id)


class PromoteAopResponse(BaseModel):
    """Respuesta del endpoint PATCH /aops/{id}/promote."""

    aop_id: UUID
    slug: str
    eval_pass_rate: float
    eval_passed_fixtures: int
    eval_total_fixtures: int
    meets_gate: bool
    promoted_to_production: bool
    production_aop_id: UUID | None = None
    fixture_details: list[dict] = Field(default_factory=list)


@router.patch(
    "/{aop_id}/promote",
    response_model=PromoteAopResponse,
    summary="Evalúa el AOP y lo promueve a production si pasa el eval harness",
    dependencies=[AdminDep],
)
async def promote_tenant_aop(
    aop_id: UUID,
    tenant_id: TenantIdDep,
) -> PromoteAopResponse:
    """Ejecuta el eval harness (fixtures YAML) contra el AOP.

    Si pass_rate >= 80% y hay al menos 1 fixture:
    - Copia el contenido al AOP de production con el mismo slug (crea o actualiza).
    - Retorna promoted_to_production=True.

    Si falla el gate (pass_rate < 80% o sin fixtures):
    - Retorna HTTP 422 con detalles de qué fixtures fallaron.
    - No modifica el AOP de production.
    """
    async with tenant_scope(tenant_id) as conn:
        aop = await get_aop_by_id(conn, tenant_id, aop_id)
    if aop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="aop_not_found")

    # ── 1. Cargar tenant config para compilar ────────────────────────────────
    async with tenant_scope(tenant_id) as conn:
        config_row = await get_tenant_configuration(conn, tenant_id)
    if config_row is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tenant_config_not_found",
        )
    tenant_config = TenantConfiguration.model_validate(config_row)

    # ── 2. Correr eval harness ───────────────────────────────────────────────
    eval_result = run_eval(aop, tenant_config)

    fixture_details = [
        {
            "name": fr.fixture_name,
            "passed": fr.passed,
            "assertions": [
                {"kind": ar.kind, "passed": ar.passed, "message": ar.message}
                for ar in fr.assertion_results
            ],
        }
        for fr in eval_result.fixture_results
    ]

    if not eval_result.meets_gate:
        reason = (
            "no_fixtures_found"
            if eval_result.total_fixtures == 0
            else f"pass_rate={eval_result.pass_rate:.0%} < 80%"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "eval_gate_failed",
                "reason": reason,
                "pass_rate": eval_result.pass_rate,
                "passed_fixtures": eval_result.passed_fixtures,
                "total_fixtures": eval_result.total_fixtures,
                "fixtures": fixture_details,
            },
        )

    # ── 3. Promover a production ─────────────────────────────────────────────
    async with tenant_scope(tenant_id) as conn:
        prod_aop = await get_aop_by_slug(conn, tenant_id, aop.slug, "production")

        if prod_aop is None:
            prod_aop = await create_aop(
                conn,
                tenant_id=tenant_id,
                slug=aop.slug,
                workspace="production",
                yaml_frontmatter=aop.yaml_frontmatter,
                body_markdown=aop.body_markdown,
                raw_source=aop.raw_source,
                created_by=None,
            )
        else:
            await save_aop_version(
                conn,
                tenant_id=tenant_id,
                aop_id=prod_aop.id,
                yaml_frontmatter=aop.yaml_frontmatter,
                body_markdown=aop.body_markdown,
                raw_source=aop.raw_source,
                created_by=None,
            )
            prod_aop = await get_aop_by_id(conn, tenant_id, prod_aop.id)

    assert prod_aop is not None
    logger.info(
        "aop.promoted tenant=%s slug=%s pass_rate=%.2f prod_aop_id=%s",
        tenant_id,
        aop.slug,
        eval_result.pass_rate,
        prod_aop.id,
    )

    return PromoteAopResponse(
        aop_id=aop_id,
        slug=aop.slug,
        eval_pass_rate=eval_result.pass_rate,
        eval_passed_fixtures=eval_result.passed_fixtures,
        eval_total_fixtures=eval_result.total_fixtures,
        meets_gate=True,
        promoted_to_production=True,
        production_aop_id=prod_aop.id,
        fixture_details=fixture_details,
    )


@router.post(
    "/validate",
    response_model=AopValidateResponse,
    summary="Valida y precompila un AOP — test inmediato sin guardar",
)
async def validate_aop(
    body: ValidateAopRequest,
    tenant_id: TenantIdDep,
) -> AopValidateResponse:
    """Parsea el raw_source, compila el AOP y retorna el system_prompt renderizado.

    No persiste nada. Úsalo desde el editor como 'Vista previa del prompt'.
    """
    errors: list[str] = []

    try:
        frontmatter, body_md = _parse_raw_source(body.raw_source)
    except ValueError as exc:
        return AopValidateResponse(valid=False, errors=[str(exc)])

    if not frontmatter.get("slug"):
        errors.append("Falta el campo 'slug' en el frontmatter.")

    if errors:
        return AopValidateResponse(valid=False, errors=errors)

    async with tenant_scope(tenant_id) as conn:
        tenant_config_row = await get_tenant_configuration(conn, tenant_id)

    if tenant_config_row is None:
        return AopValidateResponse(
            valid=False, errors=["No se encontró la configuración del tenant."]
        )

    tenant_config = TenantConfiguration.model_validate(tenant_config_row)

    # Construir un AopWithContent temporal para compilarlo
    from uuid import uuid4

    from apps.api.db.models import AopWithContent as _AopWithContent

    temp_aop = _AopWithContent(
        id=uuid4(),
        tenant_id=tenant_id,
        slug=frontmatter.get("slug", "preview"),
        workspace=body.workspace,
        current_version=0,
        is_active=True,
        yaml_frontmatter=frontmatter,
        body_markdown=body_md,
        raw_source=body.raw_source,
    )

    try:
        compiled = compile_aop(temp_aop, tenant_config)
    except Exception as exc:
        return AopValidateResponse(valid=False, errors=[f"Error al compilar: {exc}"])

    return AopValidateResponse(valid=True, system_prompt=compiled.system_prompt)
