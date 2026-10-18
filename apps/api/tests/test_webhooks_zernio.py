"""`POST /webhooks/zernio`: firma, routing por cuenta, filtros y encolado."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from apps.api.core.config import get_settings
from apps.api.core.errors import ConflictError
from apps.api.db.queries import get_integration_by_zernio_account
from apps.api.integrations.zernio import sign_zernio_body
from apps.api.routers.webhooks_zernio import router
from apps.api.services.inbound_intake import InboundIntakeResult
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import (
    CONVERSATION_ID,
    TENANT_ID,
    FakeSettings,
    make_fake_bootstrap_connection,
    make_tenant,
)
from tests.test_zernio_adapter import message_received

MODULE = "apps.api.routers.webhooks_zernio"
SECRET = "whsec_test"
JOB_ID = UUID("88888888-8888-8888-8888-888888888888")


@pytest.fixture
def mocks(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    integration = MagicMock(tenant_id=TENANT_ID, id=UUID(int=5), config={"account_id": "acc-1"})
    m: dict[str, Any] = {
        "get_integration_by_zernio_account": AsyncMock(return_value=integration),
        "get_integration_credentials_encrypted": AsyncMock(return_value=b"enc"),
        "get_tenant_by_id": AsyncMock(return_value=make_tenant()),
        "get_tenant_configuration": AsyncMock(return_value=None),
        "enforce_rate_limit": AsyncMock(),
        "check_tenant_budget": AsyncMock(),
        "persist_and_enqueue_inbound": AsyncMock(
            return_value=InboundIntakeResult(
                duplicate=False, conversation_id=CONVERSATION_ID, job_id=JOB_ID
            )
        ),
        "handle_zernio_status_event": AsyncMock(return_value={"received": True, "processed": True}),
    }
    for name, mock in m.items():
        monkeypatch.setattr(f"{MODULE}.{name}", mock)
    m["creds"] = {"api_key": "k", "webhook_secret": SECRET}
    monkeypatch.setattr(f"{MODULE}.bootstrap_connection", make_fake_bootstrap_connection())
    monkeypatch.setattr(f"{MODULE}.get_integration_crypto_key", lambda _s: b"k")
    monkeypatch.setattr(
        f"{MODULE}.decrypt_credentials", lambda _e, _k: json.dumps(m["creds"]).encode()
    )
    return m


def _app() -> tuple[FastAPI, MagicMock]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = FakeSettings
    worker = MagicMock()
    app.state.inbound_worker = worker
    return app, worker


def _post(
    app: FastAPI, payload: dict[str, Any], *, secret: str | None = SECRET, raw: bytes | None = None
) -> Any:
    body = raw if raw is not None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Zernio-Signature"] = sign_zernio_body(body, secret)
    with TestClient(app) as client:
        return client.post("/webhooks/zernio", content=body, headers=headers)


def test_message_received_is_enqueued(mocks: dict[str, Any]) -> None:
    app, worker = _app()
    r = _post(app, message_received())
    assert r.status_code == 200
    assert r.json() == {"received": True, "queued": True, "job_id": str(JOB_ID)}
    kwargs = mocks["persist_and_enqueue_inbound"].await_args.kwargs
    assert kwargs["channel"] == "whatsapp"
    assert kwargs["external_id"] == "zconv-1"
    assert kwargs["idempotency_key"] == "zernio:evt_1"
    assert kwargs["customer_phone"] == "+34600111222"
    assert kwargs["customer_external_id"] == "wa:bsuid:ES.abc"
    assert kwargs["customer_email"] is None
    assert kwargs["message_metadata"]["zernio_attachments"][0]["type"] == "image"
    worker.notify.assert_called_once()
    mocks["get_integration_by_zernio_account"].assert_awaited_once()
    assert mocks["get_integration_by_zernio_account"].await_args.kwargs == {"account_id": "acc-1"}


def test_legacy_signature_header_is_accepted(mocks: dict[str, Any]) -> None:
    app, _ = _app()
    body = json.dumps(message_received()).encode()
    with TestClient(app) as client:
        r = client.post(
            "/webhooks/zernio",
            content=body,
            headers={"X-Late-Signature": sign_zernio_body(body, SECRET)},
        )
    assert r.status_code == 200


def test_invalid_signature_401(mocks: dict[str, Any]) -> None:
    app, _ = _app()
    assert _post(app, message_received(), secret="otro").status_code == 401
    mocks["persist_and_enqueue_inbound"].assert_not_awaited()


def test_missing_signature_401(mocks: dict[str, Any]) -> None:
    app, _ = _app()
    assert _post(app, message_received(), secret=None).status_code == 401


def test_integration_without_secret_500(mocks: dict[str, Any]) -> None:
    mocks["creds"] = {"api_key": "k"}
    app, _ = _app()
    assert _post(app, message_received()).status_code == 500
    mocks["persist_and_enqueue_inbound"].assert_not_awaited()


def test_unknown_account_404(mocks: dict[str, Any]) -> None:
    mocks["get_integration_by_zernio_account"].return_value = None
    app, _ = _app()
    assert _post(app, message_received()).status_code == 404


def test_inactive_tenant_403(mocks: dict[str, Any]) -> None:
    mocks["get_tenant_by_id"].return_value = make_tenant(status="suspended")
    app, _ = _app()
    assert _post(app, message_received()).status_code == 403


def test_invalid_json_400(mocks: dict[str, Any]) -> None:
    app, _ = _app()
    assert _post(app, {}, raw=b"{not json").status_code == 400


def test_webhook_test_event_200_without_lookup(mocks: dict[str, Any]) -> None:
    app, _ = _app()
    r = _post(app, {"id": "evt_t", "event": "webhook.test"}, secret=None)
    assert r.status_code == 200
    mocks["get_integration_by_zernio_account"].assert_not_awaited()


def test_duplicate_acks_without_waking_worker(mocks: dict[str, Any]) -> None:
    mocks["persist_and_enqueue_inbound"].return_value = InboundIntakeResult(duplicate=True)
    app, worker = _app()
    r = _post(app, message_received())
    assert r.json()["duplicate"] is True
    worker.notify.assert_not_called()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"metadata": {"standby": True}}, "standby"),
        ({"event": "message.received", "message": None}, "no_message"),
    ],
)
def test_ignored_messages(mocks: dict[str, Any], overrides: dict[str, Any], reason: str) -> None:
    app, _ = _app()
    r = _post(app, message_received(**overrides))
    assert r.status_code == 200
    assert r.json()["ignored"] == reason
    mocks["persist_and_enqueue_inbound"].assert_not_awaited()


def test_non_whatsapp_platform_is_ignored(mocks: dict[str, Any]) -> None:
    payload = message_received()
    payload["message"]["platform"] = "instagram"
    app, _ = _app()
    assert _post(app, payload).json()["ignored"] == "unsupported_platform"


def test_outgoing_message_received_is_ignored(mocks: dict[str, Any]) -> None:
    payload = message_received()
    payload["message"]["direction"] = "outgoing"
    app, _ = _app()
    assert _post(app, payload).json()["ignored"] == "not_incoming"


def test_empty_message_is_ignored(mocks: dict[str, Any]) -> None:
    payload = message_received()
    payload["message"]["text"] = "  "
    payload["message"]["attachments"] = []
    app, _ = _app()
    assert _post(app, payload).json()["ignored"] == "empty_content"


def test_attachment_without_text_is_enqueued(mocks: dict[str, Any]) -> None:
    payload = message_received()
    payload["message"]["text"] = None
    app, _ = _app()
    assert _post(app, payload).status_code == 200
    assert mocks["persist_and_enqueue_inbound"].await_args.kwargs["content"] == ""


def test_unknown_event_goes_to_status_handler_and_is_200(mocks: dict[str, Any]) -> None:
    app, _ = _app()
    r = _post(app, {"id": "evt_9", "event": "reaction.received", "account": {"id": "acc-1"}})
    assert r.status_code == 200
    mocks["handle_zernio_status_event"].assert_awaited_once()
    mocks["persist_and_enqueue_inbound"].assert_not_awaited()


def test_event_without_account_is_ignored(mocks: dict[str, Any]) -> None:
    app, _ = _app()
    r = _post(app, {"id": "evt_9", "event": "message.received"}, secret=None)
    assert r.json()["ignored"] == "no_account"
    mocks["get_integration_by_zernio_account"].assert_not_awaited()


def test_event_without_id_is_not_processed(mocks: dict[str, Any]) -> None:
    payload = message_received()
    del payload["id"]
    app, _ = _app()
    assert _post(app, payload).json()["ignored"] == "no_event_id"
    mocks["persist_and_enqueue_inbound"].assert_not_awaited()


# ─── Cross-tenant: una cuenta de Zernio nunca resuelve a dos tenants ─────────


async def test_zernio_account_collision_fails_closed() -> None:
    rows = [
        {"tenant_id": UUID(int=1), "id": UUID(int=11)},
        {"tenant_id": UUID(int=2), "id": UUID(int=12)},
    ]
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    with pytest.raises(ConflictError):
        await get_integration_by_zernio_account(conn, account_id="acc-1")
    sql = conn.fetch.await_args.args[0]
    assert "provider    = 'zernio'" in sql and "kind        = 'channel'" in sql
