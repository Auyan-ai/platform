"""Webhook handler dedicado para Zendesk.

Flujo:
1. Recibir POST de Zendesk (disparado por un Trigger configurado en la cuenta).
2. Extraer subdomain del payload para resolver el tenant.
3. Descifrar credenciales + validar X-Zendesk-Webhook-Signature (si configurado).
4. Leer el comentario de la API, filtrar (solo públicos del requester).
5. Persistir el mensaje + encolar el turno en una transacción → 200 inmediato.
   El grafo y la respuesta al ticket corren en el worker (`services/inbound_worker.py`).

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

Idempotencia: por comentario (`zendesk:{ticket_id}:{comment_id}`, id real de la API),
reclamada en la misma transacción que persiste y encola: un reintento de Zendesk
(incluso concurrente) sale como duplicado; si la transacción cae, se reprocesa limpio.

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

from apps.api.core.config import Settings, get_settings
from apps.api.db.client import bootstrap_connection
from apps.api.db.queries import (
    get_integration_by_zendesk_subdomain,
    get_integration_credentials_encrypted,
    get_tenant_by_id,
    get_tenant_configuration,
)
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.zendesk import (
    ZendeskAdapter,
    ZendeskInboundComment,
    verify_zendesk_signature,
)
from apps.api.services.inbound_intake import notify_inbound_worker, persist_and_enqueue_inbound
from apps.api.services.integrations_crypto import decrypt_credentials, get_integration_crypto_key
from apps.api.services.rate_limit import enforce_rate_limit
from apps.api.services.usage import check_tenant_budget
from fastapi import APIRouter, Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


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

    # 8. Persistir + encolar (idempotencia por comentario, misma transacción) y ack.
    #    El grafo corre en el worker (services/inbound_worker.py): Zendesk corta a
    #    ~10 s y reintenta, y un turno con supervisor puede tardar más.
    result = await persist_and_enqueue_inbound(
        tenant_id=tenant_id,
        channel="zendesk",
        external_id=zendesk_ticket_id,
        idempotency_key=f"zendesk:{zendesk_ticket_id}:{comment.comment_id}",
        request_path="/webhooks/zendesk",
        content=comment.content,
        customer_email=comment.requester_email,
        customer_name=comment.requester_name,
        subject=comment.subject,
        message_metadata={
            "channel": "zendesk",
            "zendesk_ticket_id": zendesk_ticket_id,
            "zendesk_comment_id": comment.comment_id,
        },
    )
    if not result.duplicate:
        notify_inbound_worker(request)
    return result.response()
