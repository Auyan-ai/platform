"""Webhook router para inbounds.

V1 expone un endpoint genérico `/webhooks/inbound` para testear end-to-end.
Webhooks específicos (Postmark, Zendesk, Intercom, Shopify) se montarán en
endpoints aparte y deben terminar llamando al MISMO flujo:

    1. Resolver tenant por algún identificador del payload.
    2. Upsert end_customer (por email o external_id).
    3. Find-or-create conversation (por (tenant, channel, external_id)).
    4. INSERT message inbound (role='customer').
    5. agent_service.process_inbound(...)
    6. Devolver AgentOutcome al adapter del canal para enviar la respuesta.

Seguridad: HMAC-SHA256 sobre el body, header `X-Auyan-Signature: sha256=<hex>`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Annotated, Any

from apps.api.agents.service import AgentService
from apps.api.core.config import Settings, get_settings
from apps.api.db.client import bootstrap_connection, tenant_scope
from apps.api.db.models import ChannelType
from apps.api.db.queries import (
    complete_idempotency_key,
    create_conversation,
    create_end_customer,
    delete_idempotency_key,
    find_conversation_by_external,
    find_conversation_by_id,
    find_end_customer_by_email,
    get_idempotency_record,
    get_tenant_by_slug,
    get_tenant_configuration,
    insert_message,
    try_insert_idempotency_key,
    update_conversation_last_message,
)
from apps.api.services.conversations import reopen_if_resolved
from apps.api.services.helpdesk_closure import close_external_helpdesk_ticket_safe
from apps.api.services.helpdesk_escalation import push_escalation_to_helpdesk_safe
from apps.api.services.message_cap import enforce_message_cap
from apps.api.services.rate_limit import enforce_rate_limit
from apps.api.services.usage import UsageRecorder, check_tenant_budget
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
_usage_recorder = UsageRecorder()


# ----------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------


class InboundPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_slug: str = Field(min_length=1, max_length=100)
    channel: ChannelType
    content: str = Field(min_length=1, max_length=20_000)

    conversation_id: str | None = None
    external_conversation_id: str | None = None
    external_customer_id: str | None = None
    customer_email: str | None = None
    customer_name: str | None = None
    subject: str | None = None


class InboundResponse(BaseModel):
    ok: bool
    decision: str
    conversation_id: str
    inbound_message_id: str
    output_message_id: str | None = None
    escalation_id: str | None = None
    response_text: str | None = None
    escalation_reason: str | None = None
    trace_id: str | None = None
    error: str | None = None


# ----------------------------------------------------------------
# HMAC verification
# ----------------------------------------------------------------


def _verify_signature(body: bytes, header_value: str, secret: str) -> bool:
    """HMAC-SHA256 sobre el body. Header esperado: `sha256=<hex>`."""
    if not header_value.startswith("sha256="):
        return False
    provided = header_value[len("sha256="):]
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


# ----------------------------------------------------------------
# Dependencies
# ----------------------------------------------------------------


def get_agent_service(request: Request) -> AgentService:
    svc = getattr(request.app.state, "agent_service", None)
    if svc is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="agent_service_not_ready"
        )
    return svc


SettingsDep = Annotated[Settings, Depends(get_settings)]
AgentServiceDep = Annotated["AgentService", Depends(get_agent_service)]


# ----------------------------------------------------------------
# Endpoint genérico (firma HMAC + flujo del agente)
# ----------------------------------------------------------------


@router.post(
    "/inbound",
    response_model=InboundResponse,
    status_code=status.HTTP_200_OK,
    summary="Inbound genérico — dispara el agente para un mensaje del cliente",
)
async def inbound(
    request: Request,
    settings: SettingsDep,
    agent_service: AgentServiceDep,
) -> InboundResponse:
    body = await request.body()

    signature_header = request.headers.get("X-Auyan-Signature", "")
    if not _verify_signature(
        body, signature_header, settings.webhook_secret.get_secret_value()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_signature")

    try:
        payload = InboundPayload.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"invalid_payload: {exc.errors()}"
        ) from exc

    # 1. Resolver tenant — sin tenant_scope todavía.
    async with bootstrap_connection() as conn:
        tenant = await get_tenant_by_slug(conn, payload.tenant_slug)
    if tenant is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"tenant_not_found: {payload.tenant_slug}"
        )
    if tenant.status != "active":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=f"tenant_not_active: status={tenant.status}"
        )

    # 2. Rate limiting + budget check — antes de idempotency y de tocar datos.
    async with bootstrap_connection() as conn:
        tenant_config = await get_tenant_configuration(conn, tenant.id)
        await enforce_rate_limit(
            conn,
            tenant_id=tenant.id,
            tenant_config=tenant_config,
            customer_id=None,  # todavía no conocemos el customer_id
            settings=settings,
        )
        await check_tenant_budget(
            conn,
            tenant_id=tenant.id,
            tenant_config=tenant_config,
            settings=settings,
        )

    # 3. Idempotencia — si viene X-Idempotency-Key, deduplicamos antes de tocar datos.
    idempotency_key = request.headers.get("X-Idempotency-Key")
    idempotency_claimed = False

    if idempotency_key:
        async with bootstrap_connection() as conn:
            record = await try_insert_idempotency_key(
                conn,
                tenant_id=tenant.id,
                key=idempotency_key,
                request_path="/webhooks/inbound",
            )
            if record is None:
                # Ya existe — buscar el registro actual
                existing = await get_idempotency_record(
                    conn, tenant_id=tenant.id, key=idempotency_key
                )
                if existing is not None and existing.status == "done" and existing.response_body:
                    # Devolver respuesta cacheada sin re-procesar
                    logger.info(
                        "idempotency_cache_hit",
                        extra={"tenant_id": str(tenant.id), "key": idempotency_key},
                    )
                    return InboundResponse.model_validate(existing.response_body)
                # Pending (en vuelo) o expirado sin respuesta → conflicto
                raise HTTPException(
                    status.HTTP_409_CONFLICT, detail="idempotency_key_in_flight"
                )
            idempotency_claimed = True

    # 4. Dentro del tenant_scope: customer, conversación, mensaje inbound.
    cap_outcome = None
    try:
        async with tenant_scope(tenant.id) as conn:
            customer = None
            if payload.customer_email:
                customer = await find_end_customer_by_email(
                    conn, tenant.id, payload.customer_email
                )
            if customer is None:
                customer = await create_end_customer(
                    conn,
                    tenant_id=tenant.id,
                    email=payload.customer_email,
                    external_id=payload.external_customer_id,
                    full_name=payload.customer_name,
                )

            conversation = None
            if payload.conversation_id:
                conversation = await find_conversation_by_id(
                    conn, tenant.id, payload.conversation_id
                )
            if conversation is None and payload.external_conversation_id:
                conversation = await find_conversation_by_external(
                    conn, tenant.id, payload.channel, payload.external_conversation_id
                )
            if conversation is None:
                conversation = await create_conversation(
                    conn,
                    tenant_id=tenant.id,
                    end_customer_id=customer.id,
                    channel=payload.channel,
                    external_id=payload.external_conversation_id,
                    subject=payload.subject,
                )
            else:
                # El cliente volvió a escribir: si estaba resuelta, reactivarla.
                conversation = await reopen_if_resolved(conn, tenant.id, conversation)

            inbound_msg = await insert_message(
                conn,
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                role="customer",
                direction="inbound",
                content=payload.content,
                metadata={"channel": payload.channel},
            )
            await update_conversation_last_message(conn, tenant.id, conversation.id)

            # 4b. Message cap — escala automáticamente si la conversación excedió el límite.
            cap_outcome = await enforce_message_cap(
                conn,
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                inbound_message_id=inbound_msg.id,
                tenant_config=tenant_config,
                settings=settings,
            )

        # 5. Disparar el grafo (o usar el outcome del cap si aplica).
        if cap_outcome is not None:
            outcome = cap_outcome
        else:
            outcome = await agent_service.process_inbound(
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                inbound_message_id=inbound_msg.id,
                inbound_message_content=payload.content,
                channel=payload.channel,
                end_customer_id=customer.id,
            )

    except Exception:
        # Si el procesamiento falla, liberar la key para que el reintento sea válido.
        if idempotency_key and idempotency_claimed:
            async with bootstrap_connection() as conn:
                await delete_idempotency_key(conn, tenant_id=tenant.id, key=idempotency_key)
        raise

    logger.info(
        "inbound_processed",
        extra={
            "tenant_id": str(tenant.id),
            "conversation_id": str(conversation.id),
            "decision": outcome.decision,
            "trace_id": outcome.trace_id,
        },
    )

    # Resolución autónoma: cerrar el ticket externo si hay helpdesk (no-op para
    # canales de prueba sin helpdesk). Best-effort.
    if outcome.resolved:
        await close_external_helpdesk_ticket_safe(
            tenant_id=tenant.id, conversation=conversation, settings=settings
        )

    # Escalado: nota interna con el motivo + asignación al equipo CX del cliente,
    # solo al crear la escalación (no-op para canales sin helpdesk). Best-effort.
    if outcome.escalation_created:
        await push_escalation_to_helpdesk_safe(
            tenant_id=tenant.id,
            conversation=conversation,
            reason=outcome.escalation_reason or "unspecified_escalation",
        )

    # 6. Registrar uso (fire-and-forget, no bloquea la respuesta).
    _usage_recorder.record(
        tenant_id=tenant.id,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
        cost_usd=outcome.cost_usd,
    )

    response = InboundResponse(
        ok=True,
        decision=outcome.decision,
        conversation_id=str(conversation.id),
        inbound_message_id=str(inbound_msg.id),
        output_message_id=outcome.output_message_id,
        escalation_id=outcome.escalation_id,
        response_text=outcome.response_text,
        escalation_reason=outcome.escalation_reason,
        trace_id=outcome.trace_id,
        error=outcome.error,
    )

    # 5. Marcar la key como done y cachear la respuesta.
    if idempotency_key and idempotency_claimed:
        async with bootstrap_connection() as conn:
            await complete_idempotency_key(
                conn,
                tenant_id=tenant.id,
                key=idempotency_key,
                response_status=200,
                response_body=response.model_dump(mode="json"),
            )

    return response


# ----------------------------------------------------------------
# Stubs de webhooks específicos por canal (heredados de PR #4)
# Por ahora solo aceptan el payload y loguean. La integración real con cada
# canal queda como deuda — debe terminar llamando al mismo flujo de `inbound`
# (resolver tenant, persistir mensaje, invocar agent_service).
# ----------------------------------------------------------------


@router.post("/zendesk")
async def zendesk_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    payload = await request.json()
    logger.info("zendesk_webhook_received", extra={"payload_keys": list(payload.keys())})
    # TODO Sprint 2: procesar en background_tasks llamando a agent_service
    return {"received": True}


@router.post("/postmark")
async def postmark_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    payload: dict[str, Any] = await request.json()
    logger.info("postmark_webhook_received", extra={"from": payload.get("From")})
    return {"received": True}
