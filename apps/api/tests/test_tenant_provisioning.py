"""Tests del provisioning service y del endpoint POST /tenants."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from apps.api.db.models import Tenant
from apps.api.services.tenant_provisioning import (
    ProvisionRequest,
    SlugTakenError,
    SupabaseAdminError,
    provision_tenant,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


SUPABASE_URL = "https://proj.supabase.co"
SERVICE_ROLE = "service_role_test"
CREATOR_INTERNAL_USER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
AUTH_USER_ID = UUID("99999999-9999-9999-9999-999999999999")


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.supabase_url = SUPABASE_URL
    s.supabase_service_role_key = MagicMock()
    s.supabase_service_role_key.get_secret_value.return_value = SERVICE_ROLE
    return s


def _make_request(slug: str = "lunaria-2") -> ProvisionRequest:
    return ProvisionRequest(
        company_name="Lunaria 2",
        slug=slug,
        plan_tier="founding",
        tenant_admin_email="admin@lunaria.test",
        tenant_admin_name="Admin Lunaria",
        creator_internal_user_id=CREATOR_INTERNAL_USER_ID,
    )


def _make_conn(slug_taken: bool = False) -> MagicMock:
    """Mockea asyncpg.Connection con transaction() async context y métodos básicos."""
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=1 if slug_taken else None)

    # INSERT INTO tenants ... RETURNING
    def _tenant_row() -> dict[str, Any]:
        return {
            "id": uuid4(),
            "slug": "lunaria-2",
            "name": "Lunaria 2",
            "status": "active",
            "agent_lifecycle_state": "discovery",
            "plan_tier": "founding",
        }

    conn.fetchrow = AsyncMock(side_effect=lambda *a, **kw: _tenant_row())
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    # transaction() debe ser un async context manager
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)
    return conn


def _make_http(transport: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport)


# ---------------------------------------------------------------------------
# Service: provision_tenant
# ---------------------------------------------------------------------------


class TestProvisionService:
    @pytest.mark.asyncio
    async def test_happy_path_invites_new_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = _make_conn(slug_taken=False)
        # El seeding de los AOPs canónicos se prueba aparte (test_canonical_aops); aquí no-op.
        monkeypatch.setattr(
            "apps.api.services.tenant_provisioning.provision_canonical_aops",
            AsyncMock(return_value={"created": 8, "updated": 0, "skipped": 0, "tool_permissions": 11}),
        )

        async def _handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/auth/v1/invite"
            assert request.headers["authorization"] == f"Bearer {SERVICE_ROLE}"
            return httpx.Response(200, json={"id": str(AUTH_USER_ID), "email": "admin@lunaria.test"})

        http = _make_http(httpx.MockTransport(_handler))
        result = await provision_tenant(
            conn, settings=_make_settings(), http=http, request=_make_request()
        )

        assert result.tenant_admin_user_id == AUTH_USER_ID
        assert result.invite_sent is True
        assert isinstance(result.tenant, Tenant)
        assert result.tenant.agent_lifecycle_state == "discovery"
        assert result.tenant.plan_tier == "founding"

        # Verificó slug, insertó tenant + user + onboarding + assignment + config + prompt.
        conn.fetchval.assert_awaited_once()
        # 5 execute: users, tenant_onboarding, tenant_assignments,
        # tenant_configurations, tenant_prompts (fetchrow ya cuenta INSERT tenants).
        assert conn.execute.await_count == 5

        sql_calls = [call.args[0] for call in conn.execute.await_args_list]
        assert any("INSERT INTO tenant_configurations" in sql for sql in sql_calls)
        prompt_call = next(
            call for call in conn.execute.await_args_list
            if "INSERT INTO tenant_prompts" in call.args[0]
        )
        # El prompt base interpola el company_name del request.
        assert "Lunaria 2" in prompt_call.args[2]

    @pytest.mark.asyncio
    async def test_slug_taken_raises_before_supabase(self) -> None:
        conn = _make_conn(slug_taken=True)
        called = {"hit": False}

        async def _handler(request: httpx.Request) -> httpx.Response:
            called["hit"] = True
            return httpx.Response(200, json={"id": str(AUTH_USER_ID)})

        http = _make_http(httpx.MockTransport(_handler))
        with pytest.raises(SlugTakenError):
            await provision_tenant(
                conn, settings=_make_settings(), http=http, request=_make_request("taken")
            )
        assert called["hit"] is False
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_email_exists_falls_back_to_find_and_magic_link(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = _make_conn(slug_taken=False)
        monkeypatch.setattr(
            "apps.api.services.tenant_provisioning.provision_canonical_aops",
            AsyncMock(return_value={"created": 8, "updated": 0, "skipped": 0, "tool_permissions": 11}),
        )
        calls: list[str] = []

        async def _handler(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url.path}")
            if request.url.path == "/auth/v1/invite":
                return httpx.Response(
                    422, json={"msg": "Email address already registered"}
                )
            if request.url.path == "/auth/v1/admin/users":
                return httpx.Response(
                    200, json={"users": [{"id": str(AUTH_USER_ID), "email": "admin@lunaria.test"}]}
                )
            if request.url.path == "/auth/v1/admin/generate_link":
                return httpx.Response(200, json={"properties": {"action_link": "https://link"}})
            return httpx.Response(404)

        http = _make_http(httpx.MockTransport(_handler))
        result = await provision_tenant(
            conn, settings=_make_settings(), http=http, request=_make_request()
        )
        assert result.tenant_admin_user_id == AUTH_USER_ID
        assert result.invite_sent is True
        assert calls == [
            "POST /auth/v1/invite",
            "GET /auth/v1/admin/users",
            "POST /auth/v1/admin/generate_link",
        ]

    @pytest.mark.asyncio
    async def test_email_exists_but_not_found_raises(self) -> None:
        conn = _make_conn(slug_taken=False)

        async def _handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/auth/v1/invite":
                return httpx.Response(422, json={"msg": "already registered"})
            if request.url.path == "/auth/v1/admin/users":
                return httpx.Response(200, json={"users": []})
            return httpx.Response(404)

        http = _make_http(httpx.MockTransport(_handler))
        with pytest.raises(SupabaseAdminError):
            await provision_tenant(
                conn, settings=_make_settings(), http=http, request=_make_request()
            )

    @pytest.mark.asyncio
    async def test_supabase_500_raises(self) -> None:
        conn = _make_conn(slug_taken=False)

        async def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="upstream down")

        http = _make_http(httpx.MockTransport(_handler))
        with pytest.raises(SupabaseAdminError):
            await provision_tenant(
                conn, settings=_make_settings(), http=http, request=_make_request()
            )


# ---------------------------------------------------------------------------
# Endpoint: POST /tenants
# ---------------------------------------------------------------------------


def _make_internal_user() -> MagicMock:
    u = MagicMock()
    u.id = CREATOR_INTERNAL_USER_ID
    return u


def _make_endpoint_app(auth_role: str = "super_admin"):
    from apps.api.core.config import get_settings
    from apps.api.core.errors import register_exception_handlers
    from apps.api.core.security import get_auth_context
    from apps.api.routers.tenants import router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)

    auth = MagicMock()
    auth.role = auth_role
    auth.user_id = UUID("11111111-1111-1111-1111-1111111111aa")
    auth.tenant_id = None if auth_role == "super_admin" else uuid4()

    app.dependency_overrides[get_settings] = _make_settings
    app.dependency_overrides[get_auth_context] = lambda: auth
    return TestClient(app)


class TestCreateTenantEndpoint:
    def _payload(self) -> dict[str, str]:
        return {
            "company_name": "Lunaria 2",
            "slug": "lunaria-2",
            "plan_tier": "founding",
            "tenant_admin_email": "admin@lunaria.test",
            "tenant_admin_name": "Admin",
        }

    def test_201_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.db import client as db_client
        from apps.api.routers import tenants as tenants_router

        async def _fake_provision(conn, *, settings, http, request):
            from apps.api.services.tenant_provisioning import ProvisionResult

            tenant = Tenant(
                id=uuid4(),
                slug=request.slug,
                name=request.company_name,
                status="active",
                agent_lifecycle_state="discovery",
                plan_tier=request.plan_tier,
            )
            return ProvisionResult(
                tenant=tenant, tenant_admin_user_id=AUTH_USER_ID, invite_sent=True
            )

        async def _fake_bootstrap():
            class _Ctx:
                async def __aenter__(self):
                    return MagicMock()

                async def __aexit__(self, *a):
                    return None

            return _Ctx()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_bootstrap_cm():
            yield MagicMock()

        async def _fake_get_internal(conn, user_id):
            return _make_internal_user()

        monkeypatch.setattr(tenants_router, "provision_tenant", _fake_provision)
        monkeypatch.setattr(tenants_router, "bootstrap_connection", _fake_bootstrap_cm)
        monkeypatch.setattr(tenants_router, "get_internal_user_by_auth_id", _fake_get_internal)
        # silenciar el módulo db.client por si algo importa pool real
        monkeypatch.setattr(db_client, "get_pool", MagicMock())

        client = _make_endpoint_app("super_admin")
        resp = client.post("/tenants", json=self._payload())
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["tenant"]["slug"] == "lunaria-2"
        assert body["tenant"]["plan_tier"] == "founding"
        assert body["invite_sent"] is True

    def test_403_when_not_super_admin(self) -> None:
        client = _make_endpoint_app("tenant_admin")
        resp = client.post("/tenants", json=self._payload())
        assert resp.status_code == 403

    def test_409_when_slug_taken(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from contextlib import asynccontextmanager

        from apps.api.routers import tenants as tenants_router

        async def _raise_slug(*a, **kw):
            raise SlugTakenError("lunaria-2")

        @asynccontextmanager
        async def _fake_bootstrap_cm():
            yield MagicMock()

        async def _fake_get_internal(conn, user_id):
            return _make_internal_user()

        monkeypatch.setattr(tenants_router, "provision_tenant", _raise_slug)
        monkeypatch.setattr(tenants_router, "bootstrap_connection", _fake_bootstrap_cm)
        monkeypatch.setattr(tenants_router, "get_internal_user_by_auth_id", _fake_get_internal)

        client = _make_endpoint_app("super_admin")
        resp = client.post("/tenants", json=self._payload())
        assert resp.status_code == 409

    def test_403_when_super_admin_without_internal_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from contextlib import asynccontextmanager

        from apps.api.routers import tenants as tenants_router

        @asynccontextmanager
        async def _fake_bootstrap_cm():
            yield MagicMock()

        async def _fake_get_internal(conn, user_id):
            return None

        monkeypatch.setattr(tenants_router, "bootstrap_connection", _fake_bootstrap_cm)
        monkeypatch.setattr(tenants_router, "get_internal_user_by_auth_id", _fake_get_internal)

        client = _make_endpoint_app("super_admin")
        resp = client.post("/tenants", json=self._payload())
        assert resp.status_code == 403

    def test_422_invalid_slug(self) -> None:
        client = _make_endpoint_app("super_admin")
        payload = self._payload() | {"slug": "Invalid Slug!"}
        resp = client.post("/tenants", json=payload)
        assert resp.status_code == 422

    def test_422_invalid_email(self) -> None:
        client = _make_endpoint_app("super_admin")
        payload = self._payload() | {"tenant_admin_email": "no-arroba"}
        resp = client.post("/tenants", json=payload)
        assert resp.status_code == 422
