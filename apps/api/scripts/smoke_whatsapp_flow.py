"""Prueba de humo del flujo de WhatsApp contra un Postgres REAL (Sprint 2).

Zernio, Zendesk y Supabase Storage van simulados (httpx.MockTransport) y el grafo es un
agente falso: no hace falta red ni LLM. Recorre de punta a punta webhook firmado → cola →
worker → entrega:

  1. imagen sin texto → Storage + mensaje fijo, sin grafo (e identidad BSUID + teléfono)
  2. escalado → ticket de handoff en Zendesk con transcripción literal y motivo
  3. mensaje con handoff activo → al ticket, la IA calla
  4. respuesta pública del agente de Zendesk → WhatsApp (reintento sin duplicar)
  5. ticket resuelto → conversación resuelta SIN resolution_event
  6. respuesta desde la app del móvil → hold de 12 h (human_hold)
  7. ventana cerrada → plantilla de re-enganche → pendiente entregado en el siguiente inbound

Preparar un Postgres desechable con TODAS las migraciones (una vez):

    createdb auyan_smoke
    psql auyan_smoke -f scripts/sql/supabase_local_stubs.sql   # auth/storage/roles de Supabase
    for f in ../../supabase/migrations/*.sql; do psql auyan_smoke -v ON_ERROR_STOP=1 -f \; done

Correr (desde apps/api):

    AUYAN_SMOKE_DATABASE_URL=postgresql://postgres:postgres@localhost/auyan_smoke \
        PYTHONPATH=../.. poetry run python -m scripts.smoke_whatsapp_flow

Nunca contra staging ni producción: crea un tenant de prueba en la base indicada.
"""

# ruff: noqa: E402,E501,S101,S105,S106  (secretos falsos de un harness local)

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

KEY_HEX = "ab" * 32
if not os.environ.get("AUYAN_SMOKE_DATABASE_URL"):
    sys.exit("Falta AUYAN_SMOKE_DATABASE_URL (Postgres desechable con todas las migraciones)")
os.environ.update(
    {
        "SUPABASE_URL": "https://proj.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "srk",
        "SUPABASE_ANON_KEY": "x",
        "ANTHROPIC_API_KEY": "x",
        "OPENAI_API_KEY": "x",
        "DATABASE_URL": os.environ.get("AUYAN_SMOKE_DATABASE_URL", ""),
        "SUPABASE_JWT_SECRET": "x",
        "INTEGRATIONS_SECRET_KEY": KEY_HEX,
        "WEBHOOK_SECRET": "x",
    }
)
from apps.api.core.config import Settings

for n, f in Settings.model_fields.items():
    if f.is_required() and n.upper() not in os.environ:
        os.environ[n.upper()] = "x"

import httpx
from apps.api.agents.service import AgentOutcome
from apps.api.core.config import get_settings
from apps.api.db import client as dbclient
from apps.api.db import queries as q
from apps.api.integrations import zendesk as zmod
from apps.api.integrations.zernio import ZernioAdapter, sign_zernio_body
from apps.api.routers.webhooks_zendesk import router as zendesk_router
from apps.api.routers.webhooks_zernio import router as zernio_router
from apps.api.services import media_storage
from apps.api.services.inbound_worker import InboundWorker
from apps.api.services.integrations_crypto import encrypt_credentials
from fastapi import FastAPI

SECRET = "whsec"
ACCOUNT = f"acc-{uuid.uuid4().hex[:6]}"
SUB = f"sub{uuid.uuid4().hex[:6]}"
calls: list[tuple[str, str, Any]] = []


def zernio_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content) if request.content and request.method == "POST" else None
    calls.append(("zernio", f"{request.method} {request.url.path}", body))
    if "/whatsapp/media/" in request.url.path:
        return httpx.Response(200, content=b"\x89PNGfake", headers={"Content-Type": "image/png"})
    return httpx.Response(200, json={"data": {"messageId": f"wamid.{len(calls)}"}})


def zendesk_handler(request: httpx.Request) -> httpx.Response:
    body = (
        json.loads(request.content)
        if request.content
        and request.headers.get("content-type", "").startswith("application/json")
        else None
    )
    calls.append(("zendesk", f"{request.method} {request.url.path}", body))
    p = request.url.path
    if p.endswith("/users/create_or_update.json"):
        return httpx.Response(200, json={"user": {"id": 777}})
    if p.endswith("/uploads.json"):
        return httpx.Response(201, json={"upload": {"token": "tok-1"}})
    if p.endswith("/tickets.json"):
        return httpx.Response(201, json={"ticket": {"id": 555}})
    if p.endswith("/comments.json"):
        return httpx.Response(
            200,
            json={
                "comments": [
                    {
                        "id": 9001,
                        "author_id": 42,
                        "public": True,
                        "body": "Hola, soy Laura: ya lo cambiamos.",
                    }
                ],
                "users": [{"id": 42, "name": "Laura", "role": "agent"}],
            },
        )
    if request.method == "GET":
        return httpx.Response(200, json={"ticket": {"id": 555, "requester_id": 777}, "users": []})
    return httpx.Response(200, json={"ticket": {"id": 555}})


def storage_handler(request: httpx.Request) -> httpx.Response:
    calls.append(("storage", f"{request.method} {request.url.path}", None))
    return (
        httpx.Response(200, content=b"\x89PNGfake")
        if request.method == "GET"
        else httpx.Response(200, json={"Key": "k"})
    )


class FakeAgent:
    def __init__(self) -> None:
        self.calls = 0
        self.next: AgentOutcome | None = None

    observability = None

    async def process_inbound(self, **kw: Any) -> AgentOutcome:
        self.calls += 1
        return self.next


def outcome(**o: Any) -> AgentOutcome:
    base = dict(
        decision="respond",
        response_text="Te ayudo",
        escalation_reason=None,
        output_message_id=None,
        escalation_id=None,
        resolves_on_delivery=False,
        trace_id=None,
        confidence=0.9,
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.0,
        model_used=None,
        error=None,
    )
    base.update(o)
    return AgentOutcome(**base)


def payload(event: str, text: str | None, attachments: list | None = None, **msg: Any) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:10]}",
        "event": event,
        "message": {
            "id": uuid.uuid4().hex[:8],
            "conversationId": "zc-1",
            "platform": "whatsapp",
            "platformMessageId": f"wamid.in{uuid.uuid4().hex[:6]}",
            "direction": "incoming" if event == "message.received" else "outgoing",
            "text": text,
            "attachments": attachments or [],
            "sender": {
                "id": "34600111222",
                "name": "Ana López",
                "phoneNumber": "+34600111222",
                "businessScopedUserId": "ES.bsuid1",
            },
            "sentAt": datetime.now(UTC).isoformat(),
            **msg,
        },
        "conversation": {"id": "zc-1"},
        "account": {"id": ACCOUNT, "accountId": ACCOUNT},
        "metadata": {},
    }


async def main() -> None:
    ZernioAdapter.transport = httpx.MockTransport(zernio_handler)
    orig = zmod.ZendeskClient
    zmod.ZendeskAdapter._client = lambda self, ctx: orig(
        ctx.config["subdomain"], oauth_token="t", transport=httpx.MockTransport(zendesk_handler)
    )
    media_storage._transport = httpx.MockTransport(storage_handler)
    await dbclient.init_pool()
    key = bytes.fromhex(KEY_HEX)
    pool = dbclient.get_pool()
    tenant_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into tenants (id, slug, name) values ($1,$2,'Smoke')",
            tenant_id,
            f"smoke-{tenant_id.hex[:6]}",
        )
        await q.upsert_integration(
            conn,
            tenant_id=tenant_id,
            kind="channel",
            provider="zernio",
            credentials_encrypted=encrypt_credentials(
                json.dumps({"api_key": "k", "webhook_secret": SECRET}).encode(), key
            ),
            config={
                "account_id": ACCOUNT,
                "reengagement_template": {"name": "auyan_reengagement", "language": "es"},
            },
            is_active=True,
            is_primary_for_kind=True,
        )
        await q.upsert_integration(
            conn,
            tenant_id=tenant_id,
            kind="helpdesk",
            provider="zendesk",
            credentials_encrypted=encrypt_credentials(
                json.dumps({"oauth_token": "t"}).encode(), key
            ),
            config={"subdomain": SUB, "api_user_id": "1"},
            is_active=True,
            is_primary_for_kind=True,
        )

    app = FastAPI()
    app.include_router(zernio_router)
    app.include_router(zendesk_router)
    app.dependency_overrides[get_settings] = get_settings
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    agent = FakeAgent()
    worker = InboundWorker(agent_service=agent, settings=get_settings())

    async def post_zernio(p: dict) -> httpx.Response:
        raw = json.dumps(p).encode()
        return await client.post(
            "/webhooks/zernio",
            content=raw,
            headers={"X-Zernio-Signature": sign_zernio_body(raw, SECRET)},
        )

    # 1) Imagen sin texto → mensaje fijo, sin grafo
    r = await post_zernio(
        payload(
            "message.received",
            None,
            [{"type": "image", "url": "https://zernio.com/api/v1/whatsapp/media/77"}],
        )
    )
    assert r.status_code == 200 and r.json().get("queued"), r.text
    # Evento desconocido de la misma cuenta: siempre 200 (nunca 4xx a Zernio).
    unknown = await post_zernio({**payload("reaction.received", None), "message": None})
    assert unknown.status_code == 200, unknown.text
    assert await worker.run_once()
    assert agent.calls == 0
    sends = [c for c in calls if c[0] == "zernio" and c[1].endswith("/messages")]
    assert sends and "no podemos verlo" in sends[-1][2]["message"], sends
    async with pool.acquire() as conn:
        conv = await q.find_conversation_by_external(conn, tenant_id, "whatsapp", "zc-1")
        msgs = await q.get_messages_for_conversation(conn, tenant_id, conv.id)
        cust = await q.get_end_customer(conn, tenant_id, conv.end_customer_id)
    assert cust.phone == "+34600111222" and cust.external_id == "wa:bsuid:ES.bsuid1"
    assert msgs[0].attachments and msgs[0].attachments[0]["path"].startswith(str(tenant_id))
    assert (
        msgs[1].metadata.get("fixed_message") == "media_without_text"
        and msgs[1].metadata.get("delivery") == "delivered"
    )
    print("1 OK media_fallback + identidad + Storage")

    # 2) Texto → grafo (fake) escala → handoff a Zendesk
    agent.next = outcome(
        decision="escalate",
        response_text="Te paso con una persona del equipo.",
        escalation_reason="El cliente pide hablar con una persona",
        escalation_created=True,
    )
    r = await post_zernio(payload("message.received", "Quiero hablar con una persona"))
    assert await worker.run_once()
    assert agent.calls == 1
    tickets = [c for c in calls if c[1].endswith("/tickets.json")]
    assert tickets, calls
    t = tickets[-1][2]["ticket"]
    assert (
        t["tags"] == ["auyan_handoff", "auyan_whatsapp"]
        and "Quiero hablar con una persona" in t["comment"]["body"]
    )
    assert "Motivo: El cliente pide hablar con una persona" in t["comment"]["body"]
    async with pool.acquire() as conn:
        h = await q.get_active_handoff_for_chat(conn, tenant_id, "whatsapp", "zc-1")
    assert h and h.external_ticket_id == "555"
    print("2 OK escalado → ticket de handoff con transcripción y motivo")

    # 3) Nuevo mensaje con handoff → al ticket, sin grafo
    await post_zernio(payload("message.received", "¿Hay novedades?"))
    assert await worker.run_once()
    assert agent.calls == 1
    put = [c for c in calls if c[0] == "zendesk" and c[1].startswith("PUT") and c[2]]
    assert put[-1][2]["ticket"]["comment"] == {
        "body": "¿Hay novedades?",
        "public": True,
        "author_id": 777,
    }
    print("3 OK mensaje reenviado al ticket, IA callada")

    # 4) Respuesta pública del agente de Zendesk → WhatsApp
    n_before = len([c for c in calls if c[1].endswith("/messages")])
    r = await client.post(
        "/webhooks/zendesk",
        json={"ticket_id": "555", "comment_id": "9001", "subdomain": SUB, "event": "handoff_reply"},
    )
    assert r.status_code == 200 and r.json().get("delivery") == "delivered", r.text
    r2 = await client.post(
        "/webhooks/zendesk",
        json={"ticket_id": "555", "comment_id": "9001", "subdomain": SUB, "event": "handoff_reply"},
    )
    assert r2.json().get("duplicate") is True, r2.text
    sends = [c for c in calls if c[1].endswith("/messages")]
    assert (
        len(sends) == n_before + 1
        and sends[-1][2]["message"] == "Hola, soy Laura: ya lo cambiamos."
    )
    print("4 OK respuesta de Zendesk llega a WhatsApp (sin duplicar)")

    # 5) solved → handoff cerrado, resuelta sin resolution_event
    r = await client.post(
        "/webhooks/zendesk", json={"ticket_id": "555", "subdomain": SUB, "event": "handoff_solved"}
    )
    assert r.status_code == 200, r.text
    async with pool.acquire() as conn:
        assert await q.get_active_handoff_for_chat(conn, tenant_id, "whatsapp", "zc-1") is None
        conv = await q.get_conversation(conn, tenant_id, h.conversation_id)
        events = (
            await conn.fetchval(
                "select count(*) from billing_resolution_events where tenant_id=$1", tenant_id
            )
            if await conn.fetchval("select to_regclass('billing_resolution_events')")
            else 0
        )
    assert conv.status == "resolved" and events == 0, (conv.status, events)
    print("5 OK solved → resuelta sin facturar")

    # 6) Toma desde el móvil → device hold → IA callada
    r = await post_zernio(
        payload("message.sent", "Te escribo yo, Ana", source="whatsapp_business_app", sentVia=None)
    )
    assert r.json().get("outcome") == "device_hold_opened", r.text
    await post_zernio(payload("message.received", "Gracias!"))
    assert await worker.run_once()
    assert agent.calls == 1
    async with pool.acquire() as conn:
        last = await conn.fetchval(
            "select decision from inbound_jobs where tenant_id=$1 order by created_at desc limit 1",
            tenant_id,
        )
    assert last == "human_hold", last
    print("6 OK toma desde el móvil → human_hold")
    # 7) Ventana cerrada: confirmación L3 → plantilla + pendiente → se entrega en el siguiente inbound
    from apps.api.services.helpdesk_delivery import deliver_message_to_helpdesk

    async with pool.acquire() as conn:
        await conn.execute(
            "update conversation_handoffs set expires_at = now() - interval '1 minute' where tenant_id=$1",
            tenant_id,
        )
        await conn.execute(
            "update messages set created_at = now() - interval '30 hours' where tenant_id=$1 and role='customer'",
            tenant_id,
        )
        conv = await q.find_conversation_by_external(conn, tenant_id, "whatsapp", "zc-1")
        msg = await q.insert_message(
            conn,
            tenant_id=tenant_id,
            conversation_id=conv.id,
            role="agent_ai",
            direction="outbound",
            content="Listo: cancelamos tu pedido #1432.",
        )
        await conn.execute("select set_config('app.tenant_id', $1, false)", str(tenant_id))
        ok = await deliver_message_to_helpdesk(
            conn, tenant_id=tenant_id, conversation=conv, content=msg.content, message_id=msg.id
        )
    assert ok is False
    tpl = [c for c in calls if c[0] == "zernio" and c[2] and "template" in c[2]]
    assert (
        tpl
        and tpl[-1][2]["template"]["elements"][0]["components"][0]["parameters"][0]["text"] == "Ana"
    ), tpl
    agent.next = outcome(response_text="¡De nada!")
    await post_zernio(payload("message.received", "ok gracias"))
    assert await worker.run_once()
    texts = [c[2].get("message") for c in calls if c[0] == "zernio" and c[2] and "message" in c[2]]
    assert texts[-2:] == ["Listo: cancelamos tu pedido #1432.", "¡De nada!"], texts[-3:]
    async with pool.acquire() as conn:
        meta = await conn.fetchval("select metadata->>'delivery' from messages where id=$1", msg.id)
    assert meta == "delivered", meta
    print("7 OK ventana cerrada → plantilla → pendiente entregado antes de la respuesta")
    await dbclient.close_pool()
    print("SMOKE OK")


asyncio.run(main())
