"""ZernioClient / ZernioAdapter / firma / parseo de eventos (transport mock, sin red)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ExternalIntegrationError
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.integrations.zernio import (
    ZernioAdapter,
    ZernioClient,
    parse_zernio_event,
    sign_zernio_body,
    split_for_whatsapp,
    verify_zernio_signature,
)

from tests.conftest import TENANT_ID

FIXTURE = Path(__file__).parent / "fixtures" / "zernio" / "webhook_test.json"


def message_received(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "evt_1",
        "event": "message.received",
        "message": {
            "id": "m1",
            "conversationId": "zconv-1",
            "platform": "whatsapp",
            "platformMessageId": "wamid.1",
            "direction": "incoming",
            "text": "¿Dónde está mi pedido?",
            "attachments": [
                {"type": "image", "url": "https://zernio.com/api/v1/whatsapp/media/9"}
            ],
            "sender": {
                "id": "34600111222",
                "name": "Ana",
                "phoneNumber": "+34600111222",
                "businessScopedUserId": "ES.abc",
            },
            "sentAt": "2026-10-01T10:00:00Z",
        },
        "conversation": {"id": "zconv-1", "status": "active"},
        "account": {"id": "acc-1", "accountId": "acc-1", "profileId": "prof-1"},
        "metadata": {"standby": False},
    }
    payload.update(overrides)
    return payload


# ─── Firma ────────────────────────────────────────────────────────────────────


def test_signature_valid() -> None:
    body = b'{"id":"evt_1"}'
    assert verify_zernio_signature(body, "s3cret", sign_zernio_body(body, "s3cret"))


def test_signature_accepts_sha256_prefix_and_uppercase() -> None:
    body = b'{"id":"evt_1"}'
    sig = sign_zernio_body(body, "s3cret").upper()
    assert verify_zernio_signature(body, "s3cret", f"sha256={sig}")


def test_signature_invalid_or_missing() -> None:
    body = b'{"id":"evt_1"}'
    assert not verify_zernio_signature(body, "s3cret", sign_zernio_body(body, "otro"))
    assert not verify_zernio_signature(body + b" ", "s3cret", sign_zernio_body(body, "s3cret"))
    assert not verify_zernio_signature(body, "s3cret", None)
    assert not verify_zernio_signature(body, "", sign_zernio_body(body, ""))


@pytest.mark.skipif(not FIXTURE.exists(), reason="Pendiente de C0.4: fixture real de la firma")
def test_signature_matches_real_zernio_fixture() -> None:
    """Fixture capturado en C0: {"secret", "headers", "raw_body"} de un `webhook.test` real."""
    fixture = json.loads(FIXTURE.read_text())
    raw = fixture["raw_body"].encode()
    headers = {k.lower(): v for k, v in fixture["headers"].items()}
    assert verify_zernio_signature(raw, fixture["secret"], headers["x-zernio-signature"])


# ─── Parseo ───────────────────────────────────────────────────────────────────


def test_parse_message_received() -> None:
    event = parse_zernio_event(message_received())
    assert (event.event_id, event.event, event.account_id, event.profile_id) == (
        "evt_1",
        "message.received",
        "acc-1",
        "prof-1",
    )
    assert event.conversation_id == "zconv-1"
    assert event.message is not None
    sender = event.message.sender
    assert sender.phone_e164 == "+34600111222"
    assert sender.customer_external_id == "wa:bsuid:ES.abc"
    assert event.message.attachments[0].type == "image"
    assert event.standby is False


def test_parse_sender_without_phone() -> None:
    payload = message_received()
    del payload["message"]["sender"]["phoneNumber"]
    event = parse_zernio_event(payload)
    assert event.message is not None
    assert event.message.sender.phone_e164 is None
    assert event.message.sender.customer_external_id == "wa:bsuid:ES.abc"


def test_parse_account_id_fallback_and_missing_parts() -> None:
    event = parse_zernio_event({"id": "e", "event": "x", "account": {"id": "acc-9"}})
    assert event.account_id == "acc-9"
    assert event.message is None
    assert event.conversation_id is None
    event = parse_zernio_event({"event": "webhook.test"})
    assert (event.event_id, event.account_id) == (None, None)


def test_parse_standby() -> None:
    event = parse_zernio_event(message_received(metadata={"standby": True}))
    assert event.standby is True


# ─── Cortes ───────────────────────────────────────────────────────────────────


def test_split_short_text_single_chunk() -> None:
    assert split_for_whatsapp("  hola  ") == ["hola"]
    assert split_for_whatsapp("   ") == []


def test_split_by_paragraphs_under_limit() -> None:
    text = "\n\n".join(["a" * 30] * 5)
    chunks = split_for_whatsapp(text, limit=70)
    assert all(len(c) <= 70 for c in chunks)
    assert "".join(c.replace("\n\n", "") for c in chunks) == "a" * 150


def test_split_hard_cuts_huge_line() -> None:
    chunks = split_for_whatsapp("x" * 9000)
    assert [len(c) for c in chunks] == [4000, 4000, 1000]


# ─── Cliente HTTP ─────────────────────────────────────────────────────────────


def _transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_send_text_posts_to_conversation_with_idempotency_key() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"success": True, "data": {"messageId": "wamid.X", "conversationId": "zconv-1"}},
            headers={"X-Request-Id": "req-1"},
        )

    client = ZernioClient("key-1", transport=_transport(handler))
    result = await client.send_text("zconv-1", "acc-1", "hola", idempotency_key="msg-1:0")
    assert seen["url"] == "https://zernio.com/api/v1/inbox/conversations/zconv-1/messages"
    assert seen["headers"]["Authorization"] == "Bearer key-1"
    assert seen["headers"]["Idempotency-Key"] == "msg-1:0"
    assert seen["body"] == {"accountId": "acc-1", "message": "hola"}
    assert result.message_id == "wamid.X"


async def test_send_template_body_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"messageId": "wamid.T"}})

    client = ZernioClient("k", transport=_transport(handler))
    components = [{"type": "body", "parameters": [{"type": "text", "text": "Ana"}]}]
    await client.send_template("zconv-1", "acc-1", "auyan_reengage", "es", components)
    assert seen["body"] == {
        "accountId": "acc-1",
        "template": {
            "elements": [{"name": "auyan_reengage", "language": "es", "components": components}]
        },
    }


async def test_error_is_translated_with_zernio_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "131056", "error": "rate"})

    client = ZernioClient("k", transport=_transport(handler))
    with pytest.raises(ExternalIntegrationError) as exc:
        await client.send_text("c", "a", "hola")
    assert exc.value.code == "zernio_131056"


async def test_transport_error_is_translated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    client = ZernioClient("k", transport=_transport(handler))
    with pytest.raises(ExternalIntegrationError) as exc:
        await client.send_text("c", "a", "hola")
    assert exc.value.code == "zernio_transport"


async def test_download_media_uses_bearer_only_for_zernio_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(200, content=b"\x89PNG", headers={"Content-Type": "image/png"})

    client = ZernioClient("k", transport=_transport(handler))
    data, mime = await client.download_media("https://zernio.com/api/v1/whatsapp/media/9")
    assert (data, mime) == (b"\x89PNG", "image/png")
    with pytest.raises(ExternalIntegrationError) as exc:
        await client.download_media("https://evil.example/steal")
    assert exc.value.code == "zernio_media_foreign_url"


async def test_download_media_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.api.integrations.zernio.MAX_MEDIA_BYTES", 3)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"12345")

    client = ZernioClient("k", transport=_transport(handler))
    with pytest.raises(ExternalIntegrationError) as exc:
        await client.download_media("https://zernio.com/api/v1/whatsapp/media/9")
    assert exc.value.code == "zernio_media_too_large"


# ─── Adapter ──────────────────────────────────────────────────────────────────


def test_adapter_is_registered_as_channel() -> None:
    assert IntegrationRegistry.get("channel", "zernio") is ZernioAdapter


async def test_adapter_send_outbound_chunks_with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((json.loads(request.content)["message"], request.headers.get("Idempotency-Key")))
        return httpx.Response(200, json={"data": {"messageId": f"wamid.{len(sent)}"}})

    adapter = ZernioAdapter()
    adapter.transport = _transport(handler)
    ctx = IntegrationContext(
        tenant_id=TENANT_ID, credentials={"api_key": "k"}, config={"account_id": "acc-1"}
    )
    results = await adapter.send_outbound(ctx, "zconv-1", "x" * 4500, idempotency_key="msg-1")
    assert [key for _, key in sent] == ["msg-1:0", "msg-1:1"]
    assert [r.message_id for r in results] == ["wamid.1", "wamid.2"]


async def test_adapter_requires_account_id() -> None:
    ctx = IntegrationContext(tenant_id=TENANT_ID, credentials={"api_key": "k"}, config={})
    with pytest.raises(ExternalIntegrationError):
        await ZernioAdapter().send_outbound(ctx, "zconv-1", "hola")
