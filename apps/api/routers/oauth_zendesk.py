"""OAuth 2.0 Authorization Code flow para Zendesk.

Endpoints:
  GET /oauth/zendesk/authorize   — inicia el flujo, requiere auth
  GET /oauth/zendesk/callback    — callback de Zendesk, sin auth (usa state para CSRF)

Flujo:
  1. super_admin o tenant_admin llama a /authorize?tenant_id=...&subdomain=...
  2. Recibe redirect 302 a Zendesk OAuth.
  3. Zendesk redirige al callback con ?code=...&state=...
  4. Callback verifica HMAC del state, intercambia code por token.
  5. Persiste token cifrado en tenant_integrations.
  6. Responde 200 con {ok: true} (o redirect a dashboard si se configura).

State format:
  {tenant_id}:{subdomain}:{timestamp}:{hmac_hex}

  HMAC = HMAC-SHA256(webhook_secret, "{tenant_id}:{subdomain}:{timestamp}")
  Expira a los 15 minutos.

Scopes Zendesk solicitados: read write
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

router = APIRouter(prefix="/oauth/zendesk", tags=["oauth"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
AuthDep = Annotated[AuthContext, Depends(get_auth_context)]

_STATE_TTL_SECONDS = 900  # 15 minutos
_ZENDESK_SCOPES = "read write"


# ─── Helpers de state ─────────────────────────────────────────────────────────


def _build_state(tenant_id: str, subdomain: str, secret: str) -> str:
    ts = str(int(time.time()))
    msg = f"{tenant_id}:{subdomain}:{ts}".encode()
    mac = hmac.new(key=secret.encode(), msg=msg, digestmod=hashlib.sha256).hexdigest()
    return f"{tenant_id}:{subdomain}:{ts}:{mac}"


def _verify_state(state: str, secret: str) -> tuple[str, str]:
    """Verifica el HMAC y la antigüedad del state.

    Returns:
        (tenant_id, subdomain) si es válido.

    Raises:
        ValidationFailed si el state es inválido o expirado.
    """
    parts = state.split(":")
    # UUID tiene 5 segmentos con guiones, subdomain sin colons, ts y mac = 4 partes
    # Formato real: {uuid}:{subdomain}:{ts}:{mac} — subdomain no tiene ":"
    if len(parts) != 4:
        raise ValidationFailed("invalid_oauth_state")

    tenant_id, subdomain, ts_str, received_mac = parts

    # Verificar antigüedad
    try:
        ts = int(ts_str)
    except ValueError as exc:
        raise ValidationFailed("invalid_oauth_state") from exc
    if time.time() - ts > _STATE_TTL_SECONDS:
        raise ValidationFailed("oauth_state_expired")

    # Verificar HMAC
    msg = f"{tenant_id}:{subdomain}:{ts_str}".encode()
    expected_mac = hmac.new(
        key=secret.encode(), msg=msg, digestmod=hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_mac, received_mac):
        raise ValidationFailed("invalid_oauth_state")

    return tenant_id, subdomain


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "/authorize",
    status_code=status.HTTP_302_FOUND,
    summary="Inicia el flujo OAuth de Zendesk para un tenant",
)
async def zendesk_authorize(
    tenant_id: str,
    subdomain: str,
    auth: AuthDep,
    settings: SettingsDep,
) -> RedirectResponse:
    """Redirige al usuario a Zendesk para autorizar la integración.

    Requiere estar autenticado como super_admin o como tenant_admin del tenant indicado.
    """
    if not settings.zendesk_oauth_client_id or not settings.zendesk_oauth_redirect_uri:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="zendesk_oauth_not_configured",
        )

    # Validar que el usuario puede conectar este tenant.
    if auth.role != "super_admin":
        if str(auth.tenant_id) != tenant_id:
            raise ForbiddenError("cannot_connect_other_tenant")

    # Validar que tenant_id es un UUID válido.
    try:
        UUID(tenant_id)
    except ValueError as exc:
        raise ValidationFailed("invalid_tenant_id") from exc

    state = _build_state(tenant_id, subdomain, settings.webhook_secret.get_secret_value())

    params = {
        "response_type": "code",
        "client_id": settings.zendesk_oauth_client_id,
        "scope": _ZENDESK_SCOPES,
        "state": state,
        "redirect_uri": settings.zendesk_oauth_redirect_uri,
    }
    authorize_url = (
        f"https://{subdomain}.zendesk.com/oauth/authorizations/new?"
        + urllib.parse.urlencode(params)
    )
    return RedirectResponse(url=authorize_url, status_code=status.HTTP_302_FOUND)


@router.get(
    "/callback",
    status_code=status.HTTP_200_OK,
    summary="Callback OAuth de Zendesk — intercambia code por token y persiste",
)
async def zendesk_callback(
    code: str,
    state: str,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Recibe el callback de Zendesk, valida state, intercambia code por token
    y persiste las credentials cifradas en tenant_integrations.

    Este endpoint NO requiere auth — el state HMAC es la defensa CSRF.
    """
    if not settings.zendesk_oauth_client_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="zendesk_oauth_not_configured",
        )
    if not settings.zendesk_oauth_client_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="zendesk_oauth_not_configured",
        )

    secret = settings.webhook_secret.get_secret_value()
    tenant_id_str, subdomain = _verify_state(state, secret)

    # Intercambio de código por token.
    token_url = f"https://{subdomain}.zendesk.com/oauth/tokens"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                token_url,
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": settings.zendesk_oauth_client_id,
                    "client_secret": settings.zendesk_oauth_client_secret.get_secret_value(),
                    "redirect_uri": settings.zendesk_oauth_redirect_uri,
                    "scope": _ZENDESK_SCOPES,
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            token_data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"zendesk_token_exchange_failed: {exc.response.status_code}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"zendesk_token_exchange_error: {exc}",
        ) from exc

    oauth_token: str = token_data["access_token"]
    tenant_id = UUID(tenant_id_str)

    # Cifrar y persistir en tenant_integrations.
    if not settings.integrations_secret_key:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="integrations_secret_key_not_configured",
        )

    crypto_key = get_integration_crypto_key(settings)
    credentials_plain = {"oauth_token": oauth_token}
    encrypted = encrypt_credentials(credentials_plain, crypto_key)
    config = {"subdomain": subdomain}

    async with tenant_scope(tenant_id) as conn:
        await upsert_integration(
            conn,
            tenant_id=tenant_id,
            kind="helpdesk",
            provider="zendesk",
            credentials_encrypted=encrypted,
            config=config,
            is_primary_for_kind=False,
        )

    return {"ok": True, "provider": "zendesk", "subdomain": subdomain}
