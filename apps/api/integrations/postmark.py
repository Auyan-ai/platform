"""Adapter HTTP para Postmark — email outbound de Auyan → cliente.

Dos capas:
- `PostmarkClient`: cliente HTTP stateful (server_token en __init__). Retry automático
  sobre errores transitorios (5xx, 429, timeouts).
- `PostmarkEmailAdapter`: wrapper de alto nivel, instanciado una vez en startup con las
  credenciales globales de Auyan. Las credenciales son de Auyan, no del tenant — Postmark
  es para emails Auyan→cliente (escalación fallback, reportes, notificaciones lifecycle).

`build_postmark_adapter(settings)` devuelve None si POSTMARK_API_TOKEN no está configurado,
permitiendo que el sistema arranque sin Postmark en desarrollo local.

NO es un canal bidireccional: no hay parse_inbound_webhook.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

if TYPE_CHECKING:
    from apps.api.core.config import Settings

logger = logging.getLogger(__name__)

POSTMARK_API_URL = "https://api.postmarkapp.com"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


# ─── Marcador de error transitorio ────────────────────────────────────────────


class _TransientError(Exception):
    """Señal interna para tenacity: reintenta sobre este tipo de error."""


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, httpx.TimeoutException | httpx.ConnectError | _TransientError)


# ─── Cliente HTTP ──────────────────────────────────────────────────────────────


class PostmarkClient:
    """Cliente HTTP para Postmark API. Stateful: guarda server_token."""

    def __init__(self, server_token: str) -> None:
        self._token = server_token

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Postmark-Server-Token": self._token,
        }

    async def send_email(
        self,
        *,
        to: str,
        from_field: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        """Envía un email via Postmark con retry en errores transitorios."""
        payload: dict[str, Any] = {
            "From": from_field,
            "To": to,
            "Subject": subject,
            "TextBody": text_body,
        }
        if html_body:
            payload["HtmlBody"] = html_body
        if tag:
            payload["Tag"] = tag

        async for attempt in AsyncRetrying(
            retry=retry_if_exception(_is_transient),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        ):
            with attempt:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        f"{POSTMARK_API_URL}/email",
                        headers=self._headers(),
                        json=payload,
                    )
                    if resp.status_code in _RETRYABLE_STATUS:
                        raise _TransientError(f"http_{resp.status_code}")
                    resp.raise_for_status()
                    return resp.json()  # type: ignore[no-any-return]

        raise RuntimeError("unreachable")  # tenacity reraise=True lo maneja


# ─── Adapter de alto nivel ─────────────────────────────────────────────────────


class PostmarkEmailAdapter:
    """Adapter stateful para emails outbound de Auyan.

    Instanciar una vez en startup vía `build_postmark_adapter(settings)`.
    Las credenciales son globales de Auyan — no hay IntegrationContext per-tenant.
    """

    def __init__(
        self,
        server_token: str,
        from_email: str,
        from_name: str = "Auyan",
    ) -> None:
        self._client = PostmarkClient(server_token=server_token)
        self._from_email = from_email
        self._from_name = from_name

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        """Envía un email desde la cuenta Auyan configurada."""
        from_field = f"{self._from_name} <{self._from_email}>"
        return await self._client.send_email(
            to=to,
            from_field=from_field,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            tag=tag,
        )


# ─── Factory ───────────────────────────────────────────────────────────────────


def build_postmark_adapter(settings: Settings) -> PostmarkEmailAdapter | None:
    """Crea un PostmarkEmailAdapter si POSTMARK_API_TOKEN está configurado.

    Devuelve None en desarrollo local sin token. El EmailSender maneja el None
    como no-op (no envía email, loguea warning).
    """
    if not settings.postmark_api_token:
        return None
    return PostmarkEmailAdapter(
        server_token=settings.postmark_api_token.get_secret_value(),
        from_email=settings.postmark_from_email,
        from_name=settings.postmark_from_name,
    )
