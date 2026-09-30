"""Intake de webhooks (#260): persistir + encolar en una transacción y ack inmediato.

Cubre el servicio compartido y los tres routers de helpdesk (Zendesk, Gorgias,
Chatwoot): el grafo NUNCA corre dentro del request.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from apps.api.core.config import get_settings
from apps.api.integrations.zendesk import ZendeskInboundComment
from apps.api.routers.webhooks_chatwoot import router as chatwoot_router
from apps.api.routers.webhooks_gorgias import router as gorgias_router
from apps.api.routers.webhooks_zendesk import router as zendesk_router
from apps.api.services.inbound_intake import InboundIntakeResult, persist_and_enqueue_inbound
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    INBOUND_MSG_ID,
    TENANT_ID,
    FakeSettings,
    make_conversation,
    make_end_customer,
    make_fake_bootstrap_connection,
    make_fake_tenant_scope,
    make_message,
    make_tenant,
)

INTAKE = "apps.api.services.inbound_intake"
JOB_ID = UUID("88888888-8888-8888-8888-888888888888")


# ─── persist_and_enqueue_inbound ─────────────────────────────────────────────


@pytest.fixture
def intake_db(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "claim_webhook_idempotency_key": AsyncMock(return_value=True),
        "find_end_customer_by_email": AsyncMock(return_value=make_end_customer()),
        "create_end_customer": AsyncMock(return_value=make_end_customer()),
        "find_conversation_by_external": AsyncMock(return_value=None),
        "create_conversation": AsyncMock(return_value=make_conversation()),
        "reopen_if_resolved": AsyncMock(side_effect=lambda _c, _t, conv: conv),
        "insert_message": AsyncMock(return_value=make_message(id=INBOUND_MSG_ID)),
        "update_conversation_last_message": AsyncMock(),
        "enqueue_inbound_job": AsyncMock(return_value=JOB_ID),
        "lock_inbound_intake": AsyncMock(),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(f"{INTAKE}.{name}", mock)
    monkeypatch.setattr(f"{INTAKE}.tenant_scope", make_fake_tenant_scope())
    return mocks


async def _intake(**overrides: Any) -> InboundIntakeResult:
    kwargs: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "channel": "zendesk",
        "external_id": "42",
        "idempotency_key": "zendesk:42:900",
        "request_path": "/webhooks/zendesk",
        "content": "¿dónde está mi pedido?",
        "customer_email": "cliente@test.com",
        "customer_name": "Cliente",
        "subject": "Pedido",
        "message_metadata": {"channel": "zendesk"},
    }
    kwargs.update(overrides)
    return await persist_and_enqueue_inbound(**kwargs)


async def test_new_message_is_persisted_and_enqueued(intake_db: dict[str, AsyncMock]) -> None:
    result = await _intake()

    assert result == InboundIntakeResult(
        duplicate=False, conversation_id=CONVERSATION_ID, job_id=JOB_ID
    )
    assert result.response() == {"received": True, "queued": True, "job_id": str(JOB_ID)}
    create = intake_db["create_conversation"].await_args.kwargs
    assert (create["channel"], create["external_id"], create["subject"]) == (
        "zendesk",
        "42",
        "Pedido",
    )
    enqueue = intake_db["enqueue_inbound_job"].await_args.kwargs
    assert enqueue == {
        "tenant_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "inbound_message_id": INBOUND_MSG_ID,
        "end_customer_id": CUSTOMER_ID,
        "channel": "zendesk",
    }


async def test_intake_locks_ticket_and_customer_before_creating(
    intake_db: dict[str, AsyncMock],
) -> None:
    await _intake()
    assert intake_db["lock_inbound_intake"].await_args.kwargs == {
        "tenant_id": TENANT_ID,
        "channel": "zendesk",
        "external_id": "42",
        "customer_email": "cliente@test.com",
    }


async def test_duplicate_webhook_writes_nothing(intake_db: dict[str, AsyncMock]) -> None:
    intake_db["claim_webhook_idempotency_key"].return_value = False

    result = await _intake()

    assert result.duplicate is True
    assert result.response() == {"received": True, "processed": False, "duplicate": True}
    intake_db["insert_message"].assert_not_awaited()
    intake_db["enqueue_inbound_job"].assert_not_awaited()


async def test_existing_conversation_is_reopened_not_recreated(
    intake_db: dict[str, AsyncMock],
) -> None:
    existing = make_conversation(status="resolved")
    intake_db["find_conversation_by_external"].return_value = existing

    await _intake()

    intake_db["create_conversation"].assert_not_awaited()
    intake_db["reopen_if_resolved"].assert_awaited_once()


async def test_unknown_customer_is_created(intake_db: dict[str, AsyncMock]) -> None:
    intake_db["find_end_customer_by_email"].return_value = None
    await _intake()
    assert intake_db["create_end_customer"].await_args.kwargs["email"] == "cliente@test.com"


async def test_failure_before_enqueue_propagates(intake_db: dict[str, AsyncMock]) -> None:
    """La transacción cae entera (key incluida): el reintento del proveedor reprocesa."""
    intake_db["insert_message"].side_effect = RuntimeError("db down")
    with pytest.raises(RuntimeError):
        await _intake()
    intake_db["enqueue_inbound_job"].assert_not_awaited()


# ─── Routers ─────────────────────────────────────────────────────────────────


def _patch_router_bootstrap(monkeypatch: pytest.MonkeyPatch, module: str, lookup: str) -> AsyncMock:
    integration = MagicMock(tenant_id=TENANT_ID, id=UUID(int=5), config={"subdomain": "acme"})
    monkeypatch.setattr(f"{module}.bootstrap_connection", make_fake_bootstrap_connection())
    monkeypatch.setattr(f"{module}.{lookup}", AsyncMock(return_value=integration))
    monkeypatch.setattr(
        f"{module}.get_integration_credentials_encrypted", AsyncMock(return_value=b"enc")
    )
    monkeypatch.setattr(f"{module}.get_integration_crypto_key", lambda _s: b"k")
    monkeypatch.setattr(f"{module}.decrypt_credentials", lambda _e, _k: json.dumps({}).encode())
    monkeypatch.setattr(f"{module}.get_tenant_by_id", AsyncMock(return_value=make_tenant()))
    monkeypatch.setattr(f"{module}.get_tenant_configuration", AsyncMock(return_value=None))
    monkeypatch.setattr(f"{module}.enforce_rate_limit", AsyncMock())
    monkeypatch.setattr(f"{module}.check_tenant_budget", AsyncMock())
    intake = AsyncMock(
        return_value=InboundIntakeResult(
            duplicate=False, conversation_id=CONVERSATION_ID, job_id=JOB_ID
        )
    )
    monkeypatch.setattr(f"{module}.persist_and_enqueue_inbound", intake)
    return intake


def _app(router: Any) -> tuple[FastAPI, MagicMock]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = FakeSettings
    worker = MagicMock()
    app.state.inbound_worker = worker
    # Sin agent_service: el request no debe necesitarlo (el grafo corre en el worker).
    return app, worker


class TestZendeskRouter:
    MODULE = "apps.api.routers.webhooks_zendesk"

    @pytest.fixture
    def intake(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        intake = _patch_router_bootstrap(
            monkeypatch, self.MODULE, "get_integration_by_zendesk_subdomain"
        )
        comment = ZendeskInboundComment(
            ticket_id="42",
            comment_id="900",
            author_id="7",
            public=True,
            content="¿dónde está mi pedido?",
            requester_id="7",
            requester_email="cliente@test.com",
            requester_name="Cliente",
            subject="Pedido",
        )
        monkeypatch.setattr(
            f"{self.MODULE}.ZendeskAdapter.fetch_inbound_comment",
            AsyncMock(return_value=comment),
        )
        return intake

    def _post(self, app: FastAPI) -> Any:
        with TestClient(app) as client:
            return client.post(
                "/webhooks/zendesk",
                json={"ticket_id": "42", "comment_id": "900", "subdomain": "acme"},
            )

    def test_enqueues_and_acks_without_running_the_graph(self, intake: AsyncMock) -> None:
        app, worker = _app(zendesk_router)
        r = self._post(app)

        assert r.status_code == 200
        assert r.json() == {"received": True, "queued": True, "job_id": str(JOB_ID)}
        kwargs = intake.await_args.kwargs
        assert kwargs["idempotency_key"] == "zendesk:42:900"
        assert kwargs["external_id"] == "42"
        assert kwargs["content"] == "¿dónde está mi pedido?"
        assert kwargs["customer_email"] == "cliente@test.com"
        worker.notify.assert_called_once()

    def test_duplicate_acks_200_without_waking_worker(self, intake: AsyncMock) -> None:
        intake.return_value = InboundIntakeResult(duplicate=True)
        app, worker = _app(zendesk_router)
        r = self._post(app)
        assert r.status_code == 200
        assert r.json()["duplicate"] is True
        worker.notify.assert_not_called()

    def test_works_without_a_live_worker(self, intake: AsyncMock) -> None:
        """El job es durable: sin worker en proceso, el ack igual sale."""
        app, _ = _app(zendesk_router)
        del app.state.inbound_worker
        assert self._post(app).status_code == 200


class TestGorgiasRouter:
    MODULE = "apps.api.routers.webhooks_gorgias"

    def _payload(self, **message: Any) -> dict[str, Any]:
        return {
            "event": {"type": "ticket-message-created"},
            "meta": {"domain": "acme"},
            "data": {
                "ticket": {"id": 77, "subject": "Pedido"},
                "message": {
                    "id": 501,
                    "from_agent": False,
                    "body_text": "¿dónde está mi pedido?",
                    "sender": {"email": "cliente@test.com", "name": "Cliente"},
                    **message,
                },
            },
        }

    def test_enqueues_and_acks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        intake = _patch_router_bootstrap(
            monkeypatch, self.MODULE, "get_integration_by_gorgias_domain"
        )
        app, worker = _app(gorgias_router)
        with TestClient(app) as client:
            r = client.post("/webhooks/gorgias", json=self._payload())

        assert r.status_code == 200
        assert r.json()["queued"] is True
        kwargs = intake.await_args.kwargs
        assert kwargs["idempotency_key"] == "gorgias:77:501"
        assert (kwargs["channel"], kwargs["external_id"]) == ("gorgias", "77")
        assert kwargs["customer_email"] == "cliente@test.com"
        worker.notify.assert_called_once()

    def test_agent_message_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        intake = _patch_router_bootstrap(
            monkeypatch, self.MODULE, "get_integration_by_gorgias_domain"
        )
        app, _ = _app(gorgias_router)
        with TestClient(app) as client:
            r = client.post("/webhooks/gorgias", json=self._payload(from_agent=True))
        assert r.json() == {"received": True, "processed": False}
        intake.assert_not_awaited()

    def test_missing_message_id_dedupes_by_body_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        intake = _patch_router_bootstrap(
            monkeypatch, self.MODULE, "get_integration_by_gorgias_domain"
        )
        app, _ = _app(gorgias_router)
        with TestClient(app) as client:
            client.post("/webhooks/gorgias", json=self._payload(id=None))
        key = intake.await_args.kwargs["idempotency_key"]
        assert key.startswith("gorgias:77:") and len(key) == len("gorgias:77:") + 64


class TestChatwootRouter:
    MODULE = "apps.api.routers.webhooks_chatwoot"

    def test_enqueues_and_acks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        intake = _patch_router_bootstrap(
            monkeypatch, self.MODULE, "get_integration_by_chatwoot_account"
        )
        app, worker = _app(chatwoot_router)
        payload = {
            "event": "message_created",
            "message_type": "incoming",
            "id": 3001,
            "content": "¿dónde está mi pedido?",
            "account": {"id": 9},
            "conversation": {"id": 55},
            "sender": {"email": "cliente@test.com", "name": "Cliente"},
        }
        with TestClient(app) as client:
            r = client.post("/webhooks/chatwoot", json=payload)

        assert r.status_code == 200
        assert r.json()["queued"] is True
        kwargs = intake.await_args.kwargs
        assert kwargs["idempotency_key"] == "chatwoot:3001"
        assert (kwargs["channel"], kwargs["external_id"]) == ("chatwoot", "55")
        worker.notify.assert_called_once()

    def test_outgoing_message_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        intake = _patch_router_bootstrap(
            monkeypatch, self.MODULE, "get_integration_by_chatwoot_account"
        )
        app, _ = _app(chatwoot_router)
        with TestClient(app) as client:
            r = client.post(
                "/webhooks/chatwoot",
                json={"event": "message_created", "message_type": "outgoing", "content": "hola"},
            )
        assert r.json() == {"received": True, "processed": False}
        intake.assert_not_awaited()
