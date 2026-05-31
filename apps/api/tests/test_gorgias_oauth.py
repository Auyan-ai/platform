"""Tests del flujo OAuth de Gorgias: state helpers + endpoints authorize + callback."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.core.errors import ValidationFailed
from apps.api.routers.oauth_gorgias import _build_state, _verify_state

# ---------------------------------------------------------------------------
# _build_state / _verify_state
# ---------------------------------------------------------------------------


class TestStateHelpers:
    def test_roundtrip_valid(self) -> None:
        secret = "webhook_secret_test"
        tenant_id = "11111111-1111-1111-1111-111111111111"
        domain = "mitienda"

        state = _build_state(tenant_id, domain, secret)
        t_id, dom = _verify_state(state, secret)

        assert t_id == tenant_id
        assert dom == domain

    def test_wrong_secret_raises(self) -> None:
        state = _build_state("tid", "dom", "secreto_correcto")
        with pytest.raises(ValidationFailed, match="invalid_oauth_state"):
            _verify_state(state, "secreto_incorrecto")

    def test_expired_state_raises(self) -> None:
        secret = "s"
        tenant_id = "11111111-1111-1111-1111-111111111111"
        domain = "old"
        old_ts = str(int(time.time()) - 1000)  # > 15 min en el pasado

        import hashlib
        import hmac as hmac_mod

        msg = f"{tenant_id}:{domain}:{old_ts}".encode()
        mac = hmac_mod.new(key=secret.encode(), msg=msg, digestmod=hashlib.sha256).hexdigest()
        state = f"{tenant_id}:{domain}:{old_ts}:{mac}"

        with pytest.raises(ValidationFailed, match="oauth_state_expired"):
            _verify_state(state, secret)

    def test_malformed_state_raises(self) -> None:
        with pytest.raises(ValidationFailed, match="invalid_oauth_state"):
            _verify_state("solo_dos:partes", "s")

    def test_non_integer_timestamp_raises(self) -> None:
        with pytest.raises(ValidationFailed, match="invalid_oauth_state"):
            _verify_state("a:b:notanumber:mac", "s")

    def test_tampered_domain_fails(self) -> None:
        secret = "s"
        state = _build_state("tid", "original", secret)
        parts = state.split(":")
        tampered = f"{parts[0]}:otrodomain:{parts[2]}:{parts[3]}"
        with pytest.raises(ValidationFailed, match="invalid_oauth_state"):
            _verify_state(tampered, secret)

    def test_state_has_four_parts(self) -> None:
        state = _build_state(
            "11111111-1111-1111-1111-111111111111", "mitienda", "secret"
        )
        parts = state.split(":")
        assert len(parts) == 4


# ---------------------------------------------------------------------------
# GET /oauth/gorgias/authorize
# ---------------------------------------------------------------------------


def _make_settings(**overrides):
    s = MagicMock()
    s.gorgias_oauth_client_id = "client_id_test"
    s.gorgias_oauth_client_secret = MagicMock()
    s.gorgias_oauth_client_secret.get_secret_value.return_value = "client_secret_test"
    s.gorgias_oauth_redirect_uri = "https://api.auyan.ai/oauth/gorgias/callback"
    s.webhook_secret = MagicMock()
    s.webhook_secret.get_secret_value.return_value = "webhook_secret_test"
    s.integrations_secret_key = MagicMock()
    s.integrations_secret_key.get_secret_value.return_value = "a" * 64
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_app(mock_settings=None, mock_auth=None):
    from apps.api.core.config import get_settings
    from apps.api.core.errors import register_exception_handlers
    from apps.api.core.security import get_auth_context
    from apps.api.routers.oauth_gorgias import router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)

    if mock_settings:
        app.dependency_overrides[get_settings] = lambda: mock_settings
    if mock_auth:
        app.dependency_overrides[get_auth_context] = lambda: mock_auth

    return TestClient(app, follow_redirects=False)


class TestAuthorizeEndpoint:
    def test_redirects_to_gorgias(self) -> None:
        mock_auth = MagicMock()
        mock_auth.role = "super_admin"
        mock_auth.tenant_id = None

        client = _make_app(_make_settings(), mock_auth)
        resp = client.get(
            "/oauth/gorgias/authorize",
            params={"tenant_id": "11111111-1111-1111-1111-111111111111", "domain": "mitienda"},
        )

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "mitienda.gorgias.com/oauth/authorize" in location
        assert "client_id=client_id_test" in location
        assert "response_type=code" in location
        assert "state=" in location

    def test_returns_503_when_not_configured(self) -> None:
        mock_auth = MagicMock()
        mock_auth.role = "super_admin"

        client = _make_app(_make_settings(gorgias_oauth_client_id=None), mock_auth)
        resp = client.get(
            "/oauth/gorgias/authorize",
            params={"tenant_id": "11111111-1111-1111-1111-111111111111", "domain": "x"},
        )
        assert resp.status_code == 503

    def test_format_json_returns_authorize_url(self) -> None:
        """Con ?format=json el endpoint devuelve {authorize_url} en lugar de 302.
        Lo usa el wizard del cliente: fetch con Bearer no puede seguir un 302 a otro dominio."""
        mock_auth = MagicMock()
        mock_auth.role = "super_admin"
        mock_auth.tenant_id = None

        client = _make_app(_make_settings(), mock_auth)
        resp = client.get(
            "/oauth/gorgias/authorize",
            params={
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "domain": "mitienda",
                "format": "json",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert "authorize_url" in body
        assert "mitienda.gorgias.com/oauth/authorize" in body["authorize_url"]
        assert "client_id=client_id_test" in body["authorize_url"]

    def test_tenant_admin_cannot_connect_other_tenant(self) -> None:
        from uuid import UUID

        mock_auth = MagicMock()
        mock_auth.role = "tenant_admin"
        mock_auth.tenant_id = UUID("22222222-2222-2222-2222-222222222222")

        client = _make_app(_make_settings(), mock_auth)
        resp = client.get(
            "/oauth/gorgias/authorize",
            params={"tenant_id": "11111111-1111-1111-1111-111111111111", "domain": "other"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /oauth/gorgias/callback
# ---------------------------------------------------------------------------


class TestCallbackEndpoint:
    def test_callback_with_invalid_state_returns_422(self) -> None:
        client = _make_app(_make_settings())
        resp = client.get(
            "/oauth/gorgias/callback",
            params={"code": "abc", "state": "invalid:state"},
        )
        assert resp.status_code == 422

    def test_callback_with_valid_state_exchanges_code(self) -> None:
        from unittest.mock import patch as _patch

        settings = _make_settings()
        secret = settings.webhook_secret.get_secret_value()
        tenant_id = "11111111-1111-1111-1111-111111111111"
        domain = "mitienda"
        state = _build_state(tenant_id, domain, secret)

        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {"access_token": "gorgias_token_xyz"}
        mock_token_resp.raise_for_status = MagicMock()

        client = _make_app(settings)

        with (
            _patch("httpx.AsyncClient") as MockHTTP,
            _patch("apps.api.routers.oauth_gorgias.upsert_integration", new=AsyncMock()),
            _patch("apps.api.routers.oauth_gorgias.tenant_scope") as mock_scope,
            _patch(
                "apps.api.routers.oauth_gorgias.get_integration_crypto_key",
                return_value=b"k" * 32,
            ),
            _patch(
                "apps.api.routers.oauth_gorgias.encrypt_credentials",
                return_value=b"encrypted",
            ),
        ):
            mock_conn = AsyncMock()
            mock_scope.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)
            MockHTTP.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_token_resp
            )

            resp = client.get(
                "/oauth/gorgias/callback",
                params={"code": "authcode123", "state": state},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["provider"] == "gorgias"
        assert body["domain"] == domain
