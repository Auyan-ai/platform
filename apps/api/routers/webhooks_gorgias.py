"""Webhook handler dedicado para Gorgias.

Flujo:
1. Recibir POST de Gorgias.
2. Filtrar: solo event.type=ticket-message-created y message.from_agent=false.
3. Resolver tenant por domain (config de tenant_integrations, cross-tenant).
4. Descifrar credenciales + validar X-Gorgias-Hmac-Sha256 (si configurado).
5. Ejecutar flujo inbound estándar (customer, conversación, mensaje, agente).
6. Si el agente responde: send_outbound al adapter de Gorgias.

Seguridad: si la integración tiene `webhook_signing_secret` en sus credenciales,
la request debe incluir `X-Gorgias-Hmac-Sha256` con la firma HMAC-SHA256
base64 del raw body.
Sin secret configurado se acepta el webhook sin validación de firma.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from apps.api.agents.service import AgentService
from apps.api.core.config import Settings, get_settings
from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.queries import (
    complete_idempotency_key,
    create_conversation,
    create_end_customer,
    delete_idempotency_key,
    find_conversation_by_external,
    find_end_customer_by_email,
    get_idempotency_record,
    get_integration_by_gorgias_domain,
    get_integration_credentials_encrypted,
    get_tenant_by_id,
    get_tenant_configuration,
    insert_message,
    try_insert_idempotency_key,
    update_conversation_last_message,
)
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.gorgias import GorgiasAdapter, verify_gorgias_signature
from apps.api.services.integrations_crypto import decrypt_credentials, get_integration_crypto_key
from apps.api.services.message_cap import enforce_message_cap
from apps.api.services.rate_limit import enforce_rate_limit
from apps.api.services.usage import UsageRecorder, check_tenant_budget
from fastapi import APIRouter, Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
_usage_recorder = UsageRecorder()

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_agent_service(request: Request) -> AgentService:
    svc = getattr(request.app.state, "agent_service", None)
    if svc is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="agent_service_not_ready"
        )
    return svc


AgentServiceDep = Annotated["AgentService", Depends(get_agent_service)]


@router.post(
    "/gorgias",
    status_code=status.HTTP_200_OK,
    summary="Webhook inbound de Gorgias — dispara el agente para mensajes del cliente",
)
async def gorgias_webhook(
    request: Request,
    settings: SettingsDep,
    agent_service: AgentServiceDep,
) -> dict[str, Any]:
    raw_body = await request.body()
    payload: dict[str, Any] = await request.json()

    # 1. Filtrar: solo mensajes inbound del cliente.
    event_type = (payload.get("event") or {}).get("type", "")
    if event_type != "ticket-message-created":
        return {"received": True, "processed": False}

    data = payload.get("data") or {}
    message = data.get("message") or {}
    if message.get("from_agent", True):
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
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="credentials_not_found"
        )
    crypto_key = get_integration_crypto_key(settings)
    credentials = json.loads(decrypt_credentials(encrypted, crypto_key).decode())

    # 4. Validar firma opcional.
    signing_secret = credentials.get("webhook_signing_secret", "")
    if signing_secret:
        received_sig = request.headers.get("X-Gorgias-Hmac-Sha256", "")
        if not received_sig or not verify_gorgias_signature(raw_body, signing_secret, received_sig):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_signature")

    ctx = IntegrationContext(
        tenant_id=tenant_id,
        credentials=credentials,
        config=integration.config,
    )

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

    # 6. Idempotencia usando el ticket_id + message_id de Gorgias.
    ticket = data.get("ticket") or {}
    ticket_id = str(ticket.get("id", ""))
    message_id = str(message.get("id", ""))
    idempotency_key = (
        f"gorgias:{ticket_id}:{message_id}" if ticket_id and message_id else None
    )
    idempotency_claimed = False

    if idempotency_key:
        async with bootstrap_connection() as conn:
            record = await try_insert_idempotency_key(
                conn,
                tenant_id=tenant_id,
                key=idempotency_key,
                request_path="/webhooks/gorgias",
            )
            if record is None:
                existing = await get_idempotency_record(
                    conn, tenant_id=tenant_id, key=idempotency_key
                )
                if existing is not None and existing.status == "done":
                    return {"received": True, "processed": False, "duplicate": True}
                raise HTTPException(status.HTTP_409_CONFLICT, detail="idempotency_key_in_flight")
            idempotency_claimed = True

    # 7. Extraer datos del mensaje y del sender.
    adapter = GorgiasAdapter()
    inbound_msg_model = await adapter.parse_inbound_webhook(payload)

    if not ticket_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="missing_ticket_id")

    sender = message.get("sender") or {}
    customer_email: str | None = sender.get("email")
    customer_name: str | None = sender.get("name")

    cap_outcome = None
    try:
        async with tenant_scope(tenant_id) as conn:
            # Upsert end_customer.
            customer = None
            if customer_email:
                customer = await find_end_customer_by_email(conn, tenant_id, customer_email)
            if customer is None:
                customer = await create_end_customer(
                    conn,
                    tenant_id=tenant_id,
                    email=customer_email,
                    external_id=None,
                    full_name=customer_name,
                )

            # Find-or-create conversación por ticket_id de Gorgias.
            conversation = await find_conversation_by_external(
                conn, tenant_id, "gorgias", ticket_id
            )
            if conversation is None:
                conversation = await create_conversation(
                    conn,
                    tenant_id=tenant_id,
                    end_customer_id=customer.id,
                    channel="gorgias",
                    external_id=ticket_id,
                    subject=ticket.get("subject"),
                )

            inbound_db_msg = await insert_message(
                conn,
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                role="customer",
                direction="inbound",
                content=inbound_msg_model.content,
                metadata={
                    "channel": "gorgias",
                    "gorgias_ticket_id": ticket_id,
                    "gorgias_message_id": message_id,
                },
            )
            await update_conversation_last_message(conn, tenant_id, conversation.id)

            cap_outcome = await enforce_message_cap(
                conn,
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                inbound_message_id=inbound_db_msg.id,
                tenant_config=tenant_config,
                settings=settings,
            )

        # 8. Disparar el grafo.
        if cap_outcome is not None:
            outcome = cap_outcome
        else:
            outcome = await agent_service.process_inbound(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                inbound_message_id=inbound_db_msg.id,
                inbound_message_content=inbound_msg_model.content,
                channel="gorgias",
                end_customer_id=customer.id,
            )

    except Exception:
        if idempotency_key and idempotency_claimed:
            async with bootstrap_connection() as conn:
                await delete_idempotency_key(conn, tenant_id=tenant_id, key=idempotency_key)
        raise

    logger.info(
        "gorgias_inbound_processed",
        extra={
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation.id),
            "decision": outcome.decision,
        },
    )

    # 9. Enviar respuesta del agente de vuelta a Gorgias.
    if outcome.decision == "respond" and outcome.response_text:
        try:
            await adapter.send_outbound(ctx, ticket_id, outcome.response_text)
        except Exception as exc:
            logger.error(
                "gorgias_send_outbound_failed",
                extra={"error": str(exc), "tenant_id": str(tenant_id)},
            )

    _usage_recorder.record(
        tenant_id=tenant_id,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
        cost_usd=outcome.cost_usd,
    )

    if idempotency_key and idempotency_claimed:
        async with bootstrap_connection() as conn:
            await complete_idempotency_key(
                conn,
                tenant_id=tenant_id,
                key=idempotency_key,
                response_status=200,
                response_body={"ok": True, "decision": outcome.decision},
            )

    return {"ok": True, "decision": outcome.decision}
