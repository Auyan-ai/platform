"""Webhook handler dedicado para Zendesk.

Flujo:
1. Recibir POST de Zendesk (disparado por un Trigger configurado en la cuenta).
2. Extraer subdomain del payload para resolver el tenant.
3. Descifrar credenciales + validar X-Zendesk-Webhook-Signature (si configurado).
4. Ejecutar flujo inbound estándar (customer, conversación, mensaje, agente).
5. Si el agente responde: send_outbound al adapter de Zendesk.

Payload esperado (configurar en el Zendesk Trigger → Webhook). SOLO IDs:
    {
        "ticket_id":  "{{ticket.id}}",
        "comment_id": "{% for c in ticket.comments limit:1 %}{{c.id}}{% endfor %}",
        "subdomain":  "hardcoded-subdomain"
    }

    Nada de texto libre en el payload: Zendesk no escapa los placeholders y un
    comentario con comillas/saltos de línea rompe el JSON. El contenido, el autor
    y el requester se leen de la API (`ZendeskAdapter.fetch_inbound_comment`).
    Zendesk no tiene variable {{subdomain}}: se hardcodea una vez por cuenta.
    Campos extra del payload (content, requester_*…) se ignoran.

Idempotencia: por comentario (`zendesk:{ticket_id}:{comment_id}`, id real de la API).

Anti-loop: la respuesta pública del agente re-dispara el Trigger. Dos capas: la
condición del Trigger (Current user = end user) y aquí se ignora todo comentario
cuyo autor (según la API) no sea el requester, o que no sea público.

Seguridad HMAC:
    - Headers: X-Zendesk-Webhook-Signature + X-Zendesk-Webhook-Signature-Timestamp
    - Si webhook_signing_secret está en credentials, la firma se valida.
    - Sin secreto configurado, se acepta el webhook sin validación de firma.
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
    get_integration_by_zendesk_subdomain,
    get_integration_credentials_encrypted,
    get_tenant_by_id,
    get_tenant_configuration,
    insert_message,
    try_insert_idempotency_key,
    update_conversation_last_message,
)
from apps.api.integrations.base import InboundMessage, IntegrationContext
from apps.api.integrations.zendesk import (
    ZendeskAdapter,
    ZendeskInboundComment,
    verify_zendesk_signature,
)
from apps.api.services.agent_resolution import finalize_agent_resolution, send_agent_reply
from apps.api.services.conversations import reopen_if_resolved
from apps.api.services.helpdesk_escalation import push_escalation_to_helpdesk_safe
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
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="agent_service_not_ready")
    return svc


AgentServiceDep = Annotated["AgentService", Depends(get_agent_service)]


def _placeholder_value(value: Any) -> str | None:
    """Normaliza un campo del payload del Trigger.

    Zendesk deja vacío un placeholder sin valor y manda literal uno que no
    reconoce (`{{...}}` / `{%...%}`): ambos casos cuentan como ausente.
    """
    text = str(value if value is not None else "").strip()
    if not text or "{{" in text or "{%" in text:
        return None
    return text


def _parse_payload(raw_body: bytes) -> dict[str, Any] | None:
    """JSON del webhook; None si no es un objeto JSON válido."""
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _ignore_reason(comment: ZendeskInboundComment) -> str | None:
    """Motivo para no procesar el comentario, o None si es del cliente final."""
    if not comment.public:
        return "private_comment"
    if not comment.from_requester:
        return "non_requester_comment"
    if not comment.content.strip():
        return "empty_content"
    return None


@router.post(
    "/zendesk",
    status_code=status.HTTP_200_OK,
    summary="Webhook inbound de Zendesk — dispara el agente para mensajes del cliente",
)
async def zendesk_webhook(
    request: Request,
    settings: SettingsDep,
    agent_service: AgentServiceDep,
) -> dict[str, Any]:
    raw_body = await request.body()
    payload = _parse_payload(raw_body)
    if payload is None:
        logger.warning("zendesk_webhook_invalid_json", extra={"body_bytes": len(raw_body)})
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid_json")

    # 1. Extraer subdomain para resolver el tenant + ticket_id.
    subdomain: str = str(payload.get("subdomain") or "").strip()
    if not subdomain:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="missing_subdomain")
    zendesk_ticket_id = _placeholder_value(payload.get("ticket_id"))
    if zendesk_ticket_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="missing_ticket_id")

    # 3. Resolver tenant por subdomain.
    async with bootstrap_connection() as conn:
        integration = await get_integration_by_zendesk_subdomain(conn, subdomain=subdomain)
    if integration is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="integration_not_found")

    tenant_id = integration.tenant_id

    # 4. Descifrar credenciales.
    async with bootstrap_connection() as conn:
        encrypted = await get_integration_credentials_encrypted(
            conn, tenant_id=tenant_id, integration_id=integration.id
        )
    if encrypted is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="credentials_not_found")
    crypto_key = get_integration_crypto_key(settings)
    credentials = json.loads(decrypt_credentials(encrypted, crypto_key).decode())

    # 5. Validar firma HMAC opcional.
    signing_secret = credentials.get("webhook_signing_secret", "")
    if signing_secret:
        sig_header = request.headers.get("X-Zendesk-Webhook-Signature", "")
        sig_ts = request.headers.get("X-Zendesk-Webhook-Signature-Timestamp", "")
        if not sig_header or not sig_ts:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing_signature_headers")
        if not verify_zendesk_signature(
            signing_secret=signing_secret,
            timestamp=sig_ts,
            raw_body=raw_body,
            signature_header=sig_header,
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_signature")

    # Construir IntegrationContext para usar el adapter.
    ctx = IntegrationContext(
        tenant_id=tenant_id,
        credentials=credentials,
        config=integration.config,
    )

    # 6. Cargar tenant + rate limit + budget.
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

    # 7. Leer el comentario de la API (fuente de verdad de contenido y autor).
    adapter = ZendeskAdapter()
    trigger_comment_id = _placeholder_value(payload.get("comment_id"))
    if trigger_comment_id is None:
        logger.warning(
            "zendesk_webhook_without_comment_id",
            extra={"tenant_id": str(tenant_id), "ticket_id": zendesk_ticket_id},
        )
    comment = await adapter.fetch_inbound_comment(ctx, zendesk_ticket_id, trigger_comment_id)
    if comment is None:
        logger.warning(
            "zendesk_webhook_comment_not_found",
            extra={"tenant_id": str(tenant_id), "ticket_id": zendesk_ticket_id},
        )
        return {"received": True, "processed": False, "ignored": "comment_not_found"}
    ignore_reason = _ignore_reason(comment)
    if ignore_reason is not None:
        logger.info(
            "zendesk_webhook_ignored",
            extra={
                "tenant_id": str(tenant_id),
                "ticket_id": zendesk_ticket_id,
                "comment_id": comment.comment_id,
                "reason": ignore_reason,
            },
        )
        return {"received": True, "processed": False, "ignored": ignore_reason}

    # 8. Idempotencia por comentario de Zendesk.
    idempotency_key = f"zendesk:{zendesk_ticket_id}:{comment.comment_id}"
    idempotency_claimed = False

    async with bootstrap_connection() as conn:
        record = await try_insert_idempotency_key(
            conn,
            tenant_id=tenant_id,
            key=idempotency_key,
            request_path="/webhooks/zendesk",
        )
        if record is None:
            existing = await get_idempotency_record(conn, tenant_id=tenant_id, key=idempotency_key)
            if existing is not None and existing.status == "done":
                return {"received": True, "processed": False, "duplicate": True}
            raise HTTPException(status.HTTP_409_CONFLICT, detail="idempotency_key_in_flight")
        idempotency_claimed = True

    inbound_msg_model = InboundMessage(
        external_id=zendesk_ticket_id,
        channel="zendesk",
        content=comment.content,
        sender_email=comment.requester_email,
        sender_name=comment.requester_name,
        subject=comment.subject,
        raw_payload=payload,
    )
    customer_email: str | None = inbound_msg_model.sender_email
    customer_name: str | None = inbound_msg_model.sender_name

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

            # Find-or-create conversación por ticket_id de Zendesk.
            conversation = await find_conversation_by_external(
                conn, tenant_id, "zendesk", zendesk_ticket_id
            )
            if conversation is None:
                conversation = await create_conversation(
                    conn,
                    tenant_id=tenant_id,
                    end_customer_id=customer.id,
                    channel="zendesk",
                    external_id=zendesk_ticket_id,
                    subject=inbound_msg_model.subject,
                )
            else:
                # El cliente volvió a escribir: si estaba resuelta, reactivarla.
                conversation = await reopen_if_resolved(conn, tenant_id, conversation)

            inbound_db_msg = await insert_message(
                conn,
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                role="customer",
                direction="inbound",
                content=inbound_msg_model.content,
                metadata={
                    "channel": "zendesk",
                    "zendesk_ticket_id": zendesk_ticket_id,
                    "zendesk_comment_id": comment.comment_id,
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

        # 9. Disparar el grafo.
        if cap_outcome is not None:
            outcome = cap_outcome
        else:
            outcome = await agent_service.process_inbound(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                inbound_message_id=inbound_db_msg.id,
                inbound_message_content=inbound_msg_model.content,
                channel="zendesk",
                end_customer_id=customer.id,
            )

    except Exception:
        if idempotency_key and idempotency_claimed:
            async with bootstrap_connection() as conn:
                await delete_idempotency_key(conn, tenant_id=tenant_id, key=idempotency_key)
        raise

    logger.info(
        "zendesk_inbound_processed",
        extra={
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation.id),
            "decision": outcome.decision,
        },
    )

    # 10. Enviar el mensaje del agente de vuelta a Zendesk. Incluye el caso escalate
    #     (mensaje "en revisión"), no solo respond.
    delivered = False
    if outcome.response_text:
        delivered = await send_agent_reply(
            adapter,
            ctx,
            zendesk_ticket_id,
            outcome.response_text,
            tenant_id=tenant_id,
            provider="zendesk",
        )

    # Resolución autónoma: solo si la respuesta llegó al cliente se marca
    # 'resolved' + billing + cierre del ticket externo.
    if outcome.resolves_on_delivery:
        await finalize_agent_resolution(
            tenant_id=tenant_id, conversation=conversation, delivered=delivered, settings=settings
        )

    # Escalado: nota interna con el motivo + asignación al equipo CX del cliente.
    # Solo al crear la escalación. Best-effort.
    if outcome.escalation_created:
        await push_escalation_to_helpdesk_safe(
            tenant_id=tenant_id,
            conversation=conversation,
            reason=outcome.escalation_reason or "unspecified_escalation",
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
