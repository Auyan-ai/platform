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

    # Pedido por número
    poetry run python -m scripts.send_test_webhook \\
        --email "cliente@example.com" \\
        --content "Necesito cancelar el pedido #1234"
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)

STAGING_URL = "https://platform-staging-fdb7.up.railway.app"


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
    except Exception:
        print(r.text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Envía un mensaje de prueba a staging.")
    parser.add_argument("--tenant", default="lunaria")
    parser.add_argument("--content", required=True, help="Mensaje del cliente")
    parser.add_argument("--email", default=None, help="Email del cliente")
    parser.add_argument("--name", default="Cliente Test", help="Nombre del cliente")
    parser.add_argument("--channel", default="chat", choices=["email", "chat", "widget", "whatsapp"])
    parser.add_argument("--url", default=STAGING_URL, help="URL base del API")
    args = parser.parse_args()
    run(
        tenant=args.tenant,
        content=args.content,
        email=args.email,
        name=args.name,
        channel=args.channel,
        url=args.url,
    )


if __name__ == "__main__":
    main()
