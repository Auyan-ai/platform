"""Provisioning de tenants: crea tenant + tenant_admin + invite end-to-end.

Productiza los pasos 1 y 2 del onboarding (ver docs/onboarding-system-plan.md §3-6).
Usa el service_role key de Supabase para crear el auth user y mandarle el correo de acceso.

Flujo:
    1. Valida slug único.
    2. Crea o recupera el auth.users vía Supabase Auth y le manda el correo de acceso.
       Si el correo no sale, SupabaseAdminError antes de tocar la DB.
    3. Transacción DB: tenants + public.users + tenant_onboarding + tenant_assignment.
       Tenant nace con lifecycle 'discovery' porque el invite ya se mandó.
    4. Devuelve resultado con tenant + auth_user_id + invite_sent.

El alta se compone de dos piezas idempotentes reutilizables (`scaffold_tenant` y
`attach_tenant_admin`); `provision_tenant` las encadena con el invite fuera de la
transacción.

Idempotencia: si el email ya tiene auth user, lo recupera y le manda un magic link
por correo (no falla). El INSERT en public.users hace ON CONFLICT (id) DO UPDATE para
tolerar re-provisioning del mismo email a un tenant nuevo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import asyncpg
import httpx
from apps.api.aops.canonical import provision_canonical_aops
from apps.api.core.config import Settings
from apps.api.db.models import AgentLifecycleState, PlanTier, Tenant, TenantOrigin

# Prompt base que nace con cada tenant. Es el fallback legacy: en runtime
# select_aop sobreescribe system_prompt con el AOP compilado (todo tenant nace
# con los 8 AOPs canónicos). Pero load_tenant_context hard-failea si no hay un
# prompt activo, así que toda tenant necesita esta fila. Sin branding ni
# políticas concretas — eso lo llena el onboarding.
_DEFAULT_SYSTEM_PROMPT = """\
Eres el agente de atención al cliente de {company_name}.

Tono: cercano, claro y breve. Trata al cliente de "tú".

Tu misión: resolver dudas de soporte (pedidos, envíos, devoluciones, productos) \
con precisión y empatía, apoyándote SIEMPRE en la knowledge base y los datos del \
tenant. Si la consulta requiere acción humana (reembolso fuera de política, queja \
grave, asunto legal, cliente muy molesto) o no tienes información con respaldo, \
escala a un agente humano explicando el motivo.

Reglas no negociables:
- Nunca inventes datos de pedidos, stock, plazos, fechas, importes ni políticas. \
Si una herramienta devuelve vacío o error, trátalo como dato no disponible y \
escala; no rellenes con suposiciones.
- Usa la knowledge base del tenant antes de responder sobre políticas o productos.
- Si el cliente pide hablar con un humano, escala sin discutir.

Idioma: responde en el idioma del cliente (por defecto, español)."""


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
    # Siempre True: si el correo no sale, provision_tenant lanza SupabaseAdminError
    # y no hay resultado. Se mantiene en el contrato de POST /tenants.
    invite_sent: bool


async def ensure_tenant_config_and_prompt(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    company_name: str,
) -> dict[str, bool]:
    """Crea la fila 1:1 de `tenant_configurations` y el prompt 'system' activo si faltan.

    Idempotente: la config usa ON CONFLICT DO NOTHING; el prompt sólo se inserta si
    el tenant no tiene ya un 'system' (activo o no), para no pisar personalizaciones
    ni colisionar con el unique de versión. Lo usan `provision_tenant` (tenant nuevo)
    y el script de backfill (tenants existentes a los que les falte).

    `created_by=NULL`: el creador es un internal_user y `tenant_prompts.created_by`
    referencia `users(id)` — NULL evita una violación de FK (igual que en los AOPs).

    Returns: flags `{config_created, prompt_created}` para que el backfill reporte.
    """
    config_status = await conn.execute(
        """
        INSERT INTO tenant_configurations (tenant_id) VALUES ($1)
        ON CONFLICT (tenant_id) DO NOTHING
        """,
        tenant_id,
    )
    prompt_status = await conn.execute(
        """
        INSERT INTO tenant_prompts
          (tenant_id, name, version, content, is_active, created_by)
        SELECT $1, 'system', 1, $2, true, NULL
        WHERE NOT EXISTS (
            SELECT 1 FROM tenant_prompts WHERE tenant_id = $1 AND name = 'system'
        )
        """,
        tenant_id,
        _DEFAULT_SYSTEM_PROMPT.format(company_name=company_name),
    )
    return {
        "config_created": config_status.endswith(" 1"),
        "prompt_created": prompt_status.endswith(" 1"),
    }


async def scaffold_tenant(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID | None,
    slug: str,
    company_name: str,
    plan_tier: PlanTier,
    lifecycle_state: AgentLifecycleState,
    origin: TenantOrigin = "client",
    demo_expires_at: datetime | None = None,
    demo_source_url: str | None = None,
) -> Tenant:
    """Asegura el tenant y todo lo que el agente necesita para arrancar. Idempotente.

    Crea (o reutiliza) la fila de `tenants`, `tenant_configurations`, el prompt base
    'system', `tenant_onboarding` y los 8 AOPs canónicos con sus permisos. Volver a
    llamarla no duplica ni pisa nada: cada INSERT lleva ON CONFLICT / NOT EXISTS.

    `tenant_id=None`: reutiliza el tenant vivo con ese slug o crea uno nuevo. Con un
    id explícito, el `INSERT ... ON CONFLICT (id)` converge a la misma fila.

    No abre transacción: el llamador decide el alcance atómico (`provision_tenant`
    la comparte con `attach_tenant_admin`).
    """
    if tenant_id is None:
        existing = await conn.fetchval(
            "SELECT id FROM tenants WHERE slug = $1 AND deleted_at IS NULL",
            slug,
        )
        tenant_id = existing if existing is not None else uuid4()

    row = await conn.fetchrow(
        """
        INSERT INTO tenants
          (id, slug, name, plan_tier, agent_lifecycle_state,
           origin, demo_expires_at, demo_source_url)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (id) DO UPDATE SET slug = tenants.slug
        RETURNING id, slug, name, status, agent_lifecycle_state, plan_tier,
                  origin, demo_expires_at, demo_source_url
        """,
        tenant_id,
        slug,
        company_name,
        plan_tier,
        lifecycle_state,
        origin,
        demo_expires_at,
        demo_source_url,
    )
    assert row is not None
    tenant = Tenant(**dict(row))

    await conn.execute(
        "INSERT INTO tenant_onboarding (tenant_id) VALUES ($1) ON CONFLICT (tenant_id) DO NOTHING",
        tenant.id,
    )

    # tenant_configurations (1:1) + prompt 'system' activo. Sin ambos,
    # load_tenant_context hard-failea (tenant_config_missing /
    # no_active_system_prompt) en el primer mensaje.
    await ensure_tenant_config_and_prompt(conn, tenant.id, company_name=company_name)

    # Copy-on-create: cada tenant nace con su propia copia de los 8 AOPs canónicos
    # + permisos default (L1/L2 auto, L3 approval, refund_partial apagada).
    # created_by=None: el creador es un internal_user, y aop_versions.created_by
    # referencia users(id); None evita una violación de FK.
    await provision_canonical_aops(conn, tenant.id, created_by=None)
    return tenant


async def _write_tenant_admin_rows(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    auth_user_id: UUID,
    email: str,
    name: str,
    creator_internal_user_id: UUID,
) -> None:
    """Escrituras de DB del tenant_admin: `users` + `tenant_assignments`. Idempotente."""
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
        email,
        name,
    )

    # ON CONFLICT sin target: lo cubre el índice único parcial
    # (tenant_id, internal_user_id, role_in_tenant) WHERE unassigned_at IS NULL.
    await conn.execute(
        """
        INSERT INTO tenant_assignments
          (tenant_id, internal_user_id, role_in_tenant, assigned_by)
        VALUES ($1, $2, 'aide_primary', $2)
        ON CONFLICT DO NOTHING
        """,
        tenant_id,
        creator_internal_user_id,
    )


async def attach_tenant_admin(
    conn: asyncpg.Connection,
    http: httpx.AsyncClient,
    settings: Settings,
    *,
    tenant_id: UUID,
    email: str,
    name: str,
    creator_internal_user_id: UUID,
) -> UUID:
    """Invita (o recupera) al tenant_admin y lo enlaza al tenant. Idempotente.

    Orden: primero el correo de acceso (Supabase Auth); si falla, lanza
    SupabaseAdminError sin tocar la DB. Luego `users` y `tenant_assignments`.
    Repetirla reenvía el correo (magic link si el usuario ya existe) pero no
    duplica filas. El tenant debe existir (`scaffold_tenant`). No abre transacción.

    Returns: el id del auth user.
    """
    auth_user_id = await _invite_or_get_user(
        http=http,
        supabase_url=str(settings.supabase_url).rstrip("/"),
        service_role=settings.supabase_service_role_key.get_secret_value(),
        email=email,
    )
    await _write_tenant_admin_rows(
        conn,
        tenant_id=tenant_id,
        auth_user_id=auth_user_id,
        email=email,
        name=name,
        creator_internal_user_id=creator_internal_user_id,
    )
    return auth_user_id


async def provision_tenant(
    conn: asyncpg.Connection,
    *,
    settings: Settings,
    http: httpx.AsyncClient,
    request: ProvisionRequest,
) -> ProvisionResult:
    """Crea tenant + tenant_admin + manda invite. Ver docstring del módulo.

    Compone `scaffold_tenant` + las escrituras de `attach_tenant_admin`, pero el
    invite va ANTES de abrir la transacción (no se sostiene una transacción durante
    una llamada HTTP, y un correo fallido no toca la DB).
    """
    existing_slug = await conn.fetchval(
        "SELECT 1 FROM tenants WHERE slug = $1 AND deleted_at IS NULL",
        request.slug,
    )
    if existing_slug is not None:
        raise SlugTakenError(request.slug)

    auth_user_id = await _invite_or_get_user(
        http=http,
        supabase_url=str(settings.supabase_url).rstrip("/"),
        service_role=settings.supabase_service_role_key.get_secret_value(),
        email=request.tenant_admin_email,
    )

    # Un solo bloque atómico: si algo falla, no queda un tenant a medio provisionar.
    async with conn.transaction():
        tenant = await scaffold_tenant(
            conn,
            tenant_id=uuid4(),
            slug=request.slug,
            company_name=request.company_name,
            plan_tier=request.plan_tier,
            lifecycle_state="discovery",
        )
        await _write_tenant_admin_rows(
            conn,
            tenant_id=tenant.id,
            auth_user_id=auth_user_id,
            email=request.tenant_admin_email,
            name=request.tenant_admin_name,
            creator_internal_user_id=request.creator_internal_user_id,
        )

    return ProvisionResult(
        tenant=tenant,
        tenant_admin_user_id=auth_user_id,
        invite_sent=True,
    )


# ─── Supabase Auth Admin API ─────────────────────────────────────────────────

# Auth solo guarda usuarios del dashboard (tenant_admin y equipo interno): 50
# páginas de 200 cubren 10.000 sin tocar el tope.
_ADMIN_USERS_PER_PAGE = 200
_ADMIN_USERS_MAX_PAGES = 50


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
) -> UUID:
    """Manda el correo de acceso al tenant_admin y devuelve su auth user id.

    Usuario nuevo (o invitado sin confirmar): POST /auth/v1/invite crea el user y
    envía el correo de invitación. Usuario ya confirmado: /invite responde 422
    email_exists, se busca su id y se le manda un magic link con POST /auth/v1/otp.

    Raises:
        SupabaseAdminError: si Supabase no confirma el envío del correo.
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
        return UUID(data["id"])

    if invite_resp.status_code in (400, 409, 422) and _looks_like_email_exists(invite_resp):
        user_id = await _find_user_by_email(
            http=http, supabase_url=supabase_url, service_role=service_role, email=email
        )
        if user_id is None:
            raise SupabaseAdminError(
                f"Supabase reportó email existente pero no se encontró usuario para {email}"
            )
        await _send_magic_link(
            http=http, supabase_url=supabase_url, service_role=service_role, email=email
        )
        return user_id

    raise SupabaseAdminError(
        f"Supabase invite falló: {invite_resp.status_code} {invite_resp.text[:200]}"
    )


async def _send_magic_link(
    *,
    http: httpx.AsyncClient,
    supabase_url: str,
    service_role: str,
    email: str,
) -> None:
    """POST /auth/v1/otp con create_user=false: envía el correo de magic link.

    No se usa /admin/generate_link porque solo devuelve el enlace sin mandar correo.
    create_user=false impide que esta vía cree usuarios (si no existe, 422 otp_disabled).
    Supabase responde 200 con cuerpo vacío cuando el correo sale.

    Raises:
        SupabaseAdminError: cualquier respuesta distinta de 200 (p. ej. 429
            over_email_send_rate_limit, 422 otp_disabled, 5xx).
    """
    resp = await http.post(
        f"{supabase_url}/auth/v1/otp",
        headers=_admin_headers(service_role),
        json={"email": email, "create_user": False},
        timeout=15,
    )
    if resp.status_code != 200:
        raise SupabaseAdminError(
            f"No se pudo enviar el magic link a {email} (usuario ya existente en Supabase "
            f"Auth): {resp.status_code} {resp.text[:200]}. No se creó el tenant."
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
    """Recorre GET /auth/v1/admin/users página a página y devuelve el id del email.

    GoTrue no filtra este endpoint por email: solo acepta `page` y `per_page`
    (offset). Se para en la primera página con menos de `per_page` usuarios.
    Pasar `page` y `per_page` explícitos fija el modo offset aunque el servidor
    tenga activa la paginación por cursor.

    Returns:
        El id del usuario, o None si se agotaron las páginas sin encontrarlo.

    Raises:
        SupabaseAdminError: respuesta distinta de 200, cuerpo sin lista `users`,
            o más de `_ADMIN_USERS_MAX_PAGES` páginas llenas.
    """
    headers = _admin_headers(service_role)
    needle = email.strip().lower()
    for page in range(1, _ADMIN_USERS_MAX_PAGES + 1):
        resp = await http.get(
            f"{supabase_url}/auth/v1/admin/users",
            headers=headers,
            params={"page": page, "per_page": _ADMIN_USERS_PER_PAGE},
            timeout=15,
        )
        if resp.status_code != 200:
            raise SupabaseAdminError(
                f"No se pudo listar usuarios de Supabase Auth (página {page}): "
                f"{resp.status_code} {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except ValueError:
            data = None
        users = data.get("users") if isinstance(data, dict) else None
        if not isinstance(users, list):
            raise SupabaseAdminError(
                f"Respuesta inesperada de GET /admin/users (página {page}): {resp.text[:200]}"
            )
        for user in users:
            if str(user.get("email", "")).strip().lower() == needle:
                return UUID(user["id"])
        if len(users) < _ADMIN_USERS_PER_PAGE:
            return None
    raise SupabaseAdminError(
        f"Búsqueda de {email} en Supabase Auth cortada tras {_ADMIN_USERS_MAX_PAGES} páginas "
        f"de {_ADMIN_USERS_PER_PAGE} usuarios sin agotar el listado"
    )
