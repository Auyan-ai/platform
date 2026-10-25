"""Tests de convertir una demo en cliente (ADR 0015 §6) y de la confirmación de la KB."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from apps.api.aops.canonical import CANONICAL_TOOL_PERMISSIONS
from apps.api.core.errors import ConflictError, NotFoundError
from apps.api.db import kb_confirmation
from apps.api.db.models import OnboardingChecklist, Tenant
from apps.api.db.queries import compute_onboarding_checklist
from apps.api.services import tenant_promotion
from apps.api.services.demo_tenants import DEMO_ALLOWED_SKILLS, demo_state_overrides
from apps.api.services.tenant_promotion import promote_demo_tenant
from apps.api.services.tenant_provisioning import SlugTakenError, SupabaseAdminError
from apps.api.services.tenants import set_lifecycle_state
from apps.api.tests.conftest import (
    TENANT_ID,
    make_fake_bootstrap_connection,
    make_fake_tenant_scope,
    make_tenant,
)
from apps.api.tests.test_demo_tenants import _super_admin_app
from apps.api.tests.test_tenants import _make_app, _make_jwt
from fastapi.testclient import TestClient

ADMIN_ID = uuid4()
INTERNAL_USER_ID = uuid4()
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
SOURCE_URL = "https://www.alohas.es"


def _demo_row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": TENANT_ID,
        "slug": "demo-alohas-ab12cd",
        "name": "Alohas",
        "status": "active",
        "agent_lifecycle_state": "initial",
        "plan_tier": "trial",
        "origin": "demo",
        "demo_expires_at": NOW + timedelta(days=30),
        "demo_source_url": SOURCE_URL,
    }
    return {**base, **overrides}


class FakeDb:
    """Estado de un tenant y de los slugs ocupados, con la semántica del UPDATE de promote."""

    def __init__(self, row: dict[str, Any], taken_slugs: set[str] | None = None) -> None:
        self.row = row
        self.taken_slugs = taken_slugs or set()
        self.admins: set[str] = set()
        self.transactions = 0
        self.conn = MagicMock()
        self.conn.fetchval = AsyncMock(side_effect=self._fetchval)
        self.conn.fetchrow = AsyncMock(side_effect=self._fetchrow)
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(side_effect=self._enter)
        tx.__aexit__ = AsyncMock(return_value=None)
        self.conn.transaction = MagicMock(return_value=tx)

    async def _enter(self) -> None:
        self.transactions += 1

    async def _fetchval(self, sql: str, *args: Any) -> Any:
        if "FROM tenants WHERE slug" in sql:
            return 1 if args[0] in self.taken_slugs else None
        if "FROM users" in sql:
            return ADMIN_ID if str(args[1]).lower() in self.admins else None
        raise AssertionError(sql)

    async def _fetchrow(self, sql: str, *args: Any) -> Any:
        assert "UPDATE tenants" in sql
        if self.row["origin"] != "demo":
            return None
        _, slug, plan_tier = args
        self.row.update(
            origin="client",
            demo_expires_at=None,
            slug=slug,
            plan_tier=plan_tier,
            agent_lifecycle_state=(
                "discovery"
                if self.row["agent_lifecycle_state"] == "initial"
                else self.row["agent_lifecycle_state"]
            ),
        )
        return dict(self.row)


@pytest.fixture
def permissions(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    upsert = AsyncMock()
    monkeypatch.setattr(tenant_promotion, "upsert_tool_permission", upsert)
    return upsert


def _attach(monkeypatch: pytest.MonkeyPatch, db: FakeDb) -> AsyncMock:
    async def _impl(conn: Any, http: Any, settings: Any, *, email: str, **_: Any) -> UUID:
        db.admins.add(email.lower())
        return ADMIN_ID

    attach = AsyncMock(side_effect=_impl)
    monkeypatch.setattr(tenant_promotion, "attach_tenant_admin", attach)
    return attach


def _stub_get_tenant(monkeypatch: pytest.MonkeyPatch, db: FakeDb) -> None:
    async def _get(conn: Any, tenant_id: UUID) -> Tenant:
        return Tenant(**db.row)

    monkeypatch.setattr(tenant_promotion, "get_tenant_by_id", _get)


async def _promote(db: FakeDb, **overrides: Any) -> Any:
    args: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "admin_email": "kenny+alohas@auyan.es",
        "admin_name": "Kenny",
        "plan_tier": "standard",
        "slug": "alohas-prueba",
        "creator_internal_user_id": INTERNAL_USER_ID,
    }
    async with httpx.AsyncClient() as http:
        return await promote_demo_tenant(db.conn, http, MagicMock(), **{**args, **overrides})


class TestPromoteDemoTenant:
    async def test_demo_becomes_a_client_with_slug_plan_and_discovery(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row())
        _stub_get_tenant(monkeypatch, db)
        attach = _attach(monkeypatch, db)

        result = await _promote(db)

        tenant = result.tenant
        assert (tenant.origin, tenant.demo_expires_at, tenant.slug) == (
            "client",
            None,
            "alohas-prueba",
        )
        assert (tenant.agent_lifecycle_state, tenant.plan_tier) == ("discovery", "standard")
        assert result.tenant_admin_user_id == ADMIN_ID
        assert attach.await_args.kwargs["email"] == "kenny+alohas@auyan.es"
        assert db.transactions == 1

    async def test_keeps_demo_source_url_as_provenance(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row())
        _stub_get_tenant(monkeypatch, db)
        _attach(monkeypatch, db)

        result = await _promote(db)

        assert result.tenant.demo_source_url == SOURCE_URL

    async def test_a_lifecycle_beyond_initial_is_not_rewound(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row(agent_lifecycle_state="building"))
        _stub_get_tenant(monkeypatch, db)
        _attach(monkeypatch, db)

        result = await _promote(db)

        assert result.tenant.agent_lifecycle_state == "building"

    async def test_restores_the_canonical_permissions_the_demo_disabled(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row())
        _stub_get_tenant(monkeypatch, db)
        _attach(monkeypatch, db)

        await _promote(db)

        written = {c.kwargs["skill_slug"]: c.kwargs for c in permissions.await_args_list}
        expected = {
            p["skill_slug"]: (p["is_enabled"], p["human_approval_required"])
            for p in CANONICAL_TOOL_PERMISSIONS
            if p["skill_slug"] not in DEMO_ALLOWED_SKILLS
        }
        assert {k: (v["is_enabled"], v["human_approval_required"]) for k, v in written.items()} == (
            expected
        )
        for slug in ("shopify.start_return", "shopify.cancel_order", "shopify.refund_partial"):
            assert written[slug]["human_approval_required"] is True
        assert written["shopify.refund_partial"]["is_enabled"] is False
        assert written["shopify.add_order_note"]["is_enabled"] is True

    async def test_non_demo_tenant_is_a_409(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row(origin="client", demo_expires_at=None, demo_source_url=None))
        _stub_get_tenant(monkeypatch, db)
        attach = _attach(monkeypatch, db)

        with pytest.raises(ConflictError) as err:
            await _promote(db)

        assert (err.value.status_code, err.value.code) == (409, "tenant_not_demo")
        attach.assert_not_awaited()
        permissions.assert_not_awaited()

    async def test_unknown_tenant_is_a_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = FakeDb(_demo_row())
        monkeypatch.setattr(tenant_promotion, "get_tenant_by_id", AsyncMock(return_value=None))

        with pytest.raises(NotFoundError):
            await _promote(db)

    async def test_slug_taken_by_another_tenant_fails_before_inviting(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row(), taken_slugs={"alohas-prueba"})
        _stub_get_tenant(monkeypatch, db)
        attach = _attach(monkeypatch, db)

        with pytest.raises(SlugTakenError):
            await _promote(db)

        attach.assert_not_awaited()
        assert db.row["origin"] == "demo"

    async def test_slug_race_on_the_unique_index_is_slug_taken(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row())
        _stub_get_tenant(monkeypatch, db)
        _attach(monkeypatch, db)
        db.conn.fetchrow = AsyncMock(
            side_effect=asyncpg.UniqueViolationError.new(
                {"C": "23505", "M": "duplicate key", "n": "tenants_slug_key"}
            )
        )

        with pytest.raises(SlugTakenError):
            await _promote(db)

    async def test_failed_invite_leaves_the_tenant_untouched(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row())
        before = dict(db.row)
        _stub_get_tenant(monkeypatch, db)
        monkeypatch.setattr(
            tenant_promotion,
            "attach_tenant_admin",
            AsyncMock(side_effect=SupabaseAdminError("smtp caído")),
        )

        with pytest.raises(SupabaseAdminError):
            await _promote(db)

        assert db.row == before
        assert db.transactions == 0
        db.conn.fetchrow.assert_not_awaited()
        permissions.assert_not_awaited()

    async def test_retry_after_a_failed_conversion_converges(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row())
        _stub_get_tenant(monkeypatch, db)
        _attach(monkeypatch, db)
        real_fetchrow = db.conn.fetchrow
        db.conn.fetchrow = AsyncMock(side_effect=asyncpg.PostgresConnectionError("corte"))

        with pytest.raises(asyncpg.PostgresConnectionError):
            await _promote(db)
        assert db.row["origin"] == "demo"

        db.conn.fetchrow = real_fetchrow
        result = await _promote(db)

        assert result.tenant.origin == "client"
        assert result.tenant.slug == "alohas-prueba"

    async def test_retry_after_a_completed_conversion_returns_the_same_tenant(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row())
        _stub_get_tenant(monkeypatch, db)
        attach = _attach(monkeypatch, db)
        first = await _promote(db)
        permissions.reset_mock()

        again = await _promote(db)

        assert again.tenant == first.tenant
        assert again.tenant_admin_user_id == ADMIN_ID
        assert attach.await_count == 1
        permissions.assert_not_awaited()

    async def test_completed_conversion_with_another_email_is_a_409(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row())
        _stub_get_tenant(monkeypatch, db)
        _attach(monkeypatch, db)
        await _promote(db)

        with pytest.raises(ConflictError):
            await _promote(db, admin_email="otra@persona.es")


class TestPromotedTenantCommerce:
    async def test_promoted_tenant_turn_state_has_no_demo_catalog(
        self, monkeypatch: pytest.MonkeyPatch, permissions: AsyncMock
    ) -> None:
        db = FakeDb(_demo_row())
        _stub_get_tenant(monkeypatch, db)
        _attach(monkeypatch, db)
        before = Tenant(**db.row)
        assert demo_state_overrides(before)["commerce_mode"] == "demo_catalog"

        result = await _promote(db)

        assert result.tenant.demo_source_url == SOURCE_URL
        assert demo_state_overrides(result.tenant) == {}
        assert demo_state_overrides(result.tenant, scripted_commerce=True) == {}


class TestPromoteEndpoint:
    def _client(self, monkeypatch: pytest.MonkeyPatch, promote: AsyncMock) -> TestClient:
        monkeypatch.setattr("apps.api.routers.tenants.promote_demo_tenant", promote)
        monkeypatch.setattr(
            "apps.api.routers.tenants.bootstrap_connection", make_fake_bootstrap_connection()
        )
        monkeypatch.setattr(
            "apps.api.routers.tenants.get_internal_user_by_auth_id",
            AsyncMock(return_value=MagicMock(id=INTERNAL_USER_ID)),
        )
        return TestClient(_super_admin_app(monkeypatch))

    BODY = {
        "admin_email": "kenny+alohas@auyan.es",
        "admin_name": "Kenny",
        "plan_tier": "standard",
        "slug": "alohas-prueba",
    }

    def test_tenant_admin_gets_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        promote = AsyncMock()
        monkeypatch.setattr("apps.api.routers.tenants.promote_demo_tenant", promote)
        client = TestClient(_make_app(monkeypatch))

        resp = client.post(
            f"/tenants/{TENANT_ID}/promote",
            json=self.BODY,
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 403
        promote.assert_not_awaited()

    def test_super_admin_promotes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        promoted = make_tenant(slug="alohas-prueba", plan_tier="standard")
        promote = AsyncMock(
            return_value=tenant_promotion.PromotionResult(promoted, ADMIN_ID)
        )
        client = self._client(monkeypatch, promote)

        resp = client.post(
            f"/tenants/{TENANT_ID}/promote",
            json=self.BODY,
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant"]["origin"] == "client"
        assert body["tenant"]["slug"] == "alohas-prueba"
        assert body["tenant_admin_user_id"] == str(ADMIN_ID)
        assert body["invite_sent"] is True
        assert promote.await_args.kwargs["creator_internal_user_id"] == INTERNAL_USER_ID

    @pytest.mark.parametrize(
        ("error", "status_code"),
        [
            (SlugTakenError("x"), 409),
            (ConflictError("no demo", code="tenant_not_demo"), 409),
            (SupabaseAdminError("smtp"), 502),
        ],
    )
    def test_domain_errors_map_to_http(
        self, monkeypatch: pytest.MonkeyPatch, error: Exception, status_code: int
    ) -> None:
        client = self._client(monkeypatch, AsyncMock(side_effect=error))

        resp = client.post(
            f"/tenants/{TENANT_ID}/promote",
            json=self.BODY,
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == status_code

    def test_invalid_slug_is_a_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._client(monkeypatch, AsyncMock())

        resp = client.post(
            f"/tenants/{TENANT_ID}/promote",
            json={**self.BODY, "slug": "Demo Alohas"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 422


class TestChecklistPendingConfirmation:
    async def test_counts_unconfirmed_documents_and_detects_the_returns_policy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = MagicMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "onboarding_submitted": False,
                "has_commerce": False,
                "has_helpdesk": False,
                "has_knowledge": True,
            }
        )
        monkeypatch.setattr(
            "apps.api.db.queries.count_unconfirmed_kb_documents", AsyncMock(return_value=3)
        )
        monkeypatch.setattr(
            "apps.api.db.queries.get_current_returns_policy", AsyncMock(return_value=None)
        )

        checklist = await compute_onboarding_checklist(conn, TENANT_ID)

        assert checklist.unconfirmed_kb_documents == 3
        assert checklist.has_returns_policy is False
        assert checklist.pending_confirmation is True

    def test_unconfirmed_documents_do_not_block_discovery_to_building(self) -> None:
        checklist = OnboardingChecklist(
            onboarding_submitted=True,
            has_commerce_integration=True,
            has_helpdesk_integration=True,
            has_knowledge=True,
            unconfirmed_kb_documents=4,
        )

        assert checklist.complete is True
        assert checklist.pending_confirmation is True


class TestLifecycleGate:
    @pytest.fixture
    def update(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        update = AsyncMock(side_effect=lambda conn, tid, state: make_tenant(agent_lifecycle_state=state))
        monkeypatch.setattr("apps.api.services.tenants.update_tenant_lifecycle_state", update)
        return update

    @pytest.mark.parametrize("state", ["shadow", "ramping", "active"])
    async def test_blocked_while_documents_are_unconfirmed(
        self, monkeypatch: pytest.MonkeyPatch, update: AsyncMock, state: str
    ) -> None:
        monkeypatch.setattr(
            "apps.api.services.tenants.count_unconfirmed_kb_documents", AsyncMock(return_value=2)
        )

        with pytest.raises(ConflictError) as err:
            await set_lifecycle_state(MagicMock(), TENANT_ID, state)

        assert (err.value.status_code, err.value.code) == (409, "unconfirmed_knowledge")
        update.assert_not_awaited()

    async def test_allowed_once_everything_is_confirmed(
        self, monkeypatch: pytest.MonkeyPatch, update: AsyncMock
    ) -> None:
        monkeypatch.setattr(
            "apps.api.services.tenants.count_unconfirmed_kb_documents", AsyncMock(return_value=0)
        )

        tenant = await set_lifecycle_state(MagicMock(), TENANT_ID, "shadow")

        assert tenant.agent_lifecycle_state == "shadow"

    @pytest.mark.parametrize("state", ["discovery", "building", "paused", "churned"])
    async def test_other_states_never_check_the_knowledge(
        self, monkeypatch: pytest.MonkeyPatch, update: AsyncMock, state: str
    ) -> None:
        count = AsyncMock(return_value=9)
        monkeypatch.setattr("apps.api.services.tenants.count_unconfirmed_kb_documents", count)

        await set_lifecycle_state(MagicMock(), TENANT_ID, state)

        count.assert_not_awaited()

    def test_lifecycle_endpoint_answers_409_unconfirmed_knowledge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("apps.api.routers.tenants.tenant_scope", make_fake_tenant_scope())
        monkeypatch.setattr(
            "apps.api.services.tenants.count_unconfirmed_kb_documents", AsyncMock(return_value=5)
        )
        client = TestClient(_super_admin_app(monkeypatch))

        resp = client.put(
            "/tenants/me/lifecycle",
            json={"agent_lifecycle_state": "shadow"},
            headers={"Authorization": f"Bearer {_make_jwt()}", "X-Tenant-Id": str(TENANT_ID)},
        )

        assert resp.status_code == 409
        assert resp.json()["error"] == "unconfirmed_knowledge"


class TestConfirmEndpoint:
    def _client(self, monkeypatch: pytest.MonkeyPatch, confirm: AsyncMock) -> TestClient:
        monkeypatch.setattr("apps.api.routers.tenants.confirm_kb_documents", confirm)
        monkeypatch.setattr(
            "apps.api.routers.tenants.list_unconfirmed_kb_documents", AsyncMock(return_value=[])
        )
        return TestClient(_make_app(monkeypatch))

    def test_confirm_all_runs_in_the_callers_tenant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        confirm = AsyncMock(return_value=4)
        client = self._client(monkeypatch, confirm)

        resp = client.post(
            "/tenants/me/kb-documents/confirm",
            json={"all": True},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"confirmed": 4, "remaining_unconfirmed": 0}
        args = confirm.await_args.args
        assert args[1] == TENANT_ID
        assert args[2] is None

    def test_confirm_specific_documents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        confirm = AsyncMock(return_value=1)
        doc = uuid4()
        client = self._client(monkeypatch, confirm)

        resp = client.post(
            "/tenants/me/kb-documents/confirm",
            json={"document_ids": [str(doc)]},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        assert confirm.await_args.args[2] == [doc]

    def test_another_tenant_header_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        confirm = AsyncMock()
        client = self._client(monkeypatch, confirm)

        resp = client.post(
            "/tenants/me/kb-documents/confirm",
            json={"all": True},
            headers={"Authorization": f"Bearer {_make_jwt()}", "X-Tenant-Id": str(uuid4())},
        )

        assert resp.status_code == 403
        confirm.assert_not_awaited()

    @pytest.mark.parametrize("body", [{}, {"all": False}, {"all": True, "document_ids": [str(uuid4())]}])
    def test_needs_exactly_one_selector(
        self, monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]
    ) -> None:
        confirm = AsyncMock()
        client = self._client(monkeypatch, confirm)

        resp = client.post(
            "/tenants/me/kb-documents/confirm",
            json=body,
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 422
        confirm.assert_not_awaited()


class TestConfirmQueries:
    async def test_confirm_filters_by_tenant_and_reports_how_many(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[{"id": uuid4()}, {"id": uuid4()}])
        user = uuid4()
        doc = uuid4()

        confirmed = await kb_confirmation.confirm_kb_documents(conn, TENANT_ID, [doc], user)

        sql, tenant_arg, user_arg, ids_arg = conn.fetch.await_args.args
        assert confirmed == 2
        assert "d.tenant_id = $1" in sql
        assert "'unconfirmed'" in sql
        assert (tenant_arg, user_arg, ids_arg) == (TENANT_ID, str(user), [doc])

    async def test_missing_key_counts_as_confirmed(self) -> None:
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=0)

        await kb_confirmation.count_unconfirmed_kb_documents(conn, TENANT_ID)

        assert "COALESCE(d.metadata->>'confirmation', 'confirmed')" in conn.fetchval.await_args.args[0]
