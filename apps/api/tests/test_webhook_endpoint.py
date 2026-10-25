"""Tests del endpoint HTTP `POST /webhooks/inbound`.

Construimos una FastAPI app de tests (sin lifespan) y montamos sólo el router.
Mockeamos el AgentService, las queries de DB y `tenant_scope` para aislar la
prueba al transporte HTTP + HMAC + payload + flujo del router.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from apps.api.agents.service import AgentOutcome
from apps.api.core.config import get_settings
from apps.api.routers.webhooks import router as webhooks_router
from apps.api.services.handoff import APPROVAL_GATE_PREFIX
from apps.api.services.inbound_media import fallback_message
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import (
    CONVERSATION_ID,
    ESCALATION_ID,
    INBOUND_MSG_ID,
    OUTBOUND_MSG_ID,
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


class _FakeSettingsWithSecret(FakeSettings):
    def __init__(self) -> None:
        super().__init__()
        self.webhook_secret = _SecretLike(WEBHOOK_SECRET)


class _SecretLike:
    """Imita pydantic.SecretStr para el endpoint."""

    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _outcome_respond() -> AgentOutcome:
    return AgentOutcome(
        decision="respond",
        response_text="3-5 días.",
        escalation_reason=None,
        output_message_id=str(OUTBOUND_MSG_ID),
        escalation_id=None,
        resolves_on_delivery=False,
        trace_id="trace-1",
        confidence=0.92,
        tokens_in=120,
        tokens_out=35,
        cost_usd=0.0008,
        model_used="claude-sonnet-4-6",
        error=None,
    )


def _outcome_escalate() -> AgentOutcome:
    return AgentOutcome(
        decision="escalate",
        response_text=None,
        escalation_reason="out_of_scope",
        output_message_id=None,
        escalation_id=str(ESCALATION_ID),
        resolves_on_delivery=False,
        trace_id="trace-2",
        confidence=0.30,
        tokens_in=80,
        tokens_out=5,
        cost_usd=0.0003,
        model_used="claude-sonnet-4-6",
        error=None,
    )


def _make_app(*, agent_service: AsyncMock) -> FastAPI:
    """Construye una app de test sin lifespan."""
    app = FastAPI()
    app.state.agent_service = agent_service
    app.dependency_overrides[get_settings] = _FakeSettingsWithSecret
    app.include_router(webhooks_router)
    return app


def _valid_payload() -> dict:
    return {
        "tenant_slug": "acme",
        "channel": "chat",
        "content": "¿Cuánto tarda el envío a Argentina?",
        "external_conversation_id": "ext-conv-1",
        "customer_email": "juan@example.com",
        "customer_name": "Juan",
        "subject": "Envíos",
    }


def _patch_db(
    monkeypatch,
    *,
    tenant=None,
    customer=None,
    conversation=None,
    inbound_msg=None,
) -> None:
    """Parchea bootstrap_connection, tenant_scope y queries en el módulo del router."""
    monkeypatch.setattr(f"{ROUTER_MODULE}.bootstrap_connection", make_fake_bootstrap_connection())
    monkeypatch.setattr(f"{ROUTER_MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.get_tenant_configuration",
        AsyncMock(return_value=make_tenant_configuration()),
    )
    monkeypatch.setattr(f"{ROUTER_MODULE}.enforce_rate_limit", AsyncMock())
    monkeypatch.setattr(f"{ROUTER_MODULE}.check_tenant_budget", AsyncMock())
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.get_tenant_by_slug",
        AsyncMock(return_value=tenant if tenant is not None else make_tenant()),
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.find_end_customer_by_email",
        AsyncMock(return_value=customer),
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.create_end_customer",
        AsyncMock(return_value=customer if customer else make_end_customer()),
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.find_conversation_by_id",
        AsyncMock(return_value=conversation),
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.find_conversation_by_external",
        AsyncMock(return_value=conversation),
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.create_conversation",
        AsyncMock(return_value=conversation if conversation else make_conversation()),
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.insert_message",
        AsyncMock(return_value=inbound_msg if inbound_msg else make_message(id=INBOUND_MSG_ID)),
    )
    monkeypatch.setattr(f"{ROUTER_MODULE}.update_conversation_last_message", AsyncMock())


class TestInboundEndpoint:
    def test_happy_path_respond(self, monkeypatch) -> None:
        service = AsyncMock()
        service.process_inbound = AsyncMock(return_value=_outcome_respond())
        _patch_db(monkeypatch)

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={
                    "X-Auyan-Signature": _sign(body),
                    "Content-Type": "application/json",
                },
            )

        assert r.status_code == 200
        body_out = r.json()
        assert body_out["ok"] is True
        assert body_out["decision"] == "respond"
        assert body_out["response_text"] == "3-5 días."
        assert body_out["output_message_id"] == str(OUTBOUND_MSG_ID)
        assert body_out["trace_id"] == "trace-1"
        service.process_inbound.assert_awaited_once()

    def test_resolving_reply_finalizes_resolution_as_delivered(self, monkeypatch) -> None:
        """El endpoint devuelve la respuesta en el body HTTP → cuenta como entregada."""
        outcome = dataclasses.replace(_outcome_respond(), resolves_on_delivery=True)
        service = AsyncMock()
        service.process_inbound = AsyncMock(return_value=outcome)
        _patch_db(monkeypatch)
        finalize = AsyncMock(return_value=True)
        monkeypatch.setattr(f"{ROUTER_MODULE}.finalize_agent_resolution", finalize)

        body = json.dumps(_valid_payload()).encode()
        with TestClient(_make_app(agent_service=service)) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body), "Content-Type": "application/json"},
            )

        assert r.status_code == 200
        finalize.assert_awaited_once()
        assert finalize.await_args.kwargs["delivered"] is True

    def test_non_resolving_reply_does_not_finalize(self, monkeypatch) -> None:
        service = AsyncMock()
        service.process_inbound = AsyncMock(return_value=_outcome_respond())
        _patch_db(monkeypatch)
        finalize = AsyncMock()
        monkeypatch.setattr(f"{ROUTER_MODULE}.finalize_agent_resolution", finalize)

        body = json.dumps(_valid_payload()).encode()
        with TestClient(_make_app(agent_service=service)) as client:
            client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body), "Content-Type": "application/json"},
            )

        finalize.assert_not_awaited()

    def test_happy_path_escalate(self, monkeypatch) -> None:
        service = AsyncMock()
        service.process_inbound = AsyncMock(return_value=_outcome_escalate())
        _patch_db(monkeypatch)

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body)},
            )

        assert r.status_code == 200
        body_out = r.json()
        assert body_out["decision"] == "escalate"
        assert body_out["escalation_reason"] == "out_of_scope"
        assert body_out["escalation_id"] == str(ESCALATION_ID)
        assert body_out["response_text"] == fallback_message("escalation_ack", None)

    def _post_chat(self, monkeypatch, outcome: AgentOutcome, channel: str = "chat"):
        service = AsyncMock()
        service.process_inbound = AsyncMock(return_value=outcome)
        _patch_db(monkeypatch)
        insert = AsyncMock(return_value=make_message(id=OUTBOUND_MSG_ID, role="agent_ai"))
        monkeypatch.setattr(f"{ROUTER_MODULE}.insert_message", insert)
        payload = {**_valid_payload(), "channel": channel}
        body = json.dumps(payload).encode()
        with TestClient(_make_app(agent_service=service)) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body)},
            )
        return r, insert

    def test_chat_low_confidence_escalation_gets_ack_and_outbound_message(
        self, monkeypatch
    ) -> None:
        outcome = dataclasses.replace(
            _outcome_escalate(),
            escalation_reason="low_confidence: 0.50 < threshold 0.60",
            confidence=0.5,
        )
        r, insert = self._post_chat(monkeypatch, outcome)

        assert r.status_code == 200
        body = r.json()
        ack = fallback_message("escalation_ack", None)
        assert body["decision"] == "escalate"
        assert body["response_text"] == ack
        assert body["output_message_id"] == str(OUTBOUND_MSG_ID)
        outbound = [
            c.kwargs for c in insert.await_args_list if c.kwargs.get("direction") == "outbound"
        ]
        assert len(outbound) == 1
        assert outbound[0]["content"] == ack
        assert outbound[0]["role"] == "agent_ai"
        assert outbound[0]["metadata"] == {"fixed_message": "escalation_ack"}

    def test_chat_ack_speaks_the_conversation_language(self, monkeypatch) -> None:
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.conversation_text_languages",
            AsyncMock(return_value=("en", "es")),
        )
        outcome = dataclasses.replace(
            _outcome_escalate(),
            escalation_reason="low_confidence: 0.50 < threshold 0.60",
            confidence=0.5,
        )
        r, insert = self._post_chat(monkeypatch, outcome)

        ack = fallback_message("escalation_ack", None, language="en")
        assert ack.startswith("I've passed your question")
        assert r.json()["response_text"] == ack
        outbound = [
            c.kwargs for c in insert.await_args_list if c.kwargs.get("direction") == "outbound"
        ]
        assert outbound[0]["content"] == ack

    def test_chat_provider_outage_escalation_gets_ack(self, monkeypatch) -> None:
        reason = "llm_provider_unavailable: credit_balance_exhausted (node reason)"
        outcome = dataclasses.replace(
            _outcome_escalate(), decision="error", escalation_reason=reason, error=reason
        )
        r, insert = self._post_chat(monkeypatch, outcome)

        body = r.json()
        assert body["decision"] == "error"
        assert body["escalation_reason"] == reason
        assert body["response_text"] == fallback_message("escalation_ack", None)
        assert body["output_message_id"] == str(OUTBOUND_MSG_ID)

    def test_chat_error_without_escalation_gets_no_ack(self, monkeypatch) -> None:
        outcome = dataclasses.replace(
            _outcome_escalate(), decision="error", escalation_id=None, error="boom"
        )
        r, _ = self._post_chat(monkeypatch, outcome)

        assert r.json()["response_text"] is None

    def test_chat_approval_gate_escalation_gets_no_ack(self, monkeypatch) -> None:
        outcome = dataclasses.replace(
            _outcome_escalate(), escalation_reason=f"{APPROVAL_GATE_PREFIX}refund"
        )
        r, insert = self._post_chat(monkeypatch, outcome)

        assert r.json()["response_text"] is None
        assert [c for c in insert.await_args_list if c.kwargs.get("direction") == "outbound"] == []

    def test_chat_escalation_with_llm_text_gets_no_extra_ack(self, monkeypatch) -> None:
        outcome = dataclasses.replace(
            _outcome_escalate(), response_text="No tengo ese dato, te paso con el equipo."
        )
        r, insert = self._post_chat(monkeypatch, outcome)

        assert r.json()["response_text"] == "No tengo ese dato, te paso con el equipo."
        assert [c for c in insert.await_args_list if c.kwargs.get("direction") == "outbound"] == []

    def test_non_chat_escalation_gets_no_ack(self, monkeypatch) -> None:
        r, insert = self._post_chat(monkeypatch, _outcome_escalate(), channel="zendesk")

        assert r.json()["response_text"] is None
        assert [c for c in insert.await_args_list if c.kwargs.get("direction") == "outbound"] == []

    def test_invalid_signature_returns_401(self, monkeypatch) -> None:
        service = AsyncMock()
        _patch_db(monkeypatch)
        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": "sha256=" + "0" * 64},
            )

        assert r.status_code == 401
        # El service NO debe haberse llamado
        service.process_inbound.assert_not_called()

    def test_missing_signature_header_returns_401(self, monkeypatch) -> None:
        service = AsyncMock()
        _patch_db(monkeypatch)
        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post("/webhooks/inbound", content=body)

        assert r.status_code == 401

    def test_invalid_payload_returns_400(self, monkeypatch) -> None:
        """Payload sin campos requeridos → 400. Signature debe validarse ANTES."""
        service = AsyncMock()
        _patch_db(monkeypatch)
        body = json.dumps({"channel": "chat"}).encode()  # falta tenant_slug + content
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body)},
            )

        assert r.status_code == 400
        service.process_inbound.assert_not_called()

    def test_tenant_not_found_returns_404(self, monkeypatch) -> None:
        service = AsyncMock()
        _patch_db(monkeypatch, tenant=None)  # get_tenant_by_slug devuelve None
        # Pero create_end_customer etc no se va a llamar porque cortamos antes
        # Reparchamos get_tenant_by_slug a None
        monkeypatch.setattr(f"{ROUTER_MODULE}.get_tenant_by_slug", AsyncMock(return_value=None))

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body)},
            )

        assert r.status_code == 404
        service.process_inbound.assert_not_called()

    def test_tenant_inactive_returns_403(self, monkeypatch) -> None:
        service = AsyncMock()
        _patch_db(monkeypatch)
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.get_tenant_by_slug",
            AsyncMock(return_value=make_tenant(status="suspended")),
        )

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body)},
            )

        assert r.status_code == 403
        service.process_inbound.assert_not_called()

    def test_demo_tenant_is_rejected_with_explicit_reason(self, monkeypatch) -> None:
        service = AsyncMock()
        _patch_db(monkeypatch)
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.get_tenant_by_slug",
            AsyncMock(
                return_value=make_tenant(
                    slug="demo-alohas-ab12cd",
                    origin="demo",
                    demo_expires_at=datetime(2026, 11, 24, tzinfo=UTC),
                    demo_source_url="https://alohas.es",
                )
            ),
        )

        body = json.dumps(_valid_payload()).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body)},
            )

        assert r.status_code == 403
        assert r.json()["detail"] == "tenant_is_demo"
        service.process_inbound.assert_not_called()

    def test_signature_validated_before_payload_parsing(self, monkeypatch) -> None:
        """Defense-in-depth: cuerpo basura con signature inválida → 401, no 400.

        Si dejáramos parsear primero, un atacante podría inducir 400/422 con
        bodies maliciosos sin tener la firma.
        """
        service = AsyncMock()
        _patch_db(monkeypatch)
        body = b"this is not json at all"
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": "sha256=" + "f" * 64},
            )

        assert r.status_code == 401

    def test_unknown_channel_returns_400(self, monkeypatch) -> None:
        """Pydantic Literal[...] rechaza canales fuera del enum."""
        service = AsyncMock()
        _patch_db(monkeypatch)
        payload = _valid_payload()
        payload["channel"] = "telegram"  # no está en ChannelType
        body = json.dumps(payload).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body)},
            )

        assert r.status_code == 400


class TestMultiTurn:
    def test_conversation_id_reuses_existing_conversation(self, monkeypatch) -> None:
        """Pasar conversation_id reutiliza la conversación existente sin crear una nueva."""
        existing_conv = make_conversation()
        service = AsyncMock()
        service.process_inbound = AsyncMock(return_value=_outcome_respond())

        find_by_id_mock = AsyncMock(return_value=existing_conv)
        find_by_external_mock = AsyncMock(return_value=None)
        create_conv_mock = AsyncMock()

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
            f"{ROUTER_MODULE}.create_end_customer", AsyncMock(return_value=make_end_customer())
        )
        monkeypatch.setattr(f"{ROUTER_MODULE}.find_conversation_by_id", find_by_id_mock)
        monkeypatch.setattr(f"{ROUTER_MODULE}.find_conversation_by_external", find_by_external_mock)
        monkeypatch.setattr(f"{ROUTER_MODULE}.create_conversation", create_conv_mock)
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.insert_message",
            AsyncMock(return_value=make_message(id=INBOUND_MSG_ID)),
        )
        monkeypatch.setattr(f"{ROUTER_MODULE}.update_conversation_last_message", AsyncMock())

        payload = {
            "tenant_slug": "acme",
            "channel": "chat",
            "content": "segundo mensaje del cliente",
            "customer_email": "maria@test.es",
            "conversation_id": str(CONVERSATION_ID),
        }
        body = json.dumps(payload).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body), "Content-Type": "application/json"},
            )

        assert r.status_code == 200
        find_by_id_mock.assert_called_once()
        find_by_external_mock.assert_not_called()
        create_conv_mock.assert_not_called()
        assert r.json()["conversation_id"] == str(CONVERSATION_ID)

    def test_without_conversation_id_creates_new(self, monkeypatch) -> None:
        """Sin conversation_id se crea conversación nueva (comportamiento original)."""
        service = AsyncMock()
        service.process_inbound = AsyncMock(return_value=_outcome_respond())
        create_conv_mock = AsyncMock(return_value=make_conversation())

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
            f"{ROUTER_MODULE}.find_end_customer_by_email", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.create_end_customer", AsyncMock(return_value=make_end_customer())
        )
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.find_conversation_by_id", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.find_conversation_by_external", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(f"{ROUTER_MODULE}.create_conversation", create_conv_mock)
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.insert_message",
            AsyncMock(return_value=make_message(id=INBOUND_MSG_ID)),
        )
        monkeypatch.setattr(f"{ROUTER_MODULE}.update_conversation_last_message", AsyncMock())

        payload = {
            "tenant_slug": "acme",
            "channel": "chat",
            "content": "primer mensaje del cliente",
            "customer_email": "nuevo@test.es",
        }
        body = json.dumps(payload).encode()
        app = _make_app(agent_service=service)

        with TestClient(app) as client:
            r = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"X-Auyan-Signature": _sign(body), "Content-Type": "application/json"},
            )

        assert r.status_code == 200
        create_conv_mock.assert_called_once()
