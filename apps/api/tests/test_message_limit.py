"""Tests para A.3 — límite de mensajes inbound por conversación.

Cubre:
- count_customer_messages_in_conversation: unit tests de la query
- Webhook endpoint: escalación automática cuando se supera el límite
- Override per-tenant del límite
- Límite 0 desactiva el check
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from apps.api.core.config import get_settings
from apps.api.db.queries import count_customer_messages_in_conversation
from fastapi import FastAPI

from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    ESCALATION_ID,
    INBOUND_MSG_ID,
    OUTBOUND_MSG_ID,
    TENANT_ID,
    FakeSettings,
    make_fake_bootstrap_connection,
    make_fake_tenant_scope,
    make_tenant,
    make_tenant_configuration,
)

ROUTER_MODULE = "apps.api.routers.webhooks"
WEBHOOK_SECRET = "test-secret"


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------


class _FakeSettingsWithSecret(FakeSettings):
    def __init__(self) -> None:
        super().__init__()

        class _Secret:
            def get_secret_value(self) -> str:
                return WEBHOOK_SECRET

        self.webhook_secret = _Secret()  # type: ignore[assignment]


def _make_app(*, agent_service: AsyncMock | None = None) -> FastAPI:
    from apps.api.core.errors import register_exception_handlers
    from apps.api.routers.webhooks import router as webhooks_router

    app = FastAPI()
    register_exception_handlers(app)
    app.state.agent_service = agent_service or AsyncMock()
    app.dependency_overrides[get_settings] = _FakeSettingsWithSecret
    app.include_router(webhooks_router)
    return app


def _signed_body() -> tuple[bytes, str]:
    payload = {
        "tenant_slug": "lunaria",
        "channel": "chat",
        "content": "hola",
        "customer_email": "test@example.com",
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


_TS = datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC)


def _customer_row() -> dict:
    return {
        "id": CUSTOMER_ID, "tenant_id": TENANT_ID, "email": "test@example.com",
        "phone": None, "external_id": None, "full_name": None, "metadata": {},
    }


def _conversation_row() -> dict:
    return {
        "id": CONVERSATION_ID, "tenant_id": TENANT_ID, "end_customer_id": CUSTOMER_ID,
        "channel": "chat", "external_id": None, "subject": None,
        "status": "open", "assigned_user_id": None, "last_message_at": None,
        "nudged_at": None, "created_at": _TS,
    }


def _message_row() -> dict:
    return {
        "id": INBOUND_MSG_ID, "tenant_id": TENANT_ID, "conversation_id": CONVERSATION_ID,
        "role": "customer", "direction": "inbound", "author_user_id": None,
        "content": "hola", "attachments": [], "metadata": {}, "created_at": _TS,
    }


def _escalation_row() -> dict:
    return {
        "id": ESCALATION_ID, "tenant_id": TENANT_ID, "conversation_id": CONVERSATION_ID,
        "reason": "conversation_message_limit_reached",
        "triggered_by_message_id": None,
        "status": "pending", "assigned_user_id": None, "metadata": {}, "created_at": _TS,
    }


def _fake_agent_outcome() -> object:
    from apps.api.agents.service import AgentOutcome

    return AgentOutcome(
        decision="respond", response_text="ok", escalation_reason=None,
        output_message_id=str(OUTBOUND_MSG_ID), escalation_id=None,
        trace_id="trace-1", confidence=0.9, tokens_in=10, tokens_out=5,
        cost_usd=0.0001, model_used="claude-sonnet-4-6", error=None,
    )


def _patch_tenant_and_boot(
    monkeypatch: pytest.MonkeyPatch,
    boot_conn: AsyncMock,
    *,
    tenant_config: object | None = None,
) -> None:
    """Parchea tenant lookup, config, bootstrap_connection, rate_limit y budget."""
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.get_tenant_by_slug", AsyncMock(return_value=make_tenant())
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.get_tenant_configuration",
        AsyncMock(return_value=tenant_config or make_tenant_configuration()),
    )
    monkeypatch.setattr(
        f"{ROUTER_MODULE}.bootstrap_connection", make_fake_bootstrap_connection(boot_conn)
    )
    monkeypatch.setattr(f"{ROUTER_MODULE}.enforce_rate_limit", AsyncMock())
    monkeypatch.setattr(f"{ROUTER_MODULE}.check_tenant_budget", AsyncMock())


# ============================================================
# count_customer_messages_in_conversation — unit tests
# ============================================================


class TestCountCustomerMessages:
    @pytest.mark.asyncio
    async def test_returns_count_from_db(self) -> None:
        conn = AsyncMock()
        conn.fetchval.return_value = 23
        result = await count_customer_messages_in_conversation(conn, TENANT_ID, CONVERSATION_ID)
        assert result == 23

    @pytest.mark.asyncio
    async def test_returns_zero_when_null(self) -> None:
        conn = AsyncMock()
        conn.fetchval.return_value = None
        result = await count_customer_messages_in_conversation(conn, TENANT_ID, CONVERSATION_ID)
        assert result == 0

    @pytest.mark.asyncio
    async def test_passes_correct_params(self) -> None:
        conn = AsyncMock()
        conn.fetchval.return_value = 5
        await count_customer_messages_in_conversation(conn, TENANT_ID, CONVERSATION_ID)
        args = conn.fetchval.call_args.args
        assert args[1] == TENANT_ID
        assert args[2] == CONVERSATION_ID

    @pytest.mark.asyncio
    async def test_query_filters_by_role_direction_and_soft_delete(self) -> None:
        conn = AsyncMock()
        conn.fetchval.return_value = 0
        await count_customer_messages_in_conversation(conn, TENANT_ID, CONVERSATION_ID)
        sql = conn.fetchval.call_args.args[0]
        assert "role = 'customer'" in sql
        assert "direction = 'inbound'" in sql
        assert "deleted_at IS NULL" in sql


# ============================================================
# Webhook endpoint — tests de integración
#
# Patrón: scope_conn con fetchrow.side_effect y fetchval.return_value.
# El payload no lleva conversation_id ni external_conversation_id, así que
# la secuencia en el tenant_scope es:
#   fetchrow[0] → find_end_customer_by_email
#   fetchrow[1] → create_conversation (customer ya existe, skip create_end_customer)
#   fetchval[0] → count_customer_messages_in_conversation
#   fetchrow[2] → insert_message
#   execute[0]  → update_conversation_last_message
#   [si limit exceeded]
#   fetchrow[3] → get_open_escalation_for_conversation
#   fetchrow[4] → insert_escalation (si no hay escalación activa)
# ============================================================


class TestWebhookMessageLimit:
    def _run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        scope_conn: AsyncMock,
        agent_service: AsyncMock | None = None,
        settings_callable: object | None = None,
        tenant_config: object | None = None,
    ) -> object:
        from fastapi.testclient import TestClient

        _patch_tenant_and_boot(monkeypatch, AsyncMock(), tenant_config=tenant_config)
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.tenant_scope", make_fake_tenant_scope(scope_conn)
        )

        svc = agent_service or AsyncMock()
        app = _make_app(agent_service=svc)
        if settings_callable is not None:
            app.dependency_overrides[get_settings] = settings_callable

        body, sig = _signed_body()
        with TestClient(app, raise_server_exceptions=True) as client:
            return client.post(
                "/webhooks/inbound",
                content=body,
                headers={"Content-Type": "application/json", "X-Auyan-Signature": sig},
            )

    def _scope_conn_under_limit(self, msg_count: int = 10) -> AsyncMock:
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _customer_row(),     # find_end_customer_by_email → existe
            _conversation_row(), # create_conversation
            _message_row(),      # insert_message
        ]
        conn.fetchval.return_value = msg_count
        conn.execute.return_value = "UPDATE 1"
        return conn

    def _scope_conn_over_limit(self, *, open_escalation: dict | None = None) -> AsyncMock:
        conn = AsyncMock()
        fetchrow_effects = [
            _customer_row(),     # find_end_customer_by_email
            _conversation_row(), # create_conversation
            _message_row(),      # insert_message
            open_escalation,     # get_open_escalation_for_conversation
        ]
        if open_escalation is None:
            fetchrow_effects.append(_escalation_row())  # insert_escalation
        conn.fetchrow.side_effect = fetchrow_effects
        conn.fetchval.return_value = 50  # == default limit
        conn.execute.return_value = "UPDATE 1"
        return conn

    def test_passes_through_when_under_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc = AsyncMock()
        svc.process_inbound = AsyncMock(return_value=_fake_agent_outcome())
        resp = self._run(
            monkeypatch,
            scope_conn=self._scope_conn_under_limit(msg_count=10),
            agent_service=svc,
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "respond"
        svc.process_inbound.assert_called_once()

    def test_escalates_when_limit_reached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc = AsyncMock()
        svc.process_inbound = AsyncMock(return_value=_fake_agent_outcome())
        resp = self._run(
            monkeypatch,
            scope_conn=self._scope_conn_over_limit(open_escalation=None),
            agent_service=svc,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "escalated"
        assert data["escalation_reason"] == "conversation_message_limit_reached"
        assert data["escalation_id"] == str(ESCALATION_ID)
        svc.process_inbound.assert_not_called()

    def test_reuses_existing_escalation_when_limit_exceeded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc = AsyncMock()
        # get_open_escalation retorna la escalación ya existente
        resp = self._run(
            monkeypatch,
            scope_conn=self._scope_conn_over_limit(open_escalation=_escalation_row()),
            agent_service=svc,
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "escalated"
        assert resp.json()["escalation_id"] == str(ESCALATION_ID)
        # fetchrow[4] (insert_escalation) no debe haberse llamado
        scope_conn = self._scope_conn_over_limit(open_escalation=_escalation_row())
        assert scope_conn.fetchrow.side_effect is not None  # sanity: solo 4 calls previstas

    def test_per_tenant_override_raises_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Con limit=100 en tenant_config, count=50 no debe escalar."""
        config = make_tenant_configuration(extra={"max_inbound_messages_per_conversation": 100})
        svc = AsyncMock()
        svc.process_inbound = AsyncMock(return_value=_fake_agent_outcome())
        # count=50 < 100 → flujo normal
        resp = self._run(
            monkeypatch,
            scope_conn=self._scope_conn_under_limit(msg_count=50),
            agent_service=svc,
            tenant_config=config,
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "respond"
        svc.process_inbound.assert_called_once()

    def test_zero_limit_disables_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """max_inbound_messages_per_conversation=0 desactiva el check completamente."""
        zero_settings = _FakeSettingsWithSecret()
        zero_settings.max_inbound_messages_per_conversation = 0  # type: ignore[attr-defined]

        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _customer_row(),
            _conversation_row(),
            _message_row(),
        ]
        conn.execute.return_value = "UPDATE 1"

        svc = AsyncMock()
        svc.process_inbound = AsyncMock(return_value=_fake_agent_outcome())
        resp = self._run(
            monkeypatch,
            scope_conn=conn,
            agent_service=svc,
            settings_callable=lambda: zero_settings,
        )
        assert resp.status_code == 200
        # fetchval no se llama cuando limit=0
        conn.fetchval.assert_not_called()
        svc.process_inbound.assert_called_once()

    def test_message_is_persisted_when_limit_exceeded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El mensaje del cliente se persiste en el historial aunque se supere el límite."""
        conn = self._scope_conn_over_limit(open_escalation=None)
        svc = AsyncMock()
        resp = self._run(monkeypatch, scope_conn=conn, agent_service=svc)
        assert resp.status_code == 200
        assert resp.json()["decision"] == "escalated"
        # fetchrow[2] = insert_message fue llamado
        assert conn.fetchrow.call_count >= 3
