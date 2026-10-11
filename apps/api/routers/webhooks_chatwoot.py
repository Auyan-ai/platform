"""Webhook handler dedicado para Chatwoot.

Flujo:
1. Recibir POST de Chatwoot.
2. Filtrar: solo event=message_created + message_type=incoming.
3. Resolver tenant por account_id (config de tenant_integrations, cross-tenant).
4. Descifrar credenciales + validar firma HMAC de Chatwoot (si configurado).
5. Persistir el mensaje + encolar el turno en una transacción → 200 inmediato.
6. El grafo y la respuesta (adapter de Chatwoot) corren en el worker
   (`services/inbound_worker.py`).

Seguridad: si la integración tiene `webhook_secret_token` en sus credenciales,
la request debe incluir `X-Chatwoot-Signature` + `X-Chatwoot-Timestamp`.
Sin token configurado se acepta el webhook sin validación de firma.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Annotated, Any

from apps.api.core.config import Settings, get_settings
from apps.api.db.client import bootstrap_connection
from apps.api.db.queries import (
    get_integration_by_chatwoot_account,
    get_integration_credentials_encrypted,
    get_tenant_by_id,
    get_tenant_configuration,
)
from apps.api.integrations.chatwoot import ChatwootAdapter, verify_chatwoot_signature
from apps.api.services.inbound_intake import notify_inbound_worker, persist_and_enqueue_inbound
from apps.api.services.integrations_crypto import decrypt_credentials, get_integration_crypto_key
from apps.api.services.rate_limit import enforce_rate_limit
from apps.api.services.usage import check_tenant_budget
from fastapi import APIRouter, Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _source_channel(payload: dict[str, Any]) -> str | None:
    """Tipo de canal de la bandeja de origen (`Channel::Email`, `Channel::WebWidget`...).

    Chatwoot lo expone en `conversation.channel`; según versión también en
    `inbox.channel_type` o `conversation.meta.channel`."""
    conversation = payload.get("conversation") or {}
    candidates = (
        conversation.get("channel"),
        (payload.get("inbox") or {}).get("channel_type"),
        (conversation.get("meta") or {}).get("channel"),
    )
    return next((str(c) for c in candidates if c), None)


@router.post(
    "/chatwoot",
    status_code=status.HTTP_200_OK,
    summary="Webhook inbound de Chatwoot — dispara el agente para mensajes del cliente",
)
async def chatwoot_webhook(
    request: Request,
    settings: SettingsDep,
) -> dict[str, Any]:
    raw_body = await request.body()
    payload: dict[str, Any] = await request.json()

    # 1. Filtrar: solo procesar mensajes inbound del cliente.
    event = payload.get("event")
    message_type = payload.get("message_type")
    if event != "message_created" or message_type != "incoming":
        return {"received": True, "processed": False}

    content = payload.get("content") or ""
    if not content.strip():
        return {"received": True, "processed": False}

    # 2. Resolver tenant por account_id del payload.
    account_id = str((payload.get("account") or {}).get("id", ""))
    if not account_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="missing_account_id")

    async with bootstrap_connection() as conn:
        integration = await get_integration_by_chatwoot_account(conn, account_id=account_id)
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

    # 4. Validar firma HMAC opcional.
    signing_secret = credentials.get("webhook_secret_token", "")
    if signing_secret:
        sig_header = request.headers.get("X-Chatwoot-Signature", "")
        sig_ts = request.headers.get("X-Chatwoot-Timestamp", "")
        if sig_header and sig_ts:
            if not verify_chatwoot_signature(
                signing_secret=signing_secret,
                timestamp=sig_ts,
                raw_body=raw_body,
                signature_header=sig_header,
            ):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_signature")
        else:
            # Legacy/self-hosted fallback used by the initial 0.4 integration.
            signature_token = request.headers.get("X-Chatwoot-Signature-Token", "")
            if not signature_token:
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED, detail="missing_signature_headers"
                )
            if not hmac.compare_digest(signature_token, signing_secret):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_signature_token")

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

    # 6. Persistir + encolar (idempotencia por mensaje, misma transacción) y ack.
    #    El grafo corre en el worker (services/inbound_worker.py).
    chatwoot_conversation_id = str((payload.get("conversation") or {}).get("id", "") or "")
    if not chatwoot_conversation_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="missing_conversation_id")
    chatwoot_message_id = str(payload.get("id", "") or "")
    # Sin id de mensaje: dedupe por hash del body.
    dedupe_ref = chatwoot_message_id or hashlib.sha256(raw_body).hexdigest()

    inbound_msg_model = await ChatwootAdapter().parse_inbound_webhook(payload)
    sender = payload.get("sender") or {}
    result = await persist_and_enqueue_inbound(
        tenant_id=tenant_id,
        channel="chatwoot",
        external_id=chatwoot_conversation_id,
        idempotency_key=f"chatwoot:{dedupe_ref}",
        request_path="/webhooks/chatwoot",
        content=inbound_msg_model.content,
        customer_email=sender.get("email"),
        customer_name=sender.get("name"),
        subject=None,
        message_metadata={
            "channel": "chatwoot",
            "chatwoot_message_id": chatwoot_message_id,
            "source_channel": _source_channel(payload),
        },
    )
    if not result.duplicate:
        notify_inbound_worker(request)
    return result.response()
