"""Auth con Supabase JWT.

Flujo de un request autenticado:
1. Cliente manda `Authorization: Bearer <jwt>` (JWT emitido por Supabase Auth).
2. `get_auth_context` lee el header del token para obtener el `kid` y el algoritmo.
3. Para ES256 (proyectos nuevos): busca la clave pública en el JWKS de Supabase (cache 1 h).
   Para HS256 (legacy): usa `SUPABASE_JWT_SECRET` de Settings.
4. Valida firma, audience y expiración.
5. Extrae `sub` (= id de `auth.users`, espejo en `public.users`).
6. Lookup en `public.users` para traer `tenant_id`, `role`, `email` (con cache TTL).
7. Devuelve `AuthContext`.

Tenant scope:
- `tenant_admin` / `tenant_agent` → su propio `tenant_id`. Si manda `X-Tenant-Id`
  distinto, 403 (cross-tenant access).
- `super_admin` → `tenant_id` queda None en el AuthContext. Para endpoints que
  requieren scope, debe pasar el header `X-Tenant-Id` con el target.

Cache de usuarios:
- `TTLCache(maxsize=settings.auth_user_cache_maxsize, ttl=settings.auth_user_cache_ttl_seconds)`.
- Maxsize acota memoria; ttl invalida cambios de role/tenant tras el TTL.
- `reset_user_cache()` expuesto para tests.

Cache de JWKS:
- Dict plano con TTL manual (`supabase_jwks_cache_ttl_seconds`, default 1 h).
- Re-fetch automático si el kid no está en cache (manejo de rotación de claves).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import httpx
import jwt
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from apps.api.core.config import Settings, get_settings
from apps.api.core.errors import ForbiddenError, UnauthorizedError
from apps.api.db.client import bootstrap_connection
from apps.api.db.models import UserRole
from apps.api.db.queries import get_user_for_auth
from cachetools import TTLCache
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


# ----------------------------------------------------------------
# Tipos
# ----------------------------------------------------------------


@dataclass(frozen=True)
class UserRecord:
    """Lo mínimo que cacheamos por usuario."""

    tenant_id: UUID | None
    role: UserRole
    email: str


@dataclass(frozen=True)
class AuthContext:
    """Identidad y permisos del request autenticado."""

    user_id: UUID
    tenant_id: UUID | None  # None sólo para super_admin
    role: UserRole
    email: str


# ----------------------------------------------------------------
# Cache de usuarios
# ----------------------------------------------------------------

_user_cache: TTLCache[UUID, UserRecord] | None = None


def _get_user_cache(settings: Settings) -> TTLCache[UUID, UserRecord]:
    global _user_cache
    if _user_cache is None:
        _user_cache = TTLCache(
            maxsize=settings.auth_user_cache_maxsize,
            ttl=settings.auth_user_cache_ttl_seconds,
        )
    return _user_cache


def reset_user_cache() -> None:
    """Limpia el cache. Para tests y para forzar refresh manual."""
    global _user_cache
    _user_cache = None


async def _lookup_user(user_id: UUID, settings: Settings) -> UserRecord | None:
    cache = _get_user_cache(settings)
    cached = cache.get(user_id)
    if cached is not None:
        return cached

    async with bootstrap_connection() as conn:
        result = await get_user_for_auth(conn, user_id)

    if result is None:
        return None

    record = UserRecord(tenant_id=result[0], role=result[1], email=result[2])
    cache[user_id] = record
    return record


# ----------------------------------------------------------------
# Cache de JWKS (claves públicas para ES256 / RS256)
# ----------------------------------------------------------------


@dataclass
class _JwksCache:
    keys: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime | None = None


_jwks_cache = _JwksCache()


def reset_jwks_cache() -> None:
    """Limpia el cache de JWKS. Para tests."""
    global _jwks_cache
    _jwks_cache = _JwksCache()


def _key_from_jwk(jwk: dict[str, Any]) -> Any:
    alg = jwk.get("alg", "")
    if alg.startswith("ES"):
        return ECAlgorithm.from_jwk(jwk)
    if alg.startswith("RS"):
        return RSAAlgorithm.from_jwk(jwk)
    raise ValueError(f"unsupported_jwk_alg:{alg}")


async def _get_jwks_key(kid: str | None, settings: Settings) -> Any:
    """Devuelve la clave pública del JWKS para el kid dado.

    Refresca el cache si expiró o si el kid no está presente (rotación de claves).
    """
    now = datetime.now(UTC)
    ttl = settings.supabase_jwks_cache_ttl_seconds

    cache_stale = (
        _jwks_cache.fetched_at is None
        or (now - _jwks_cache.fetched_at).total_seconds() > ttl
    )

    if cache_stale or kid not in _jwks_cache.keys:
        jwks_url = str(settings.supabase_url).rstrip("/") + "/auth/v1/.well-known/jwks.json"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(jwks_url)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise UnauthorizedError("jwks_fetch_failed", code="jwks_fetch_failed") from exc

        new_keys: dict[str, Any] = {}
        for jwk in resp.json().get("keys", []):
            try:
                new_keys[jwk["kid"]] = _key_from_jwk(jwk)
            except Exception:
                logger.warning("jwks_skip_unsupported_key kid=%s", jwk.get("kid"))

        _jwks_cache.keys = new_keys
        _jwks_cache.fetched_at = now

    key = _jwks_cache.keys.get(kid or "")
    if key is None:
        raise UnauthorizedError("unknown_jwt_kid", code="unknown_jwt_kid")
    return key


# ----------------------------------------------------------------
# Dependencies
# ----------------------------------------------------------------


async def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("missing_bearer_token", code="missing_bearer_token")

    token = credentials.credentials

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("invalid_token", code="invalid_token") from exc

    alg = header.get("alg", settings.supabase_jwt_algorithm)
    kid = header.get("kid")

    if alg in ("ES256", "RS256"):
        signing_key = await _get_jwks_key(kid, settings)
    elif alg == "HS256":
        if settings.supabase_jwt_secret is None:
            raise UnauthorizedError(
                "hs256_secret_not_configured", code="hs256_secret_not_configured"
            )
        signing_key = settings.supabase_jwt_secret.get_secret_value()
    else:
        raise UnauthorizedError(f"unsupported_algorithm:{alg}", code="unsupported_algorithm")

    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[alg],
            audience=settings.supabase_jwt_audience,
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("token_expired", code="token_expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise UnauthorizedError("invalid_audience", code="invalid_audience") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("invalid_token", code="invalid_token") from exc

    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError("token_missing_sub", code="token_missing_sub")
    try:
        user_id = UUID(str(sub))
    except (ValueError, TypeError) as exc:
        raise UnauthorizedError("token_sub_not_uuid", code="token_sub_not_uuid") from exc

    user = await _lookup_user(user_id, settings)
    if user is None:
        raise UnauthorizedError("user_not_provisioned", code="user_not_provisioned")

    # Defensa en profundidad: la DB tiene constraint `users_tenant_required`,
    # pero validar acá nos protege de drift de schema.
    if user.role != "super_admin" and user.tenant_id is None:
        raise UnauthorizedError("user_has_no_tenant", code="user_has_no_tenant")

    return AuthContext(
        user_id=user_id,
        tenant_id=user.tenant_id,
        role=user.role,
        email=user.email,
    )


async def get_tenant_id(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> UUID:
    """Resuelve el `tenant_id` efectivo para endpoints con scope.

    - tenant_admin / tenant_agent → su propio tenant. `X-Tenant-Id` distinto = 403.
    - super_admin → REQUIERE `X-Tenant-Id` para operar en algún tenant.
    """
    if auth.role == "super_admin":
        if not x_tenant_id:
            raise ForbiddenError(
                "super_admin_requires_x_tenant_id",
                code="super_admin_requires_x_tenant_id",
            )
        try:
            return UUID(x_tenant_id)
        except ValueError as exc:
            raise ForbiddenError("invalid_x_tenant_id", code="invalid_x_tenant_id") from exc

    # tenant_admin / tenant_agent — auth.tenant_id es UUID (validado en get_auth_context).
    if auth.tenant_id is None:
        raise ForbiddenError("user_has_no_tenant", code="user_has_no_tenant")
    if x_tenant_id:
        try:
            requested = UUID(x_tenant_id)
        except ValueError as exc:
            raise ForbiddenError("invalid_x_tenant_id", code="invalid_x_tenant_id") from exc
        if requested != auth.tenant_id:
            raise ForbiddenError(
                "cross_tenant_access_denied", code="cross_tenant_access_denied"
            )
    return auth.tenant_id


def require_role(*roles: UserRole) -> Callable[[AuthContext], Awaitable[None]]:
    """Dep factory: 403 si el rol del caller no está en `roles`.

    Uso:
        @router.post("/foo", dependencies=[Depends(require_role("tenant_admin"))])
        async def foo(...): ...
    """

    async def _checker(
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> None:
        if auth.role not in roles:
            raise ForbiddenError(
                f"requires_role: {','.join(roles)}", code="insufficient_role"
            )

    return _checker
