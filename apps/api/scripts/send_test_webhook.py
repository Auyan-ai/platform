"""Envía un mensaje de prueba firmado al endpoint /webhooks/inbound de staging.

Usa las mismas variables de .env que el API: WEBHOOK_SECRET.
La URL de staging se puede sobreescribir con --url.

Uso:
    cd apps/api
    # Política de devoluciones (no necesita email)
    poetry run python -m scripts.send_test_webhook \\
        --content "¿Cuál es la política de devoluciones?"

    # Pedido por email (el agente buscará órdenes del email dado)
    poetry run python -m scripts.send_test_webhook \\
        --email "cliente@example.com" \\
        --content "¿Dónde está mi pedido?"

    # Multi-turno: usar el conversation_id del primer mensaje
    poetry run python -m scripts.send_test_webhook \\
        --email "cliente@example.com" \\
        --conversation-id "uuid-del-primer-mensaje" \\
        --content "segundo mensaje en la misma conversación"

    # WhatsApp vía Zernio: `message.received` sintético firmado contra /webhooks/zernio
    # (secreto del webhook del tenant en ZERNIO_WEBHOOK_SECRET o --zernio-secret)
    poetry run python -m scripts.send_test_webhook --zernio \\
        --zernio-account "<accountId>" --zernio-conversation "<conversationId>" \\
        --phone "+34600111222" --content "¿Dónde está mi pedido?"
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)

STAGING_URL = "https://platform-staging-fdb7.up.railway.app"
CLOUD_RUN_STAGING_URL = "https://auyan-api-staging-350779301730.europe-west3.run.app"


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def run(
    *,
    tenant: str,
    content: str,
    email: str | None,
    name: str | None,
    channel: str,
    url: str,
    conversation_id: str | None,
) -> None:
    secret = os.environ.get("WEBHOOK_SECRET", "").strip()
    if not secret:
        raise SystemExit("WEBHOOK_SECRET no está en .env")

    payload: dict = {
        "tenant_slug": tenant,
        "channel": channel,
        "content": content,
    }
    if email:
        payload["customer_email"] = email
    if name:
        payload["customer_name"] = name
    if conversation_id:
        payload["conversation_id"] = conversation_id

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = _sign(body, secret)

    print(f"POST {url}/webhooks/inbound")
    print(f"  payload: {json.dumps(payload, ensure_ascii=False)}\n")

    with httpx.Client(timeout=60) as client:
        r = client.post(
            f"{url}/webhooks/inbound",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Auyan-Signature": signature,
            },
        )

    print(f"HTTP {r.status_code}")
    try:
        data = r.json()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        if data.get("conversation_id"):
            print(f"\n→ conversation_id: {data['conversation_id']}")
            print(f"  (usa --conversation-id {data['conversation_id']} para continuar este hilo)")
    except Exception:
        print(r.text)


def build_zernio_payload(
    *,
    account_id: str,
    conversation_id: str,
    content: str,
    phone: str | None,
    bsuid: str | None,
    name: str | None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """`message.received` sintético con la forma del webhook real de Zernio (camelCase)."""
    sender: dict[str, Any] = {"id": (phone or bsuid or "unknown").lstrip("+"), "name": name}
    if phone:
        sender["phoneNumber"] = phone
    if bsuid:
        sender["businessScopedUserId"] = bsuid
    return {
        "id": event_id or f"evt_test_{uuid.uuid4().hex[:12]}",
        "event": "message.received",
        "message": {
            "id": uuid.uuid4().hex[:24],
            "conversationId": conversation_id,
            "platform": "whatsapp",
            "platformMessageId": f"wamid.TEST{uuid.uuid4().hex[:16]}",
            "direction": "incoming",
            "text": content,
            "attachments": [],
            "sender": sender,
            "sentAt": datetime.now(UTC).isoformat(),
        },
        "conversation": {"id": conversation_id, "status": "active"},
        "account": {"id": account_id, "accountId": account_id, "platform": "whatsapp"},
        "metadata": {},
        "timestamp": datetime.now(UTC).isoformat(),
    }


def run_zernio(
    *,
    url: str,
    secret: str,
    payload: dict[str, Any],
) -> None:
    from apps.api.integrations.zernio import sign_zernio_body

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    print(f"POST {url}/webhooks/zernio  (event_id={payload['id']})")
    with httpx.Client(timeout=30) as client:
        r = client.post(
            f"{url}/webhooks/zernio",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Zernio-Signature": sign_zernio_body(body, secret),
                "X-Zernio-Event-Id": str(payload["id"]),
            },
        )
    print(f"HTTP {r.status_code}")
    print(r.text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Envía un mensaje de prueba a staging.")
    parser.add_argument("--tenant", default="lunaria")
    parser.add_argument("--content", required=True, help="Mensaje del cliente")
    parser.add_argument("--email", default=None, help="Email del cliente")
    parser.add_argument("--name", default="Cliente Test", help="Nombre del cliente")
    parser.add_argument("--channel", default="chat", choices=["email", "chat", "widget", "whatsapp"])
    parser.add_argument("--url", default=STAGING_URL, help="URL base del API")
    parser.add_argument("--conversation-id", default=None, help="UUID de conversación existente para multi-turno")
    parser.add_argument("--zernio", action="store_true", help="Webhook de Zernio (WhatsApp)")
    parser.add_argument("--zernio-account", default=None, help="accountId de Zernio del tenant")
    parser.add_argument("--zernio-conversation", default=None, help="conversationId de Zernio")
    parser.add_argument("--zernio-secret", default=None, help="Secreto del webhook del tenant")
    parser.add_argument("--zernio-event-id", default=None, help="Fijar el event id (probar duplicados)")
    parser.add_argument("--phone", default=None, help="Teléfono E.164 del comprador")
    parser.add_argument("--bsuid", default=None, help="BSUID del comprador")
    args = parser.parse_args()
    if args.zernio:
        secret = (args.zernio_secret or os.environ.get("ZERNIO_WEBHOOK_SECRET", "")).strip()
        if not secret or not args.zernio_account or not args.zernio_conversation:
            raise SystemExit("--zernio requiere --zernio-account, --zernio-conversation y el secreto")
        url = CLOUD_RUN_STAGING_URL if args.url == STAGING_URL else args.url
        run_zernio(
            url=url,
            secret=secret,
            payload=build_zernio_payload(
                account_id=args.zernio_account,
                conversation_id=args.zernio_conversation,
                content=args.content,
                phone=args.phone,
                bsuid=args.bsuid,
                name=args.name,
                event_id=args.zernio_event_id,
            ),
        )
        return
    run(
        tenant=args.tenant,
        content=args.content,
        email=args.email,
        name=args.name,
        channel=args.channel,
        url=args.url,
        conversation_id=args.conversation_id,
    )


if __name__ == "__main__":
    main()
