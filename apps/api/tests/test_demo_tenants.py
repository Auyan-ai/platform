"""Tests de las demos (ADR 0015 §5): alta, modo del turno, exclusiones y caducidad."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import asyncpg
import pytest
from apps.api.agents.nodes.load_tenant_context import make_load_tenant_context_node
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.routers.tenants import router as tenants_router
from apps.api.scripts.generate_weekly_reports import list_targets
from apps.api.services import demo_tenants
from apps.api.services.cleanup import expire_demo_tenants
from apps.api.services.demo_tenants import (
    DEMO_ALLOWED_SKILLS,
    DemoSlugExhaustedError,
    company_name_from_domain,
    create_demo_tenant,
    demo_slug,
    demo_state_overrides,
    reject_demo_intake,
)
from apps.api.tests.conftest import (
    TENANT_ID,
    make_fake_bootstrap_connection,
    make_fake_tenant_scope,
    make_tenant,
    make_tenant_configuration,
)
from apps.api.tests.test_tenants import FakeAuthSettings, _make_app, _make_jwt
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,49}$")
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _demo(**overrides: Any) -> Any:
    base = {
        "slug": "demo-thinkingmu-ab12cd",
        "origin": "demo",
        "demo_expires_at": NOW + timedelta(days=30),
        "demo_source_url": "https://www.thinkingmu.com",
    }
    return make_tenant(**{**base, **overrides})


def _slug_collision() -> asyncpg.UniqueViolationError:
    return asyncpg.UniqueViolationError.new(
        {"C": "23505", "M": "duplicate key", "n": "tenants_slug_key"}
    )


def _conn() -> MagicMock:
    conn = MagicMock()
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)
    return conn


class TestSlugAndName:
    @pytest.mark.parametrize(
        ("domain", "shop"),
        [
            ("thinkingmu.com", "thinkingmu"),
            ("www.ecoalf.com", "ecoalf"),
            ("tienda.mi-marca.co.uk", "mi-marca"),
            ("alohas.es", "alohas"),
        ],
    )
    def test_slug_is_demo_shop_and_six_random_chars(self, domain: str, shop: str) -> None:
        slug = demo_slug(domain)

        assert re.fullmatch(rf"demo-{re.escape(shop)}-[a-z0-9]{{6}}", slug)
        assert SLUG_PATTERN.match(slug)

    def test_long_shop_names_still_fit_the_slug_pattern(self) -> None:
        slug = demo_slug(f"{'a' * 60}.com")

        assert SLUG_PATTERN.match(slug)

    def test_suffix_changes_between_calls(self) -> None:
        assert len({demo_slug("thinkingmu.com") for _ in range(20)}) > 1

    @pytest.mark.parametrize(
        ("domain", "name"),
        [
            ("thinkingmu.com", "Thinkingmu"),
            ("www.mi-marca.es", "Mi Marca"),
            ("tienda.ecoalf.co.uk", "Ecoalf"),
        ],
    )
    def test_company_name_is_host_without_tld_title_cased(self, domain: str, name: str) -> None:
        assert company_name_from_domain(domain) == name


class TestCreateDemoTenant:
    @pytest.fixture
    def scaffold(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        mock = AsyncMock(side_effect=lambda conn, **kw: make_tenant(id=uuid4(), **_tenant_kw(kw)))
        monkeypatch.setattr(demo_tenants, "scaffold_tenant", mock)
        return mock

    @pytest.fixture
    def permissions(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        mock = AsyncMock()
        monkeypatch.setattr(demo_tenants, "upsert_tool_permission", mock)
        return mock

    @pytest.mark.asyncio
    async def test_scaffolds_a_demo_with_ttl_and_source_url(
        self, scaffold: AsyncMock, permissions: AsyncMock
    ) -> None:
        settings = SimpleNamespace(demo_ttl_days=30)

        tenant = await create_demo_tenant(
            _conn(), settings=settings, url="https://www.ThinkingMu.com/products/x", now=NOW
        )

        kwargs = scaffold.await_args.kwargs
        assert kwargs["origin"] == "demo"
        assert kwargs["plan_tier"] == "trial"
        assert kwargs["lifecycle_state"] == "initial"
        assert kwargs["demo_expires_at"] == NOW + timedelta(days=30)
        assert kwargs["demo_source_url"] == "https://www.thinkingmu.com"
        assert kwargs["company_name"] == "Thinkingmu"
        assert SLUG_PATTERN.match(kwargs["slug"])
        assert kwargs["slug"].startswith("demo-thinkingmu-")
        assert tenant.origin == "demo"

    @pytest.mark.asyncio
    async def test_ttl_comes_from_settings(
        self, scaffold: AsyncMock, permissions: AsyncMock
    ) -> None:
        await create_demo_tenant(
            _conn(), settings=SimpleNamespace(demo_ttl_days=7), url="alohas.es", now=NOW
        )

        assert scaffold.await_args.kwargs["demo_expires_at"] == NOW + timedelta(days=7)

    @pytest.mark.asyncio
    async def test_only_read_skills_stay_enabled(
        self, scaffold: AsyncMock, permissions: AsyncMock
    ) -> None:
        from apps.api.aops.canonical import CANONICAL_TOOL_PERMISSIONS

        await create_demo_tenant(
            _conn(), settings=SimpleNamespace(demo_ttl_days=30), url="alohas.es", now=NOW
        )

        disabled = {c.kwargs["skill_slug"] for c in permissions.await_args_list}
        canonical = {p["skill_slug"] for p in CANONICAL_TOOL_PERMISSIONS}
        assert disabled == canonical - DEMO_ALLOWED_SKILLS
        assert len(DEMO_ALLOWED_SKILLS) == 4
        assert {"shopify.start_return", "shopify.add_order_note"} <= disabled
        assert all(c.kwargs["is_enabled"] is False for c in permissions.await_args_list)

    @pytest.mark.asyncio
    async def test_retries_with_a_new_suffix_on_slug_collision(
        self, scaffold: AsyncMock, permissions: AsyncMock
    ) -> None:
        results = [_slug_collision(), _slug_collision(), None]

        async def _flaky(conn: Any, **kw: Any) -> Any:
            outcome = results.pop(0)
            if outcome is not None:
                raise outcome
            return make_tenant(id=uuid4(), **_tenant_kw(kw))

        scaffold.side_effect = _flaky

        tenant = await create_demo_tenant(
            _conn(), settings=SimpleNamespace(demo_ttl_days=30), url="alohas.es", now=NOW
        )

        assert scaffold.await_count == 3
        slugs = [c.kwargs["slug"] for c in scaffold.await_args_list]
        assert len(set(slugs)) == 3
        assert tenant.slug == slugs[-1]

    @pytest.mark.asyncio
    async def test_gives_up_after_five_collisions(
        self, scaffold: AsyncMock, permissions: AsyncMock
    ) -> None:
        scaffold.side_effect = _slug_collision()

        with pytest.raises(DemoSlugExhaustedError):
            await create_demo_tenant(
                _conn(), settings=SimpleNamespace(demo_ttl_days=30), url="alohas.es", now=NOW
            )

        assert scaffold.await_count == 5

    @pytest.mark.asyncio
    async def test_other_unique_violations_are_not_retried(
        self, scaffold: AsyncMock, permissions: AsyncMock
    ) -> None:
        scaffold.side_effect = asyncpg.UniqueViolationError.new(
            {"C": "23505", "M": "dup", "n": "tenant_onboarding_pkey"}
        )

        with pytest.raises(asyncpg.UniqueViolationError):
            await create_demo_tenant(
                _conn(), settings=SimpleNamespace(demo_ttl_days=30), url="alohas.es", now=NOW
            )

        assert scaffold.await_count == 1

    @pytest.mark.asyncio
    async def test_invalid_url_is_rejected_before_touching_the_db(
        self, scaffold: AsyncMock, permissions: AsyncMock
    ) -> None:
        with pytest.raises(ValueError, match="invalid_store_domain"):
            await create_demo_tenant(
                _conn(), settings=SimpleNamespace(demo_ttl_days=30), url="no es una url"
            )

        scaffold.assert_not_awaited()


def _tenant_kw(kw: dict[str, Any]) -> dict[str, Any]:
    return {
        "slug": kw["slug"],
        "name": kw["company_name"],
        "origin": kw["origin"],
        "demo_expires_at": kw["demo_expires_at"],
        "demo_source_url": kw["demo_source_url"],
    }


class TestDemoTurnState:
    def test_demo_gets_demo_catalog_for_its_source_domain(self) -> None:
        overrides = demo_state_overrides(_demo())

        assert overrides == {
            "commerce_integration_ctx": None,
            "commerce_mode": "demo_catalog",
            "demo_catalog_domain": "www.thinkingmu.com",
        }

    def test_scripted_simulator_keeps_the_mock_but_still_gets_no_credentials(self) -> None:
        overrides = demo_state_overrides(_demo(), scripted_commerce=True)

        assert overrides == {"commerce_integration_ctx": None}

    def test_client_tenant_is_untouched(self) -> None:
        assert demo_state_overrides(make_tenant()) == {}

    @pytest.mark.asyncio
    async def test_load_tenant_context_gives_a_demo_no_credentials(
        self, fake_deps: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = "apps.api.agents.nodes.load_tenant_context"
        build_ctx = AsyncMock(
            return_value=SimpleNamespace(tenant_id=TENANT_ID, credentials={"token": "x"}, config={})
        )
        monkeypatch.setattr(f"{module}.tenant_scope", make_fake_tenant_scope())
        monkeypatch.setattr(f"{module}.get_tenant_by_id", AsyncMock(return_value=_demo()))
        monkeypatch.setattr(
            f"{module}.get_tenant_configuration",
            AsyncMock(return_value=make_tenant_configuration()),
        )
        monkeypatch.setattr(f"{module}.get_active_system_prompt", AsyncMock(return_value="p"))
        monkeypatch.setattr(f"{module}.list_tool_permissions", AsyncMock(return_value=[]))
        monkeypatch.setattr(f"{module}.get_tenant_playbook", AsyncMock(return_value=None))
        monkeypatch.setattr(f"{module}.get_tenant_facts", AsyncMock(return_value=None))
        monkeypatch.setattr(f"{module}.load_current_returns_policy", AsyncMock(return_value=None))
        monkeypatch.setattr(f"{module}.build_commerce_integration_ctx", build_ctx)

        out = await make_load_tenant_context_node(fake_deps)({"tenant_id": str(TENANT_ID)})

        assert out["commerce_mode"] == "demo_catalog"
        assert out["demo_catalog_domain"] == "www.thinkingmu.com"
        assert out["commerce_integration_ctx"] is None
        build_ctx.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("fixtures", "expected_mode"),
        [({}, "demo_catalog"), ({"shopify": {"get_order": {}}}, None)],
        ids=["probar-agente", "escenario-guionizado"],
    )
    async def test_simulated_demo_turn_uses_catalog_unless_scripted(
        self,
        fake_deps: Any,
        monkeypatch: pytest.MonkeyPatch,
        fixtures: dict[str, Any],
        expected_mode: str | None,
    ) -> None:
        module = "apps.api.agents.nodes.load_tenant_context"
        build_ctx = AsyncMock()
        monkeypatch.setattr(f"{module}.tenant_scope", make_fake_tenant_scope())
        monkeypatch.setattr(f"{module}.get_tenant_by_id", AsyncMock(return_value=_demo()))
        monkeypatch.setattr(
            f"{module}.get_tenant_configuration",
            AsyncMock(return_value=make_tenant_configuration()),
        )
        monkeypatch.setattr(f"{module}.get_active_system_prompt", AsyncMock(return_value="p"))
        monkeypatch.setattr(f"{module}.list_tool_permissions", AsyncMock(return_value=[]))
        monkeypatch.setattr(f"{module}.get_tenant_playbook", AsyncMock(return_value=None))
        monkeypatch.setattr(f"{module}.get_tenant_facts", AsyncMock(return_value=None))
        monkeypatch.setattr(f"{module}.load_current_returns_policy", AsyncMock(return_value=None))
        monkeypatch.setattr(f"{module}.build_commerce_integration_ctx", build_ctx)

        out = await make_load_tenant_context_node(fake_deps)(
            {"tenant_id": str(TENANT_ID), "simulation_mode": True, "simulation_fixtures": fixtures}
        )

        assert out.get("commerce_mode") == expected_mode
        assert out["commerce_integration_ctx"] is None
        build_ctx.assert_not_awaited()


class TestIntakeRejectsDemos:
    def test_demo_is_rejected_with_logged_reason(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING), pytest.raises(HTTPException) as exc:
            reject_demo_intake(_demo(), source="zendesk")

        assert exc.value.status_code == 403
        assert exc.value.detail == "tenant_is_demo"
        assert "intake_rejected_demo_tenant source=zendesk" in caplog.text

    def test_client_and_unknown_tenants_pass_through(self) -> None:
        reject_demo_intake(make_tenant(), source="zendesk")
        reject_demo_intake(None, source="zendesk")


class TestWeeklyReportsSkipDemos:
    @pytest.mark.asyncio
    async def test_target_query_only_selects_client_tenants(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])

        await list_targets(conn, None)

        assert "t.origin = 'client'" in conn.fetch.await_args.args[0]


class TestDemoExpiry:
    @pytest.mark.asyncio
    async def test_expires_through_a_soft_delete_of_demos_only(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[{"id": uuid4(), "slug": "demo-alohas-ab12cd"}])
        monkeypatch.setattr(
            "apps.api.services.cleanup.bootstrap_connection", make_fake_bootstrap_connection(conn)
        )

        with caplog.at_level(logging.INFO):
            count = await expire_demo_tenants(NOW)

        sql, cutoff = conn.fetch.await_args.args
        assert count == 1
        assert cutoff == NOW
        assert "SET deleted_at" in sql
        assert "origin = 'demo'" in sql
        assert "demo_expires_at <= $1" in sql
        assert "DELETE" not in sql
        assert "demo_tenant_expired" in caplog.text

    def test_review_queue_skips_demos(self) -> None:
        import inspect

        from apps.api.db import queries

        assert "t.origin = 'client'" in inspect.getsource(queries.list_admin_review_queue)


class TestCreateDemoEndpoint:
    def test_tenant_admin_gets_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        create = AsyncMock()
        monkeypatch.setattr("apps.api.routers.tenants.create_demo_tenant", create)
        client = TestClient(_make_app(monkeypatch))

        resp = client.post(
            "/tenants/demos",
            json={"url": "thinkingmu.com"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 403
        create.assert_not_awaited()

    def test_super_admin_creates_a_demo_and_starts_ingestion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tenant = _demo()
        create = AsyncMock(return_value=tenant)
        ingestion = AsyncMock(return_value=None)
        monkeypatch.setattr("apps.api.routers.tenants.create_demo_tenant", create)
        monkeypatch.setattr("apps.api.routers.tenants.start_demo_ingestion", ingestion)
        monkeypatch.setattr(
            "apps.api.routers.tenants.bootstrap_connection", make_fake_bootstrap_connection()
        )
        client = TestClient(_super_admin_app(monkeypatch))

        resp = client.post(
            "/tenants/demos",
            json={"url": "https://thinkingmu.com"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["origin"] == "demo"
        assert body["slug"] == "demo-thinkingmu-ab12cd"
        assert body["demo_source_url"] == "https://www.thinkingmu.com"
        ingestion.assert_awaited_once()
        assert ingestion.await_args.args[1] is tenant

    def test_invalid_url_returns_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.tenants.bootstrap_connection", make_fake_bootstrap_connection()
        )
        client = TestClient(_super_admin_app(monkeypatch))

        resp = client.post(
            "/tenants/demos",
            json={"url": "esto no es una tienda"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 422


def _super_admin_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def _lookup(user_id: Any, settings: Any) -> UserRecord:
        return UserRecord(tenant_id=TENANT_ID, role="super_admin", email="kenny@auyan.ai")

    monkeypatch.setattr("apps.api.core.security._lookup_user", _lookup)
    from apps.api.core.config import get_settings

    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(tenants_router)
    return app


@pytest.fixture(autouse=True)
def _clear_user_cache() -> Any:
    reset_user_cache()
    yield
    reset_user_cache()


class TestStartDemoIngestion:
    async def test_queues_the_ingestion_of_the_demo_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tenant = _demo()
        ingestion_id = uuid4()
        enqueue = AsyncMock(return_value=ingestion_id)
        monkeypatch.setattr(demo_tenants, "enqueue_site_ingestion", enqueue)
        requested_by = uuid4()
        conn = _conn()

        result = await demo_tenants.start_demo_ingestion(conn, tenant, requested_by=requested_by)

        assert result == ingestion_id
        enqueue.assert_awaited_once_with(
            conn,
            tenant_id=tenant.id,
            root_url="https://www.thinkingmu.com",
            requested_by=requested_by,
        )
