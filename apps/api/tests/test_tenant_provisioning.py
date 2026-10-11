"""Tests del provisioning service y del endpoint POST /tenants."""

from __future__ import annotations

import json
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
    _find_user_by_email,
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
            AsyncMock(
                return_value={"created": 8, "updated": 0, "skipped": 0, "tool_permissions": 11}
            ),
        )

        async def _handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/auth/v1/invite"
            assert request.headers["authorization"] == f"Bearer {SERVICE_ROLE}"
            return httpx.Response(
                200, json={"id": str(AUTH_USER_ID), "email": "admin@lunaria.test"}
            )

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
            call
            for call in conn.execute.await_args_list
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
    async def test_email_exists_sends_magic_link_email_via_otp(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # #299: generate_link solo devuelve el enlace y no manda correo. Para un usuario
        # existente hay que llamar a POST /otp con create_user=false, que sí lo envía.
        conn = _make_conn(slug_taken=False)
        monkeypatch.setattr(
            "apps.api.services.tenant_provisioning.provision_canonical_aops",
            AsyncMock(
                return_value={"created": 8, "updated": 0, "skipped": 0, "tool_permissions": 11}
            ),
        )
        calls: list[str] = []
        otp_bodies: list[dict[str, Any]] = []

        async def _handler(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url.path}")
            if request.url.path == "/auth/v1/invite":
                return httpx.Response(
                    422, json={"code": "email_exists", "msg": "Email address already registered"}
                )
            if request.url.path == "/auth/v1/admin/users":
                return httpx.Response(
                    200, json={"users": [{"id": str(AUTH_USER_ID), "email": "admin@lunaria.test"}]}
                )
            if request.url.path == "/auth/v1/otp":
                otp_bodies.append(json.loads(request.content))
                return httpx.Response(200, json={})
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
            "POST /auth/v1/otp",
        ]
        # create_user=false: nunca crea un usuario nuevo por esta vía.
        assert otp_bodies == [{"email": "admin@lunaria.test", "create_user": False}]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status_code", "body"),
        [
            (429, {"code": "over_email_send_rate_limit", "msg": "email rate limit exceeded"}),
            (422, {"code": "otp_disabled", "msg": "Signups not allowed for otp"}),
            (500, {"msg": "upstream down"}),
        ],
    )
    async def test_email_exists_but_magic_link_send_fails_raises_before_db(
        self, status_code: int, body: dict[str, str]
    ) -> None:
        conn = _make_conn(slug_taken=False)

        async def _handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/auth/v1/invite":
                return httpx.Response(
                    422, json={"code": "email_exists", "msg": "already registered"}
                )
            if request.url.path == "/auth/v1/admin/users":
                return httpx.Response(
                    200, json={"users": [{"id": str(AUTH_USER_ID), "email": "admin@lunaria.test"}]}
                )
            if request.url.path == "/auth/v1/otp":
                return httpx.Response(status_code, json=body)
            return httpx.Response(404)

        http = _make_http(httpx.MockTransport(_handler))
        with pytest.raises(SupabaseAdminError) as excinfo:
            await provision_tenant(
                conn, settings=_make_settings(), http=http, request=_make_request()
            )
        message = str(excinfo.value)
        assert "admin@lunaria.test" in message
        assert str(status_code) in message
        assert body["msg"] in message
        # Sin correo no hay tenant: nada se escribió y el super_admin puede reintentar.
        conn.fetchrow.assert_not_awaited()
        conn.execute.assert_not_awaited()

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
# Service: _find_user_by_email (#304)
# ---------------------------------------------------------------------------


def _paged_admin_users(
    users: list[dict[str, str]], requested_pages: list[int]
) -> httpx.MockTransport:
    """Simula la paginación offset de GoTrue en GET /admin/users (page/per_page)."""

    async def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/v1/admin/users"
        page = int(request.url.params["page"])
        per_page = int(request.url.params["per_page"])
        requested_pages.append(page)
        start = (page - 1) * per_page
        return httpx.Response(200, json={"aud": "", "users": users[start : start + per_page]})

    return httpx.MockTransport(_handler)


def _other_users(count: int) -> list[dict[str, str]]:
    return [{"id": str(uuid4()), "email": f"user{i}@otro.test"} for i in range(count)]


async def _find(http: httpx.AsyncClient, email: str = "admin@lunaria.test") -> UUID | None:
    return await _find_user_by_email(
        http=http, supabase_url=SUPABASE_URL, service_role=SERVICE_ROLE, email=email
    )


class TestFindUserByEmail:
    @pytest.mark.asyncio
    async def test_user_on_second_page_is_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("apps.api.services.tenant_provisioning._ADMIN_USERS_PER_PAGE", 2)
        users = [*_other_users(2), {"id": str(AUTH_USER_ID), "email": "admin@lunaria.test"}]
        pages: list[int] = []

        found = await _find(_make_http(_paged_admin_users(users, pages)))

        assert found == AUTH_USER_ID
        assert pages == [1, 2]

    @pytest.mark.asyncio
    async def test_missing_user_returns_none_after_last_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("apps.api.services.tenant_provisioning._ADMIN_USERS_PER_PAGE", 2)
        pages: list[int] = []

        found = await _find(_make_http(_paged_admin_users(_other_users(4), pages)))

        assert found is None
        # Páginas 1 y 2 llenas; la 3 llega vacía y cierra la búsqueda.
        assert pages == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_email_comparison_is_case_insensitive(self) -> None:
        users = [{"id": str(AUTH_USER_ID), "email": "Admin@Lunaria.test"}]

        found = await _find(_make_http(_paged_admin_users(users, [])), " ADMIN@lunaria.TEST ")

        assert found == AUTH_USER_ID

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status_code", "body"),
        [
            (401, '{"msg": "invalid JWT"}'),
            (403, '{"msg": "User not allowed"}'),
            (500, "upstream down"),
        ],
    )
    async def test_non_200_raises_with_status_and_message(
        self, status_code: int, body: str
    ) -> None:
        async def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, text=body)

        with pytest.raises(SupabaseAdminError) as excinfo:
            await _find(_make_http(httpx.MockTransport(_handler)))
        message = str(excinfo.value)
        assert str(status_code) in message
        assert body in message

    @pytest.mark.asyncio
    async def test_unexpected_body_raises(self) -> None:
        async def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": []})

        with pytest.raises(SupabaseAdminError):
            await _find(_make_http(httpx.MockTransport(_handler)))

    @pytest.mark.asyncio
    async def test_page_cap_exceeded_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("apps.api.services.tenant_provisioning._ADMIN_USERS_PER_PAGE", 2)
        monkeypatch.setattr("apps.api.services.tenant_provisioning._ADMIN_USERS_MAX_PAGES", 3)
        pages: list[int] = []

        with pytest.raises(SupabaseAdminError) as excinfo:
            await _find(_make_http(_paged_admin_users(_other_users(10), pages)))
        assert "3 páginas" in str(excinfo.value)
        assert pages == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_provision_reports_admin_users_failure_not_user_missing(self) -> None:
        # Antes un 401 en /admin/users se reportaba como "no se encontró usuario".
        conn = _make_conn(slug_taken=False)

        async def _handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/auth/v1/invite":
                return httpx.Response(422, json={"msg": "already registered"})
            if request.url.path == "/auth/v1/admin/users":
                return httpx.Response(401, json={"msg": "invalid JWT"})
            return httpx.Response(404)

        http = _make_http(httpx.MockTransport(_handler))
        with pytest.raises(SupabaseAdminError) as excinfo:
            await provision_tenant(
                conn, settings=_make_settings(), http=http, request=_make_request()
            )
        message = str(excinfo.value)
        assert "401" in message
        assert "invalid JWT" in message
        assert "no se encontró" not in message
        conn.execute.assert_not_awaited()


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

    def test_502_shows_magic_link_send_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from contextlib import asynccontextmanager

        from apps.api.routers import tenants as tenants_router

        async def _raise_send(*a, **kw):
            raise SupabaseAdminError("No se pudo enviar el magic link a admin@lunaria.test")

        @asynccontextmanager
        async def _fake_bootstrap_cm():
            yield MagicMock()

        async def _fake_get_internal(conn, user_id):
            return _make_internal_user()

        monkeypatch.setattr(tenants_router, "provision_tenant", _raise_send)
        monkeypatch.setattr(tenants_router, "bootstrap_connection", _fake_bootstrap_cm)
        monkeypatch.setattr(tenants_router, "get_internal_user_by_auth_id", _fake_get_internal)

        client = _make_endpoint_app("super_admin")
        resp = client.post("/tenants", json=self._payload())
        assert resp.status_code == 502
        assert "No se pudo enviar el magic link" in resp.text

    def test_403_when_super_admin_without_internal_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
