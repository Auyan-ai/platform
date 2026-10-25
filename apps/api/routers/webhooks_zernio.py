"""Webhook de Zernio (WhatsApp) — `POST /webhooks/zernio` (ADR 0010).

Flujo (mismo patrón que Zendesk: validar, persistir, encolar y 200 inmediato):
1. JSON válido (400 si no). `webhook.test` → 200 sin más.
2. `account.accountId` → integración `(channel, zernio)` del tenant (cross-tenant por el
   índice único `tenant_integrations_unique_zernio_account`). Desconocida → 404.
3. Firma `X-Zernio-Signature` (HMAC-SHA256 hex del body) con el secreto del webhook del
   tenant. Sin firma o inválida → 401. Integración sin secreto → 500 + `logger.error`:
   Zernio siempre firma, nunca se acepta nada sin firma.
4. Tenant activo (403 si no).
5. Por evento:
   - `message.received` entrante de WhatsApp: `standby` (lo lleva Meta Business Agent) →
     ignorado; si no, rate limit + budget y `persist_and_enqueue_inbound` con
     idempotencia `zernio:{event_id}` (misma transacción).
   - Resto de eventos → los procesa `services/zernio_events.py` (estado de entrega, toma
     desde el móvil); cualquier evento desconocido → 200 `ignored`. **Nunca 4xx/5xx por un
     evento desconocido**: Zernio reintentaría y acabaría desactivando el webhook.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from apps.api.core.config import Settings, get_settings
from apps.api.db.client import bootstrap_connection
from apps.api.db.queries import (
    get_integration_by_zernio_account,
    get_integration_credentials_encrypted,
    get_tenant_by_id,
    get_tenant_configuration,
)
from apps.api.integrations.zernio import ZernioEvent, parse_zernio_event, verify_zernio_signature
from apps.api.services.demo_tenants import reject_demo_intake
from apps.api.services.inbound_intake import notify_inbound_worker, persist_and_enqueue_inbound
from apps.api.services.integrations_crypto import decrypt_credentials, get_integration_crypto_key
from apps.api.services.rate_limit import enforce_rate_limit
from apps.api.services.usage import check_tenant_budget
from apps.api.services.zernio_events import handle_zernio_status_event
from fastapi import APIRouter, Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SettingsDep = Annotated[Settings, Depends(get_settings)]

REQUEST_PATH = "/webhooks/zernio"
SIGNATURE_HEADERS = ("X-Zernio-Signature", "X-Late-Signature")


def _parse_payload(raw_body: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _signature_header(request: Request) -> str | None:
    for name in SIGNATURE_HEADERS:
        value = request.headers.get(name)
        if value:
            return value
    return None


def _ignored(reason: str, **extra: Any) -> dict[str, Any]:
    return {"received": True, "processed": False, "ignored": reason, **extra}


@router.post(
    "/zernio",
    status_code=status.HTTP_200_OK,
    summary="Webhook de Zernio (WhatsApp) — mensajes entrantes y estado de envíos",
)
async def zernio_webhook(request: Request, settings: SettingsDep) -> dict[str, Any]:
    raw_body = await request.body()
    payload = _parse_payload(raw_body)
    if payload is None:
        logger.warning("zernio_webhook_invalid_json", extra={"body_bytes": len(raw_body)})
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid_json")

    event = parse_zernio_event(payload)
    if event.event == "webhook.test":
        logger.info("zernio_webhook_test_received", extra={"event_id": event.event_id})
        return {"received": True, "test": True}

    if event.account_id is None:
        # Sin cuenta no hay tenant: no se procesa nada (tampoco se firma contra nada).
        logger.warning(
            "zernio_webhook_without_account",
            extra={"event": event.event, "event_id": event.event_id},
        )
        return _ignored("no_account")

    async with bootstrap_connection() as conn:
        integration = await get_integration_by_zernio_account(conn, account_id=event.account_id)
    if integration is None:
        logger.warning("zernio_webhook_unknown_account", extra={"event": event.event})
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="integration_not_found")
    tenant_id = integration.tenant_id

    async with bootstrap_connection() as conn:
        encrypted = await get_integration_credentials_encrypted(
            conn, tenant_id=tenant_id, integration_id=integration.id
        )
    if encrypted is None:
        logger.error("zernio_webhook_credentials_not_found", extra={"tenant_id": str(tenant_id)})
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="credentials_not_found")
    credentials = json.loads(
        decrypt_credentials(encrypted, get_integration_crypto_key(settings)).decode()
    )
    secret = str(credentials.get("webhook_secret") or "")
    if not secret:
        logger.error("zernio_webhook_secret_missing", extra={"tenant_id": str(tenant_id)})
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="webhook_secret_missing")
    signature = _signature_header(request)
    if signature is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing_signature")
    if not verify_zernio_signature(raw_body, secret, signature):
        logger.warning("zernio_webhook_invalid_signature", extra={"tenant_id": str(tenant_id)})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_signature")

    async with bootstrap_connection() as conn:
        tenant = await get_tenant_by_id(conn, tenant_id)
    reject_demo_intake(tenant, source="zernio")
    if tenant is None or tenant.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="tenant_inactive")

    if event.event_id is None:
        # Sin id no hay idempotencia: mejor no procesar que duplicar respuestas.
        logger.error("zernio_webhook_without_event_id", extra={"tenant_id": str(tenant_id)})
        return _ignored("no_event_id")

    if event.event == "message.received":
        return await _handle_message_received(
            request, event, tenant_id=tenant_id, settings=settings
        )

    return await handle_zernio_status_event(event, tenant_id=tenant_id, integration=integration)


async def _handle_message_received(
    request: Request,
    event: ZernioEvent,
    *,
    tenant_id: Any,
    settings: Settings,
) -> dict[str, Any]:
    message = event.message
    if message is None or event.conversation_id is None:
        logger.warning("zernio_message_without_body", extra={"tenant_id": str(tenant_id)})
        return _ignored("no_message")
    if message.direction != "incoming":
        return _ignored("not_incoming")
    if message.platform != "whatsapp":
        # Instagram/Facebook/TikTok van al backlog omnicanal: aún no se atienden.
        logger.info(
            "zernio_message_unsupported_platform",
            extra={"tenant_id": str(tenant_id), "platform": message.platform},
        )
        return _ignored("unsupported_platform")
    if event.standby:
        logger.info("zernio_message_standby", extra={"tenant_id": str(tenant_id)})
        return _ignored("standby")
    if not message.text.strip() and not message.attachments:
        return _ignored("empty_content")

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
            conn, tenant_id=tenant_id, tenant_config=tenant_config, settings=settings
        )

    sender = message.sender
    result = await persist_and_enqueue_inbound(
        tenant_id=tenant_id,
        channel="whatsapp",
        external_id=event.conversation_id,
        idempotency_key=f"zernio:{event.event_id}",
        request_path=REQUEST_PATH,
        content=message.text.strip(),
        customer_email=None,
        customer_name=sender.name,
        subject=None,
        customer_phone=sender.phone_e164,
        customer_external_id=sender.customer_external_id,
        message_metadata={
            "channel": "whatsapp",
            "zernio_event_id": event.event_id,
            "zernio_message_id": message.id,
            "zernio_platform_message_id": message.platform_message_id,
            "zernio_sent_at": message.sent_at.isoformat() if message.sent_at else None,
            # La descarga va en el worker (Meta borra la media: se baja al procesar).
            "zernio_attachments": [a.as_metadata() for a in message.attachments],
        },
    )
    if not result.duplicate:
        notify_inbound_worker(request)
    return result.response()
