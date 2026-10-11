"""Webhook handler dedicado para Gorgias.

Flujo:
1. Recibir POST de Gorgias.
2. Filtrar: solo event.type=ticket-message-created y message.from_agent=false.
3. Resolver tenant por domain (config de tenant_integrations, cross-tenant).
4. Descifrar credenciales + validar X-Gorgias-Hmac-Sha256 (si configurado).
5. Persistir el mensaje + encolar el turno en una transacción → 200 inmediato.
6. El grafo y la respuesta (adapter de Gorgias) corren en el worker
   (`services/inbound_worker.py`).

Seguridad: si la integración tiene `webhook_signing_secret` en sus credenciales,
la request debe incluir `X-Gorgias-Hmac-Sha256` con la firma HMAC-SHA256
base64 del raw body.
Sin secret configurado se acepta el webhook sin validación de firma.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Annotated, Any

from apps.api.core.config import Settings, get_settings
from apps.api.db.client import bootstrap_connection
from apps.api.db.queries import (
    get_integration_by_gorgias_domain,
    get_integration_credentials_encrypted,
    get_tenant_by_id,
    get_tenant_configuration,
)
from apps.api.integrations.gorgias import GorgiasAdapter, verify_gorgias_signature
from apps.api.services.inbound_intake import notify_inbound_worker, persist_and_enqueue_inbound
from apps.api.services.integrations_crypto import decrypt_credentials, get_integration_crypto_key
from apps.api.services.rate_limit import enforce_rate_limit
from apps.api.services.usage import check_tenant_budget
from fastapi import APIRouter, Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _is_from_agent(value: Any) -> bool:
    """Coacciona el flag from_agent a bool.

    Gorgias puede enviarlo como booleano JSON o como string ("true"/"false"/
    "True"/"False") según cómo se renderice la plantilla del HTTP integration.
    Ausente o ambiguo → True (conservador: no procesar como mensaje de cliente,
    evita loops con las respuestas del propio agente).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def source_channel(message: dict[str, Any], ticket: dict[str, Any]) -> str | None:
    """Canal de origen (`email`, `chat`, `facebook`...): el del mensaje, o el del ticket."""
    value = message.get("channel") or ticket.get("channel")
    return str(value) if value else None


@router.post(
    "/gorgias",
    status_code=status.HTTP_200_OK,
    summary="Webhook inbound de Gorgias — dispara el agente para mensajes del cliente",
)
async def gorgias_webhook(
    request: Request,
    settings: SettingsDep,
) -> dict[str, Any]:
    raw_body = await request.body()
    payload: dict[str, Any] = await request.json()

    # 1. Filtrar: solo mensajes inbound del cliente.
    event_type = (payload.get("event") or {}).get("type", "")
    if event_type != "ticket-message-created":
        return {"received": True, "processed": False}

    data = payload.get("data") or {}
    message = data.get("message") or {}
    if _is_from_agent(message.get("from_agent", True)):
        return {"received": True, "processed": False}

    body_text = message.get("body_text") or ""
    if not body_text.strip():
        return {"received": True, "processed": False}

    # 2. Resolver tenant por domain del payload.
    domain = (payload.get("meta") or {}).get("domain", "")
    if not domain:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="missing_domain")

    async with bootstrap_connection() as conn:
        integration = await get_integration_by_gorgias_domain(conn, domain=domain)
    if integration is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="integration_not_found")

    tenant_id = integration.tenant_id

    # 3. Descifrar credenciales.
    async with bootstrap_connection() as conn:
        encrypted = await get_integration_credentials_encrypted(
            conn, tenant_id=tenant_id, integration_id=integration.id
        )
    if encrypted is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="credentials_not_found")
    crypto_key = get_integration_crypto_key(settings)
    credentials = json.loads(decrypt_credentials(encrypted, crypto_key).decode())

    # 4. Validar firma opcional.
    signing_secret = credentials.get("webhook_signing_secret", "")
    if signing_secret:
        received_sig = request.headers.get("X-Gorgias-Hmac-Sha256", "")
        if not received_sig or not verify_gorgias_signature(raw_body, signing_secret, received_sig):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_signature")

    # 5. Cargar tenant + rate limit + budget.
    async with bootstrap_connection() as conn:
        tenant = await get_tenant_by_id(conn, tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="tenant_inactive")

    async with bootstrap_connection() as conn:
        tenant_config = await get_tenant_configuration(conn, tenant_id)
        await enforce_rate_limit(
            conn,
            tenant_id=tenant_id,
            tenant_config=tenant_config,
            customer_id=None,
            settings=settings,
        )
        await check_tenant_budget(
            conn,
            tenant_id=tenant_id,
            tenant_config=tenant_config,
            settings=settings,
        )

    # 6. Persistir + encolar (idempotencia por ticket + mensaje, misma transacción) y ack.
    #    El grafo corre en el worker (services/inbound_worker.py).
    ticket = data.get("ticket") or {}
    ticket_id = str(ticket.get("id", "") or "")
    if not ticket_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="missing_ticket_id")
    message_id = str(message.get("id", "") or "")
    # Sin id de mensaje (plantilla incompleta): dedupe por hash del body.
    dedupe_ref = message_id or hashlib.sha256(raw_body).hexdigest()

    inbound_msg_model = await GorgiasAdapter().parse_inbound_webhook(payload)
    sender = message.get("sender") or {}
    result = await persist_and_enqueue_inbound(
        tenant_id=tenant_id,
        channel="gorgias",
        external_id=ticket_id,
        idempotency_key=f"gorgias:{ticket_id}:{dedupe_ref}",
        request_path="/webhooks/gorgias",
        content=inbound_msg_model.content,
        customer_email=sender.get("email"),
        customer_name=sender.get("name"),
        subject=ticket.get("subject"),
        message_metadata={
            "channel": "gorgias",
            "gorgias_ticket_id": ticket_id,
            "gorgias_message_id": message_id,
            "source_channel": source_channel(message, ticket),
        },
    )
    if not result.duplicate:
        notify_inbound_worker(request)
    return result.response()
