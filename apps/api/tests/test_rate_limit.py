"""Tests del sistema de rate limiting.

Cubre:
- enforce_rate_limit: tenant bucket, customer bucket, overrides per-tenant
- delete_expired_rate_limit_buckets: retorna count correcto
- Webhook endpoint: 429 cuando el bucket supera el límite
"""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock

import pytest
from apps.api.core.config import get_settings
from apps.api.core.errors import RateLimitError
from apps.api.db.models import TenantConfiguration
from apps.api.services.rate_limit import enforce_rate_limit
from fastapi import FastAPI

from tests.conftest import (
    CUSTOMER_ID,
    TENANT_ID,
    FakeSettings,
    make_fake_bootstrap_connection,
    make_tenant,
    make_tenant_configuration,
)

ROUTER_MODULE = "apps.api.routers.webhooks"
WEBHOOK_SECRET = "test-webhook-secret"


class _SecretLike:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


class _FakeSettingsWithSecret(FakeSettings):
    def __init__(self) -> None:
        super().__init__()
        self.webhook_secret = _SecretLike(WEBHOOK_SECRET)  # type: ignore[assignment]


# ============================================================
# Helpers
# ============================================================


def _make_config(rate_limits: dict | None = None) -> TenantConfiguration:
    extra: dict = {}
    if rate_limits is not None:
        extra["rate_limits"] = rate_limits
    return make_tenant_configuration(extra=extra)


def _make_settings(tenant_limit: int = 300, customer_limit: int = 30) -> FakeSettings:
    s = FakeSettings()
    s.rate_limit_tenant_per_minute = tenant_limit
    s.rate_limit_customer_per_minute = customer_limit
    return s


def _signed_payload(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ============================================================
# enforce_rate_limit — unit tests (conn mockeado)
# ============================================================


class TestEnforceRateLimitTenantBucket:
    """Tests del bucket de tenant."""

    @pytest.mark.asyncio
    async def test_below_limit_does_not_raise(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"count": 1}
        await enforce_rate_limit(
            conn,
            tenant_id=TENANT_ID,
            tenant_config=_make_config(),
            customer_id=None,
            settings=_make_settings(),
        )

    @pytest.mark.asyncio
    async def test_at_limit_does_not_raise(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"count": 300}
        await enforce_rate_limit(
            conn,
            tenant_id=TENANT_ID,
            tenant_config=_make_config(),
            customer_id=None,
            settings=_make_settings(tenant_limit=300),
        )

    @pytest.mark.asyncio
    async def test_above_limit_raises(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"count": 301}
        with pytest.raises(RateLimitError) as exc_info:
            await enforce_rate_limit(
                conn,
                tenant_id=TENANT_ID,
                tenant_config=_make_config(),
                customer_id=None,
                settings=_make_settings(tenant_limit=300),
            )
        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after == 60

    @pytest.mark.asyncio
    async def test_tenant_bucket_key_is_literal_tenant(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"count": 1}
        await enforce_rate_limit(
            conn,
            tenant_id=TENANT_ID,
            tenant_config=_make_config(),
            customer_id=None,
            settings=_make_settings(),
        )
        call_kwargs = conn.fetchrow.call_args
        assert "bucket_key" not in str(call_kwargs) or True  # query por posición
        # Verificamos el argumento posicional $2 = "tenant"
        args = conn.fetchrow.call_args.args
        assert args[2] == "tenant"


class TestEnforceRateLimitCustomerBucket:
    """Tests del bucket por end_customer."""

    @pytest.mark.asyncio
    async def test_no_customer_id_skips_customer_bucket(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"count": 1}
        await enforce_rate_limit(
            conn,
            tenant_id=TENANT_ID,
            tenant_config=_make_config(),
            customer_id=None,
            settings=_make_settings(),
        )
        # Solo 1 llamada (tenant bucket), no la de customer
        assert conn.fetchrow.call_count == 1

    @pytest.mark.asyncio
    async def test_with_customer_id_checks_two_buckets(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"count": 1}
        await enforce_rate_limit(
            conn,
            tenant_id=TENANT_ID,
            tenant_config=_make_config(),
            customer_id=CUSTOMER_ID,
            settings=_make_settings(),
        )
        assert conn.fetchrow.call_count == 2

    @pytest.mark.asyncio
    async def test_customer_above_limit_raises(self) -> None:
        conn = AsyncMock()
        # Tenant ok (count=1), customer supera límite (count=31)
        conn.fetchrow.side_effect = [{"count": 1}, {"count": 31}]
        with pytest.raises(RateLimitError):
            await enforce_rate_limit(
                conn,
                tenant_id=TENANT_ID,
                tenant_config=_make_config(),
                customer_id=CUSTOMER_ID,
                settings=_make_settings(customer_limit=30),
            )

    @pytest.mark.asyncio
    async def test_customer_bucket_key_includes_uuid(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"count": 1}
        await enforce_rate_limit(
            conn,
            tenant_id=TENANT_ID,
            tenant_config=_make_config(),
            customer_id=CUSTOMER_ID,
            settings=_make_settings(),
        )
        second_call_args = conn.fetchrow.call_args_list[1].args
        assert second_call_args[2] == f"customer:{CUSTOMER_ID}"


class TestEnforceRateLimitPerTenantOverrides:
    """Tests de overrides via tenant_config.extra.rate_limits."""

    @pytest.mark.asyncio
    async def test_tenant_override_replaces_default(self) -> None:
        conn = AsyncMock()
        # Con override de 10/min, count=11 debe fallar aunque el default sea 300
        conn.fetchrow.return_value = {"count": 11}
        config = _make_config(rate_limits={"tenant_per_minute": 10})
        with pytest.raises(RateLimitError):
            await enforce_rate_limit(
                conn,
                tenant_id=TENANT_ID,
                tenant_config=config,
                customer_id=None,
                settings=_make_settings(tenant_limit=300),
            )

    @pytest.mark.asyncio
    async def test_tenant_override_increases_limit(self) -> None:
        conn = AsyncMock()
        # Con override de 600/min, count=400 debe pasar
        conn.fetchrow.return_value = {"count": 400}
        config = _make_config(rate_limits={"tenant_per_minute": 600})
        await enforce_rate_limit(
            conn,
            tenant_id=TENANT_ID,
            tenant_config=config,
            customer_id=None,
            settings=_make_settings(tenant_limit=300),
        )

    @pytest.mark.asyncio
    async def test_none_config_uses_defaults(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"count": 1}
        await enforce_rate_limit(
            conn,
            tenant_id=TENANT_ID,
            tenant_config=None,
            customer_id=None,
            settings=_make_settings(),
        )


# ============================================================
# delete_expired_rate_limit_buckets
# ============================================================


class TestDeleteExpiredBuckets:
    @pytest.mark.asyncio
    async def test_returns_deleted_count(self) -> None:
        from apps.api.db.queries import delete_expired_rate_limit_buckets

        conn = AsyncMock()
        conn.execute.return_value = "DELETE 7"
        result = await delete_expired_rate_limit_buckets(conn)
        assert result == 7

    @pytest.mark.asyncio
    async def test_returns_zero_when_none_deleted(self) -> None:
        from apps.api.db.queries import delete_expired_rate_limit_buckets

        conn = AsyncMock()
        conn.execute.return_value = "DELETE 0"
        result = await delete_expired_rate_limit_buckets(conn)
        assert result == 0


# ============================================================
# Webhook endpoint — 429 cuando rate limit se supera
# ============================================================


def _make_webhook_app(*, agent_service: AsyncMock) -> FastAPI:
    from apps.api.core.errors import register_exception_handlers
    from apps.api.routers.webhooks import router as webhooks_router

    app = FastAPI()
    register_exception_handlers(app)
    app.state.agent_service = agent_service
    app.dependency_overrides[get_settings] = _FakeSettingsWithSecret
    app.include_router(webhooks_router)
    return app


def _webhook_body_and_sig(slug: str = "lunaria") -> tuple[bytes, str]:
    import json

    body = json.dumps(
        {
            "tenant_slug": slug,
            "channel": "chat",
            "content": "hola",
            "customer_email": "test@example.com",
        }
    ).encode()
    sig = _signed_payload(body)
    return body, sig


class TestWebhookRateLimit:
    """Tests de integración del rate limit en el endpoint /webhooks/inbound."""

    def test_returns_429_when_tenant_rate_limited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi.testclient import TestClient

        app = _make_webhook_app(agent_service=AsyncMock())
        body, sig = _webhook_body_and_sig()
        tenant = make_tenant()

        fake_conn = AsyncMock()
        fake_conn.fetchrow.return_value = {"count": 9999}

        monkeypatch.setattr(f"{ROUTER_MODULE}.get_tenant_by_slug", AsyncMock(return_value=tenant))
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.get_tenant_configuration", AsyncMock(return_value=_make_config())
        )
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.bootstrap_connection", make_fake_bootstrap_connection(fake_conn)
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"Content-Type": "application/json", "X-Auyan-Signature": sig},
            )

        assert resp.status_code == 429
        assert resp.json()["error"] == "rate_limit_exceeded"
        assert "Retry-After" in resp.headers

    def test_passes_through_when_under_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.agents.service import AgentOutcome
        from fastapi.testclient import TestClient

        from tests.conftest import (
            CONVERSATION_ID,
            INBOUND_MSG_ID,
            OUTBOUND_MSG_ID,
            make_fake_tenant_scope,
        )

        fake_agent_service = AsyncMock()
        app = _make_webhook_app(agent_service=fake_agent_service)
        body, sig = _webhook_body_and_sig()
        tenant = make_tenant()

        fake_boot_conn = AsyncMock()
        fake_boot_conn.fetchrow.return_value = {"count": 1}

        # El payload no lleva conversation_id ni external_conversation_id,
        # así que find_conversation_by_id y find_conversation_by_external NO se llaman.
        fake_scope_conn = AsyncMock()
        fake_scope_conn.fetchrow.side_effect = [
            None,  # find_end_customer_by_email → no existe
            {"id": str(CUSTOMER_ID), "tenant_id": str(TENANT_ID), "email": "test@example.com",
             "phone": None, "external_id": None, "full_name": None, "metadata": {}},
            {"id": str(CONVERSATION_ID), "tenant_id": str(TENANT_ID),
             "end_customer_id": str(CUSTOMER_ID), "channel": "chat", "external_id": None,
             "subject": None, "status": "open", "assigned_user_id": None,
             "last_message_at": None, "nudged_at": None, "created_at": "2026-01-01T00:00:00+00:00"},
            {"id": str(INBOUND_MSG_ID), "tenant_id": str(TENANT_ID),
             "conversation_id": str(CONVERSATION_ID), "role": "customer", "direction": "inbound",
             "author_user_id": None, "content": "hola", "attachments": [], "metadata": {},
             "created_at": "2026-01-01T00:00:00+00:00"},
        ]
        fake_scope_conn.execute.return_value = "UPDATE 1"

        outcome = AgentOutcome(
            decision="respond", response_text="Hola, ¿en qué te ayudo?",
            escalation_reason=None, output_message_id=str(OUTBOUND_MSG_ID),
            escalation_id=None, trace_id="trace-abc", confidence=0.9,
            tokens_in=100, tokens_out=50, cost_usd=0.001,
            model_used="claude-sonnet-4-6", error=None,
        )
        fake_agent_service.process_inbound = AsyncMock(return_value=outcome)

        monkeypatch.setattr(f"{ROUTER_MODULE}.get_tenant_by_slug", AsyncMock(return_value=tenant))
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.get_tenant_configuration", AsyncMock(return_value=_make_config())
        )
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.bootstrap_connection", make_fake_bootstrap_connection(fake_boot_conn)
        )
        monkeypatch.setattr(
            f"{ROUTER_MODULE}.tenant_scope", make_fake_tenant_scope(fake_scope_conn)
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/webhooks/inbound",
                content=body,
                headers={"Content-Type": "application/json", "X-Auyan-Signature": sig},
            )

        assert resp.status_code == 200
        assert resp.json()["decision"] == "respond"
