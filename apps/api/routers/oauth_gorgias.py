"""OAuth 2.0 Authorization Code flow para Gorgias.

Endpoints:
  GET /oauth/gorgias/authorize   — inicia el flujo, requiere auth
  GET /oauth/gorgias/callback    — callback de Gorgias, sin auth (usa state para CSRF)

Flujo:
  1. super_admin o tenant_admin llama a /authorize?tenant_id=...&domain=...
  2. Recibe redirect 302 a Gorgias OAuth.
  3. Gorgias redirige al callback con ?code=...&state=...
  4. Callback verifica HMAC del state, intercambia code por token.
  5. Persiste token cifrado en tenant_integrations.
  6. Responde 200 con {ok: true}.

State format:
  {tenant_id}:{domain}:{timestamp}:{hmac_hex}

  HMAC = HMAC-SHA256(webhook_secret, "{tenant_id}:{domain}:{timestamp}")
  Expira a los 15 minutos.

Scopes Gorgias solicitados: openid email profile write:all
"""

from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse
from typing import Annotated, Any
from uuid import UUID

import httpx
from apps.api.core.config import Settings, get_settings
from apps.api.core.errors import ForbiddenError, ValidationFailed
from apps.api.core.security import AuthContext, get_auth_context
from apps.api.db.client import tenant_scope
from apps.api.db.queries import upsert_integration
from apps.api.services.integrations_crypto import encrypt_credentials, get_integration_crypto_key
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/oauth/gorgias", tags=["oauth"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
AuthDep = Annotated[AuthContext, Depends(get_auth_context)]

_STATE_TTL_SECONDS = 900  # 15 minutos
_GORGIAS_SCOPES = "openid email profile write:all"


# ─── Helpers de state ─────────────────────────────────────────────────────────


def _build_state(tenant_id: str, domain: str, secret: str) -> str:
    ts = str(int(time.time()))
    msg = f"{tenant_id}:{domain}:{ts}".encode()
    mac = hmac.new(key=secret.encode(), msg=msg, digestmod=hashlib.sha256).hexdigest()
    return f"{tenant_id}:{domain}:{ts}:{mac}"


def _verify_state(state: str, secret: str) -> tuple[str, str]:
    """Verifica el HMAC y la antigüedad del state.

    Returns:
        (tenant_id, domain) si es válido.

    Raises:
        ValidationFailed si el state es inválido o expirado.
    """
    parts = state.split(":")
    if len(parts) != 4:
        raise ValidationFailed("invalid_oauth_state")

    tenant_id, domain, ts_str, received_mac = parts

    try:
        ts = int(ts_str)
    except ValueError as exc:
        raise ValidationFailed("invalid_oauth_state") from exc
    if time.time() - ts > _STATE_TTL_SECONDS:
        raise ValidationFailed("oauth_state_expired")

    msg = f"{tenant_id}:{domain}:{ts_str}".encode()
    expected_mac = hmac.new(
        key=secret.encode(), msg=msg, digestmod=hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_mac, received_mac):
        raise ValidationFailed("invalid_oauth_state")

    return tenant_id, domain


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "/authorize",
    status_code=status.HTTP_302_FOUND,
    summary="Inicia el flujo OAuth de Gorgias para un tenant",
)
async def gorgias_authorize(
    tenant_id: str,
    domain: str,
    auth: AuthDep,
    settings: SettingsDep,
) -> RedirectResponse:
    """Redirige al usuario a Gorgias para autorizar la integración.

    Requiere estar autenticado como super_admin o como tenant_admin del tenant indicado.
    """
    if not settings.gorgias_oauth_client_id or not settings.gorgias_oauth_redirect_uri:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="gorgias_oauth_not_configured",
        )

    if auth.role != "super_admin":
        if str(auth.tenant_id) != tenant_id:
            raise ForbiddenError("cannot_connect_other_tenant")

    try:
        UUID(tenant_id)
    except ValueError as exc:
        raise ValidationFailed("invalid_tenant_id") from exc

    state = _build_state(tenant_id, domain, settings.webhook_secret.get_secret_value())

    params = {
        "response_type": "code",
        "client_id": settings.gorgias_oauth_client_id,
        "scope": _GORGIAS_SCOPES,
        "state": state,
        "redirect_uri": settings.gorgias_oauth_redirect_uri,
    }
    authorize_url = (
        f"https://{domain}.gorgias.com/oauth/authorize?"
        + urllib.parse.urlencode(params)
    )
    return RedirectResponse(url=authorize_url, status_code=status.HTTP_302_FOUND)


@router.get(
    "/callback",
    status_code=status.HTTP_200_OK,
    summary="Callback OAuth de Gorgias — intercambia code por token y persiste",
)
async def gorgias_callback(
    code: str,
    state: str,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Recibe el callback de Gorgias, valida state, intercambia code por token
    y persiste las credentials cifradas en tenant_integrations.

    Este endpoint NO requiere auth — el state HMAC es la defensa CSRF.
    """
    if not settings.gorgias_oauth_client_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="gorgias_oauth_not_configured",
        )
    if not settings.gorgias_oauth_client_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="gorgias_oauth_not_configured",
        )

    secret = settings.webhook_secret.get_secret_value()
    tenant_id_str, domain = _verify_state(state, secret)

    token_url = f"https://{domain}.gorgias.com/oauth/token"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": settings.gorgias_oauth_client_id,
                    "client_secret": settings.gorgias_oauth_client_secret.get_secret_value(),
                    "redirect_uri": settings.gorgias_oauth_redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            token_data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"gorgias_token_exchange_failed: {exc.response.status_code}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"gorgias_token_exchange_error: {exc}",
        ) from exc

    oauth_token: str = token_data["access_token"]
    tenant_id = UUID(tenant_id_str)

    if not settings.integrations_secret_key:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="integrations_secret_key_not_configured",
        )

    crypto_key = get_integration_crypto_key(settings)
    credentials_plain = {"oauth_token": oauth_token}
    encrypted = encrypt_credentials(credentials_plain, crypto_key)
    config = {"domain": domain}

    async with tenant_scope(tenant_id) as conn:
        await upsert_integration(
            conn,
            tenant_id=tenant_id,
            kind="helpdesk",
            provider="gorgias",
            credentials_encrypted=encrypted,
            config=config,
            is_primary_for_kind=False,
        )

    return {"ok": True, "provider": "gorgias", "domain": domain}
