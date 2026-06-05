"""Tests del sistema de idempotencia en POST /webhooks/inbound.

Cubre los 4 escenarios críticos:
- Sin header → flujo normal sin toque de idempotencia
- Primera petición con key → key claimed, se procesa, se marca done
- Duplicate (key done) → respuesta cacheada, el agente NO se llama
- In-flight (key pending) → 409
- Error de procesamiento → key deleted para permitir reintento
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

from apps.api.agents.service import AgentOutcome
from apps.api.core.config import get_settings
from apps.api.db.models import IdempotencyRecord
from apps.api.routers.webhooks import router as webhooks_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import (
    CONVERSATION_ID,
    INBOUND_MSG_ID,
    OUTBOUND_MSG_ID,
    TENANT_ID,
    FakeSettings,
    make_conversation,
    make_end_customer,
    make_fake_bootstrap_connection,
    make_fake_tenant_scope,
    make_message,
    make_tenant,
    make_tenant_configuration,
)

WEBHOOK_SECRET = "test-webhook-secret"
ROUTER_MODULE = "apps.api.routers.webhooks"
IDEM_KEY = "req_2026_abc123"


# ----------------------------------------------------------------
# Helpers compartidos
# ----------------------------------------------------------------


class _SecretLike:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


class _FakeSettingsWithSecret(FakeSettings):
    def __init__(self) -> None:
        super().__init__()
        self.webhook_secret = _SecretLike(WEBHOOK_SECRET)


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _make_app(*, agent_service: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.state.agent_service = agent_service
    app.dependency_overrides[get_settings] = _FakeSettingsWithSecret
    app.include_router(webhooks_router)
    return app


def _valid_payload() -> dict:
    return {
        "tenant_slug": "acme",
        "channel": "chat",
        "content": "¿Cuánto tarda el envío?",
        "customer_email": "juan@example.com",
    }


def _outcome_respond() -> AgentOutcome:
    return AgentOutcome(
        decision="respond",
        response_text="3-5 días.",
        escalation_reason=None,
        output_message_id=str(OUTBOUND_MSG_ID),
        escalation_id=None,
        resolved=False,
        trace_id="trace-1",
        confidence=0.92,
        tokens_in=120,
        tokens_out=35,
        cost_usd=0.0008,
        model_used="claude-sonnet-4-6",
        error=None,
    )


def _make_idem_record(
    status: str = "done", response_body: dict | None = None
) -> IdempotencyRecord:
    """Factory para IdempotencyRecord de test."""
    body = response_body or {
        "ok": True,
        "decision": "respond",
        "conversation_id": str(CONVERSATION_ID),
        "inbound_message_id": str(INBOUND_MSG_ID),
        "output_message_id": str(OUTBOUND_MSG_ID),
        "escalation_id": None,
        "response_text": "3-5 días.",
        "escalation_reason": None,
        "trace_id": "trace-1",
        "error": None,
    }
    return IdempotencyRecord(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        tenant_id=TENANT_ID,
        key=IDEM_KEY,
        request_path="/webhooks/inbound",
        status=status,  # type: ignore[arg-type]
        response_status=200,
        response_body=body,
        created_at=datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC),
        expires_at=datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC),
    )


def _patch_db_with_idem(
    monkeypatch,
    *,
    try_insert_return: IdempotencyRecord | None = None,
    get_record_return: IdempotencyRecord | None = None,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Parchea el router completo, incluyendo las 4 funciones de idempotencia.

    Devuelve (try_insert_mock, get_record_mock, complete_mock, delete_mock).
    """
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.bootstrap_connection", make_fake_bootstrap_connection()
    )
    monkeypatch.setattr(f"{ROUTER_MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.get_tenant_by_slug", AsyncMock(return_value=make_tenant())
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.get_tenant_configuration",
        AsyncMock(return_value=make_tenant_configuration()),
    )
    monkeypatch.setattr(f"{ROUTER_MODULE}.enforce_rate_limit", AsyncMock())
    monkeypatch.setattr(f"{ROUTER_MODULE}.check_tenant_budget", AsyncMock())
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.find_end_customer_by_email",
        AsyncMock(return_value=make_end_customer()),
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.create_end_customer",
        AsyncMock(return_value=make_end_customer()),
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.find_conversation_by_id", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.find_conversation_by_external", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.create_conversation",
        AsyncMock(return_value=make_conversation()),
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.insert_message",
        AsyncMock(return_value=make_message(id=INBOUND_MSG_ID)),
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.update_conversation_last_message", AsyncMock()
    )

    try_insert_mock = AsyncMock(return_value=try_insert_return)
    get_record_mock = AsyncMock(return_value=get_record_return)
    complete_mock = AsyncMock()
    delete_mock = AsyncMock()

    monkeypatch.setattr(
        f"{ROUTER_MODULE}.try_insert_idempotency_key", try_insert_mock
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.get_idempotency_record", get_record_mock
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.complete_idempotency_key", complete_mock
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.delete_idempotency_key", delete_mock
    )

    return try_insert_mock, get_record_mock, complete_mock, delete_mock


# ----------------------------------------------------------------
# Tests
# ----------------------------------------------------------------


class TestIdempotencyHeaderAbsent:
    """Sin header X-Idempotency-Key — flujo original intacto."""

    def test_without_key_processes_normally(self, monkeypatch) -> None:
        service = AsyncMock()
        service.process_inbound = AsyncMock(return_value=_outcome_respond())
        try_insert_mock, _, complete_mock, delete_mock = _patch_db_with_idem(monkeypatch)

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body)},
            )

        assert r.status_code == 200
        assert r.json()["decision"] == "respond"
        service.process_inbound.assert_awaited_once()
        # Sin header, las funciones de idempotencia no se tocan
        try_insert_mock.assert_not_called()
        complete_mock.assert_not_called()
        delete_mock.assert_not_called()


class TestIdempotencyFirstRequest:
    """Primera petición con key nueva — se procesa y queda registrada como done."""

    def test_first_request_claims_key_and_processes(self, monkeypatch) -> None:
        service = AsyncMock()
        service.process_inbound = AsyncMock(return_value=_outcome_respond())
        # try_insert devuelve el record (inserción exitosa)
        pending_record = _make_idem_record(status="pending", response_body=None)
        try_insert_mock, get_record_mock, complete_mock, _ = _patch_db_with_idem(
            monkeypatch, try_insert_return=pending_record
        )

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={
                    "X-Auyan-Signature": _sign(body),
                    "X-Idempotency-Key": IDEM_KEY,
                },
            )

        assert r.status_code == 200
        data = r.json()
        assert data["decision"] == "respond"

        # Se intentó insertar la key
        try_insert_mock.assert_awaited_once()
        call_kwargs = try_insert_mock.call_args.kwargs
        assert call_kwargs["key"] == IDEM_KEY
        assert call_kwargs["request_path"] == "/webhooks/inbound"

        # El agente se invocó una sola vez
        service.process_inbound.assert_awaited_once()

        # La key quedó marcada como done
        complete_mock.assert_awaited_once()
        complete_kwargs = complete_mock.call_args.kwargs
        assert complete_kwargs["key"] == IDEM_KEY
        assert complete_kwargs["response_status"] == 200
        assert complete_kwargs["response_body"]["decision"] == "respond"

        # get_record no se llamó (try_insert tuvo éxito)
        get_record_mock.assert_not_called()

    def test_complete_stores_full_response_body(self, monkeypatch) -> None:
        """El cuerpo guardado contiene todos los campos de InboundResponse."""
        service = AsyncMock()
        service.process_inbound = AsyncMock(return_value=_outcome_respond())
        pending_record = _make_idem_record(status="pending", response_body=None)
        _, _, complete_mock, _ = _patch_db_with_idem(
            monkeypatch, try_insert_return=pending_record
        )

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            client.post(
                "/webhooks/inbound",
                content=body,
                headers={
                    "X-Auyan-Signature": _sign(body),
                    "X-Idempotency-Key": IDEM_KEY,
                },
            )

        stored_body = complete_mock.call_args.kwargs["response_body"]
        required_keys = {
            "ok", "decision", "conversation_id", "inbound_message_id",
            "output_message_id", "escalation_id", "response_text",
            "escalation_reason", "trace_id", "error",
        }
        assert required_keys.issubset(stored_body.keys())


class TestIdempotencyDuplicate:
    """Petición duplicada — se devuelve la respuesta cacheada sin llamar al agente."""

    def test_duplicate_returns_cached_response(self, monkeypatch) -> None:
        service = AsyncMock()
        # try_insert devuelve None → clave ya existe
        done_record = _make_idem_record(status="done")
        try_insert_mock, get_record_mock, complete_mock, _ = _patch_db_with_idem(
            monkeypatch,
            try_insert_return=None,
            get_record_return=done_record,
        )

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={
                    "X-Auyan-Signature": _sign(body),
                    "X-Idempotency-Key": IDEM_KEY,
                },
            )

        assert r.status_code == 200
        data = r.json()
        # Los datos vienen del cache, no del agente
        assert data["decision"] == "respond"
        assert data["response_text"] == "3-5 días."

        # El agente NO se invocó
        service.process_inbound.assert_not_called()
        # complete tampoco, ya estaba done
        complete_mock.assert_not_called()
        # get_record se llamó una vez para recuperar la respuesta
        get_record_mock.assert_awaited_once()

    def test_duplicate_response_is_identical_to_original(self, monkeypatch) -> None:
        """El cuerpo cacheado es idéntico al que devolvería el router."""
        expected_body = {
            "ok": True,
            "decision": "escalate",
            "conversation_id": str(CONVERSATION_ID),
            "inbound_message_id": str(INBOUND_MSG_ID),
            "output_message_id": None,
            "escalation_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            "response_text": None,
            "escalation_reason": "cliente_solicita_humano",
            "trace_id": "trace-esc-1",
            "error": None,
        }
        done_record = _make_idem_record(status="done", response_body=expected_body)
        _patch_db_with_idem(
            monkeypatch,
            try_insert_return=None,
            get_record_return=done_record,
        )

        service = AsyncMock()
        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={
                    "X-Auyan-Signature": _sign(body),
                    "X-Idempotency-Key": IDEM_KEY,
                },
            )

        assert r.status_code == 200
        assert r.json() == expected_body


class TestIdempotencyInFlight:
    """Key en estado pending (procesando) → 409."""

    def test_in_flight_key_returns_409(self, monkeypatch) -> None:
        service = AsyncMock()
        # try_insert falla, get_record devuelve registro pending
        pending_record = _make_idem_record(status="pending", response_body=None)
        _, _, complete_mock, _ = _patch_db_with_idem(
            monkeypatch,
            try_insert_return=None,
            get_record_return=pending_record,
        )

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={
                    "X-Auyan-Signature": _sign(body),
                    "X-Idempotency-Key": IDEM_KEY,
                },
            )

        assert r.status_code == 409
        assert r.json()["detail"] == "idempotency_key_in_flight"
        service.process_inbound.assert_not_called()
        complete_mock.assert_not_called()

    def test_key_conflict_no_existing_record_returns_409(self, monkeypatch) -> None:
        """try_insert falla pero get_record devuelve None (ej: expirado sin limpiar).

        El comportamiento correcto es 409 — no intentamos re-insertar.
        """
        service = AsyncMock()
        _patch_db_with_idem(
            monkeypatch,
            try_insert_return=None,
            get_record_return=None,  # registro expirado/no encontrado
        )

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={
                    "X-Auyan-Signature": _sign(body),
                    "X-Idempotency-Key": IDEM_KEY,
                },
            )

        assert r.status_code == 409
        service.process_inbound.assert_not_called()


class TestIdempotencyErrorRecovery:
    """Si el procesamiento falla, la key debe liberarse para permitir reintentos."""

    def test_agent_error_deletes_key(self, monkeypatch) -> None:
        service = AsyncMock()
        service.process_inbound = AsyncMock(side_effect=RuntimeError("agente explotó"))
        pending_record = _make_idem_record(status="pending", response_body=None)
        _, _, complete_mock, delete_mock = _patch_db_with_idem(
            monkeypatch, try_insert_return=pending_record
        )

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={
                    "X-Auyan-Signature": _sign(body),
                    "X-Idempotency-Key": IDEM_KEY,
                },
            )

        # El endpoint devuelve 500
        assert r.status_code == 500

        # La key fue borrada para permitir reintento
        delete_mock.assert_awaited_once()
        delete_kwargs = delete_mock.call_args.kwargs
        assert delete_kwargs["key"] == IDEM_KEY

        # complete NO se llamó
        complete_mock.assert_not_called()

    def test_db_error_deletes_key(self, monkeypatch) -> None:
        """Error en el tenant_scope (ej: DB caída) también libera la key."""
        service = AsyncMock()
        pending_record = _make_idem_record(status="pending", response_body=None)
        _, _, complete_mock, delete_mock = _patch_db_with_idem(
            monkeypatch, try_insert_return=pending_record
        )
        # Sobreescribir create_conversation para que explote
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.create_conversation",
            AsyncMock(side_effect=Exception("DB timeout")),
        )

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={
                    "X-Auyan-Signature": _sign(body),
                    "X-Idempotency-Key": IDEM_KEY,
                },
            )

        assert r.status_code == 500
        delete_mock.assert_awaited_once()
        complete_mock.assert_not_called()

    def test_error_without_claimed_key_does_not_delete(self, monkeypatch) -> None:
        """Si la key no fue reclamada (error antes), no se intenta borrar."""
        service = AsyncMock()
        # try_insert devuelve None (conflict) y get_record devuelve pending → 409
        # En este caso idempotency_claimed=False, no se debe llamar delete
        pending_record = _make_idem_record(status="pending", response_body=None)
        _, _, _, delete_mock = _patch_db_with_idem(
            monkeypatch,
            try_insert_return=None,
            get_record_return=pending_record,
        )

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            client.post(
                "/webhooks/inbound",
                content=body,
                headers={
                    "X-Auyan-Signature": _sign(body),
                    "X-Idempotency-Key": IDEM_KEY,
                },
            )

        delete_mock.assert_not_called()
