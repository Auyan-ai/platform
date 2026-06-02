"""Provisioning de tenants: crea tenant + tenant_admin + invite end-to-end.

Productiza los pasos 1 y 2 del onboarding (ver docs/onboarding-system-plan.md §3-6).
Usa el service_role key de Supabase para crear el auth user y mandar magic link.

Flujo:
    1. Valida slug único.
    2. Crea o recupera el auth.users vía Supabase Auth Admin API.
    3. Transacción DB: tenants + public.users + tenant_onboarding + tenant_assignment.
       Tenant nace con lifecycle 'discovery' porque el invite ya se mandó.
    4. Devuelve resultado con tenant + auth_user_id + invite_sent.

Idempotencia: si el email ya tiene auth user, lo recupera y le re-manda magic link
(no falla). El INSERT en public.users hace ON CONFLICT (id) DO UPDATE para tolerar
re-provisioning del mismo email a un tenant nuevo.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import asyncpg
import httpx
from apps.api.aops.canonical import provision_canonical_aops
from apps.api.core.config import Settings
from apps.api.db.models import PlanTier, Tenant


class SlugTakenError(Exception):
    """El slug solicitado ya está en uso por un tenant activo."""


class SupabaseAdminError(Exception):
    """Falla irrecuperable contra Supabase Auth Admin API."""


@dataclass(frozen=True)
class ProvisionRequest:
    company_name: str
    slug: str
    plan_tier: PlanTier
    tenant_admin_email: str
    tenant_admin_name: str
    creator_internal_user_id: UUID


@dataclass(frozen=True)
class ProvisionResult:
    tenant: Tenant
    tenant_admin_user_id: UUID
    invite_sent: bool


async def provision_tenant(
    conn: asyncpg.Connection,
    *,
    settings: Settings,
    http: httpx.AsyncClient,
    request: ProvisionRequest,
) -> ProvisionResult:
    """Crea tenant + tenant_admin + manda invite. Ver docstring del módulo."""
    existing_slug = await conn.fetchval(
        "SELECT 1 FROM tenants WHERE slug = $1 AND deleted_at IS NULL",
        request.slug,
    )
    if existing_slug is not None:
        raise SlugTakenError(request.slug)

    supabase_url = str(settings.supabase_url).rstrip("/")
    service_role = settings.supabase_service_role_key.get_secret_value()

    auth_user_id, invite_sent = await _invite_or_get_user(
        http=http,
        supabase_url=supabase_url,
        service_role=service_role,
        email=request.tenant_admin_email,
    )

    async with conn.transaction():
        tenant_id = uuid4()
        row = await conn.fetchrow(
            """
            INSERT INTO tenants (id, slug, name, plan_tier, agent_lifecycle_state)
            VALUES ($1, $2, $3, $4, 'discovery')
            RETURNING id, slug, name, status, agent_lifecycle_state, plan_tier
            """,
            tenant_id,
            request.slug,
            request.company_name,
            request.plan_tier,
        )
        assert row is not None
        tenant = Tenant(**dict(row))

        await conn.execute(
            """
            INSERT INTO users (id, tenant_id, email, full_name, role)
            VALUES ($1, $2, $3, $4, 'tenant_admin')
            ON CONFLICT (id) DO UPDATE
              SET tenant_id  = EXCLUDED.tenant_id,
                  email      = EXCLUDED.email,
                  full_name  = EXCLUDED.full_name,
                  role       = EXCLUDED.role,
                  deleted_at = NULL
            """,
            auth_user_id,
            tenant_id,
            request.tenant_admin_email,
            request.tenant_admin_name,
        )

        await conn.execute(
            "INSERT INTO tenant_onboarding (tenant_id) VALUES ($1)",
            tenant_id,
        )

        await conn.execute(
            """
            INSERT INTO tenant_assignments
              (tenant_id, internal_user_id, role_in_tenant, assigned_by)
            VALUES ($1, $2, 'aide_primary', $2)
            """,
            tenant_id,
            request.creator_internal_user_id,
        )

        # Copy-on-create: cada tenant nace con su propia copia de los 8 AOPs canónicos
        # + permisos default (L1/L2 auto, L3 approval). Dentro de la misma transacción
        # → atómico: si algo falla, no queda un tenant a medio provisionar.
        # created_by=None: el creador es un internal_user, y aop_versions.created_by
        # referencia users(id); None evita una violación de FK.
        await provision_canonical_aops(conn, tenant_id, created_by=None)

    return ProvisionResult(
        tenant=tenant,
        tenant_admin_user_id=auth_user_id,
        invite_sent=invite_sent,
    )


# ─── Supabase Auth Admin API ─────────────────────────────────────────────────


def _admin_headers(service_role: str) -> dict[str, str]:
    return {
        "apikey": service_role,
        "Authorization": f"Bearer {service_role}",
        "Content-Type": "application/json",
    }


async def _invite_or_get_user(
    *,
    http: httpx.AsyncClient,
    supabase_url: str,
    service_role: str,
    email: str,
) -> tuple[UUID, bool]:
    """POST /auth/v1/invite. Si el user ya existe, lo busca y re-manda magic link.

    Returns:
        (auth_user_id, invite_sent)
    """
    headers = _admin_headers(service_role)
    invite_resp = await http.post(
        f"{supabase_url}/auth/v1/invite",
        headers=headers,
        json={"email": email},
        timeout=15,
    )

    if invite_resp.status_code in (200, 201):
        data = invite_resp.json()
        return UUID(data["id"]), True

    if invite_resp.status_code in (400, 409, 422) and _looks_like_email_exists(invite_resp):
        user_id = await _find_user_by_email(
            http=http, supabase_url=supabase_url, service_role=service_role, email=email
        )
        if user_id is None:
            raise SupabaseAdminError(
                f"Supabase reportó email existente pero no se encontró usuario para {email}"
            )
        magic_resp = await http.post(
            f"{supabase_url}/auth/v1/admin/generate_link",
            headers=headers,
            json={"type": "magiclink", "email": email},
            timeout=15,
        )
        return user_id, magic_resp.status_code in (200, 201)

    raise SupabaseAdminError(
        f"Supabase invite falló: {invite_resp.status_code} {invite_resp.text[:200]}"
    )


def _looks_like_email_exists(resp: httpx.Response) -> bool:
    content_type = resp.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        return False
    try:
        body = resp.json()
    except ValueError:
        return False
    msg = " ".join(
        str(body.get(k, "")) for k in ("msg", "message", "error_description", "error", "code")
    ).lower()
    return any(token in msg for token in ("already", "exists", "registered", "duplicate"))


async def _find_user_by_email(
    *,
    http: httpx.AsyncClient,
    supabase_url: str,
    service_role: str,
    email: str,
) -> UUID | None:
    """GET /auth/v1/admin/users?email=... — paginado, devuelve el id si encuentra."""
    headers = _admin_headers(service_role)
    resp = await http.get(
        f"{supabase_url}/auth/v1/admin/users",
        headers=headers,
        params={"email": email},
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    users = data.get("users", []) if isinstance(data, dict) else []
    needle = email.strip().lower()
    for user in users:
        if str(user.get("email", "")).strip().lower() == needle:
            return UUID(user["id"])
    return None
