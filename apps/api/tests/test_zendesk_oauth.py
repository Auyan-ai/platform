"""Tests del flujo OAuth de Zendesk: state helpers + endpoints authorize + callback."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apps.api.core.errors import ValidationFailed
from apps.api.routers.oauth_zendesk import _build_state, _verify_state

# ---------------------------------------------------------------------------
# _build_state / _verify_state
# ---------------------------------------------------------------------------


class TestStateHelpers:
    def test_roundtrip_valid(self) -> None:
        secret = "webhook_secret_test"
        tenant_id = "11111111-1111-1111-1111-111111111111"
        subdomain = "empresa-test"

        state = _build_state(tenant_id, subdomain, secret)
        t_id, sub = _verify_state(state, secret)

        assert t_id == tenant_id
        assert sub == subdomain

    def test_wrong_secret_raises(self) -> None:
        state = _build_state("tid", "sub", "secreto_correcto")
        with pytest.raises(ValidationFailed, match="invalid_oauth_state"):
            _verify_state(state, "secreto_incorrecto")

    def test_expired_state_raises(self) -> None:
        secret = "s"
        # Construir un state con timestamp muy antiguo
        tenant_id = "11111111-1111-1111-1111-111111111111"
        subdomain = "old"
        old_ts = str(int(time.time()) - 1000)  # > 15 min en el pasado

        import hashlib
        import hmac as hmac_mod

        msg = f"{tenant_id}:{subdomain}:{old_ts}".encode()
        mac = hmac_mod.new(key=secret.encode(), msg=msg, digestmod=hashlib.sha256).hexdigest()
        state = f"{tenant_id}:{subdomain}:{old_ts}:{mac}"

        with pytest.raises(ValidationFailed, match="oauth_state_expired"):
            _verify_state(state, secret)

    def test_malformed_state_raises(self) -> None:
        with pytest.raises(ValidationFailed, match="invalid_oauth_state"):
            _verify_state("solo_dos:partes", "s")

    def test_non_integer_timestamp_raises(self) -> None:
        with pytest.raises(ValidationFailed, match="invalid_oauth_state"):
            _verify_state("a:b:notanumber:mac", "s")

    def test_tampered_tenant_id_fails(self) -> None:
        secret = "s"
        state = _build_state("tid_original", "sub", secret)
        # Reemplazar el tenant_id por otro manteniendo el resto
        parts = state.split(":")
        parts[0] = "tid_alterado"
        tampered = ":".join(parts)
        with pytest.raises(ValidationFailed, match="invalid_oauth_state"):
            _verify_state(tampered, secret)


# ---------------------------------------------------------------------------
# GET /oauth/zendesk/authorize
# ---------------------------------------------------------------------------


class TestZendeskAuthorize:
    def _make_settings(self, **overrides):
        s = MagicMock()
        s.zendesk_oauth_client_id = "client_id_test"
        s.zendesk_oauth_redirect_uri = "https://api.auyan.ai/oauth/zendesk/callback"
        s.webhook_secret.get_secret_value.return_value = "webhook_secret"
        for k, v in overrides.items():
            setattr(s, k, v)
        return s

    @pytest.mark.asyncio
    async def test_redirects_to_zendesk(self) -> None:
        from apps.api.routers.oauth_zendesk import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router)

        from apps.api.core.config import get_settings
        from apps.api.core.security import get_auth_context

        mock_settings = self._make_settings()
        mock_auth = MagicMock()
        mock_auth.role = "super_admin"
        mock_auth.tenant_id = None

        app.dependency_overrides[get_settings] = lambda: mock_settings
        app.dependency_overrides[get_auth_context] = lambda: mock_auth

        client = TestClient(app, follow_redirects=False)
        resp = client.get(
            "/oauth/zendesk/authorize",
            params={
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "subdomain": "empresa-test",
            },
        )

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "empresa-test.zendesk.com/oauth/authorizations/new" in location
        assert "client_id=client_id_test" in location
        assert "response_type=code" in location
        assert "state=" in location

    @pytest.mark.asyncio
    async def test_returns_503_when_not_configured(self) -> None:
        from apps.api.routers.oauth_zendesk import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router)

        from apps.api.core.config import get_settings
        from apps.api.core.security import get_auth_context

        mock_settings = self._make_settings(zendesk_oauth_client_id=None)
        mock_auth = MagicMock()
        mock_auth.role = "super_admin"

        app.dependency_overrides[get_settings] = lambda: mock_settings
        app.dependency_overrides[get_auth_context] = lambda: mock_auth

        client = TestClient(app, follow_redirects=False)
        resp = client.get(
            "/oauth/zendesk/authorize",
            params={"tenant_id": "11111111-1111-1111-1111-111111111111", "subdomain": "x"},
        )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_tenant_admin_cannot_connect_other_tenant(self) -> None:
        from uuid import UUID

        from apps.api.core.errors import register_exception_handlers
        from apps.api.routers.oauth_zendesk import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router)
        register_exception_handlers(app)

        from apps.api.core.config import get_settings
        from apps.api.core.security import get_auth_context

        mock_settings = self._make_settings()
        mock_auth = MagicMock()
        mock_auth.role = "tenant_admin"
        mock_auth.tenant_id = UUID("22222222-2222-2222-2222-222222222222")

        app.dependency_overrides[get_settings] = lambda: mock_settings
        app.dependency_overrides[get_auth_context] = lambda: mock_auth

        client = TestClient(app, follow_redirects=False)
        resp = client.get(
            "/oauth/zendesk/authorize",
            params={
                "tenant_id": "11111111-1111-1111-1111-111111111111",  # tenant diferente
                "subdomain": "x",
            },
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /oauth/zendesk/callback
# ---------------------------------------------------------------------------


class TestZendeskCallback:
    def _make_settings(self, **overrides):
        s = MagicMock()
        s.zendesk_oauth_client_id = "client_id"
        s.zendesk_oauth_client_secret.get_secret_value.return_value = "client_secret"
        s.zendesk_oauth_redirect_uri = "https://api.auyan.ai/oauth/zendesk/callback"
        s.integrations_secret_key.get_secret_value.return_value = "a" * 64
        s.webhook_secret.get_secret_value.return_value = "webhook_secret"
        for k, v in overrides.items():
            setattr(s, k, v)
        return s

    @pytest.mark.asyncio
    async def test_invalid_state_returns_422(self) -> None:
        from apps.api.core.errors import register_exception_handlers
        from apps.api.routers.oauth_zendesk import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router)
        register_exception_handlers(app)

        from apps.api.core.config import get_settings

        app.dependency_overrides[get_settings] = lambda: self._make_settings()

        client = TestClient(app)
        resp = client.get(
            "/oauth/zendesk/callback",
            params={"code": "abc", "state": "estado_invalido"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_successful_callback_persists_token(self) -> None:
        from apps.api.routers.oauth_zendesk import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router)

        from apps.api.core.config import get_settings

        settings = self._make_settings()
        app.dependency_overrides[get_settings] = lambda: settings

        # Construir un state válido
        state = _build_state(
            "11111111-1111-1111-1111-111111111111",
            "empresa-test",
            "webhook_secret",
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "zat_token_abc123", "token_type": "bearer"}
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("apps.api.routers.oauth_zendesk.tenant_scope") as mock_scope,
            patch("apps.api.routers.oauth_zendesk.upsert_integration", new_callable=AsyncMock),
            patch("apps.api.routers.oauth_zendesk.encrypt_credentials", return_value=b"encrypted"),
            patch("apps.api.routers.oauth_zendesk.get_integration_crypto_key", return_value=b"k" * 32),
            patch("httpx.AsyncClient") as MockHttp,
        ):
            mock_http_inst = AsyncMock()
            mock_http_inst.post = AsyncMock(return_value=mock_resp)
            MockHttp.return_value.__aenter__ = AsyncMock(return_value=mock_http_inst)
            MockHttp.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_conn = AsyncMock()
            mock_scope.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_scope.return_value.__aexit__ = AsyncMock(return_value=None)

            client = TestClient(app)
            resp = client.get(
                "/oauth/zendesk/callback",
                params={"code": "zauth_code_xyz", "state": state},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["provider"] == "zendesk"
        assert data["subdomain"] == "empresa-test"
