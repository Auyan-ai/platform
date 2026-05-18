"""Tests para las queries de tenant_tool_permissions y pending_approvals (Sprint 10)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from apps.api.db.models import PendingApproval, TenantToolPermission
from apps.api.db.queries import (
    create_pending_approval,
    get_pending_approval,
    get_tool_permissions,
    list_pending_approvals,
    list_tool_permissions,
    resolve_pending_approval,
    upsert_tool_permission,
)
from apps.api.tests.conftest import TENANT_ID

CONVERSATION_ID = UUID("22222222-2222-2222-2222-222222222222")
APPROVAL_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
PERM_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
NOW = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)


def _mk_row(base: dict) -> MagicMock:
    row = MagicMock()
    row.__iter__ = lambda s: iter(base.items())
    row.keys = lambda: base.keys()
    row.__getitem__ = lambda s, k: base[k]
    return row


def _perm_row(**overrides: object) -> MagicMock:
    base: dict = {
        "id": PERM_ID,
        "tenant_id": TENANT_ID,
        "skill_slug": "shopify.cancel_order",
        "is_enabled": False,
        "threshold_override": None,
        "human_approval_required": True,
        "enabled_at": None,
        "enabled_by": None,
        "created_at": NOW,
    }
    base.update(overrides)
    return _mk_row(base)


def _approval_row(**overrides: object) -> MagicMock:
    base: dict = {
        "id": APPROVAL_ID,
        "tenant_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "skill_slug": "shopify.cancel_order",
        "skill_tier": "L3",
        "inputs_raw": {"order_id": 1001},
        "inputs_redacted": {"order_id": 1001},
        "aop_slug": "cancelaciones",
        "aop_version": 1,
        "langfuse_trace_id": "trace-abc",
        "status": "pending",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_comment": None,
        "created_at": NOW,
    }
    base.update(overrides)
    return _mk_row(base)


# ============================================================
# TenantToolPermission — queries
# ============================================================


class TestGetToolPermissions:
    async def test_returns_dict_keyed_by_slug(self) -> None:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[
            _perm_row(skill_slug="shopify.cancel_order", is_enabled=False),
            _perm_row(skill_slug="shopify.get_order_status", is_enabled=True,
                      human_approval_required=False, id=uuid4()),
        ])
        result = await get_tool_permissions(conn, TENANT_ID, ["shopify.cancel_order", "shopify.get_order_status"])
        assert isinstance(result, dict)
        assert "shopify.cancel_order" in result
        assert isinstance(result["shopify.cancel_order"], TenantToolPermission)
        assert result["shopify.cancel_order"].is_enabled is False

    async def test_empty_slugs_returns_empty_dict(self) -> None:
        conn = AsyncMock()
        result = await get_tool_permissions(conn, TENANT_ID, [])
        assert result == {}
        conn.fetch.assert_not_called()

    async def test_missing_slug_not_in_result(self) -> None:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        result = await get_tool_permissions(conn, TENANT_ID, ["shopify.nonexistent"])
        assert "shopify.nonexistent" not in result


class TestUpsertToolPermission:
    async def test_returns_permission_model(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_perm_row(is_enabled=True, human_approval_required=False))
        result = await upsert_tool_permission(
            conn,
            tenant_id=TENANT_ID,
            skill_slug="shopify.cancel_order",
            is_enabled=True,
            human_approval_required=False,
        )
        assert isinstance(result, TenantToolPermission)
        assert result.is_enabled is True

    async def test_passes_correct_params(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_perm_row(is_enabled=True))
        await upsert_tool_permission(
            conn,
            tenant_id=TENANT_ID,
            skill_slug="shopify.cancel_order",
            is_enabled=True,
            human_approval_required=True,
            threshold_override=0.90,
        )
        call_args = conn.fetchrow.call_args
        sql = call_args[0][0]
        assert "INSERT INTO tenant_tool_permissions" in sql
        assert "ON CONFLICT" in sql


class TestListToolPermissions:
    async def test_returns_list_of_permissions(self) -> None:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[
            _perm_row(skill_slug="shopify.cancel_order"),
            _perm_row(skill_slug="shopify.refund_partial", id=uuid4()),
        ])
        result = await list_tool_permissions(conn, TENANT_ID)
        assert len(result) == 2
        assert all(isinstance(p, TenantToolPermission) for p in result)

    async def test_empty_returns_empty_list(self) -> None:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        result = await list_tool_permissions(conn, TENANT_ID)
        assert result == []


# ============================================================
# PendingApproval — queries
# ============================================================


class TestCreatePendingApproval:
    async def test_returns_pending_approval_model(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_approval_row())
        result = await create_pending_approval(
            conn,
            approval_id=APPROVAL_ID,
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            skill_slug="shopify.cancel_order",
            skill_tier="L3",
            inputs_raw={"order_id": 1001},
            inputs_redacted={"order_id": 1001},
            aop_slug="cancelaciones",
            aop_version=1,
            langfuse_trace_id="trace-abc",
        )
        assert isinstance(result, PendingApproval)
        assert result.status == "pending"
        assert result.skill_slug == "shopify.cancel_order"

    async def test_uses_provided_id(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_approval_row())
        await create_pending_approval(
            conn,
            approval_id=APPROVAL_ID,
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            skill_slug="shopify.cancel_order",
            skill_tier="L3",
            inputs_raw={},
            inputs_redacted={},
            aop_slug="test",
            aop_version=1,
            langfuse_trace_id=None,
        )
        call_args = conn.fetchrow.call_args[0]
        # El approval_id ($1) debe ser el que pasamos
        assert APPROVAL_ID in call_args


class TestGetPendingApproval:
    async def test_returns_model_when_found(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_approval_row())
        result = await get_pending_approval(conn, TENANT_ID, APPROVAL_ID)
        assert isinstance(result, PendingApproval)
        assert result.id == APPROVAL_ID

    async def test_returns_none_when_not_found(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        result = await get_pending_approval(conn, TENANT_ID, APPROVAL_ID)
        assert result is None


class TestListPendingApprovals:
    async def test_returns_list(self) -> None:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[_approval_row(), _approval_row(id=uuid4())])
        result = await list_pending_approvals(conn, TENANT_ID)
        assert len(result) == 2
        assert all(isinstance(a, PendingApproval) for a in result)

    async def test_filters_by_status(self) -> None:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        await list_pending_approvals(conn, TENANT_ID, status="approved")
        sql = conn.fetch.call_args[0][0]
        assert "status = $2" in sql

    async def test_no_filter_omits_status_clause(self) -> None:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        await list_pending_approvals(conn, TENANT_ID)
        sql = conn.fetch.call_args[0][0]
        assert "status = $2" not in sql


class TestResolvePendingApproval:
    async def test_approve_returns_updated_model(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_approval_row(status="approved", reviewed_by=USER_ID))
        result = await resolve_pending_approval(
            conn,
            tenant_id=TENANT_ID,
            approval_id=APPROVAL_ID,
            new_status="approved",
            reviewed_by=USER_ID,
        )
        assert isinstance(result, PendingApproval)
        assert result.status == "approved"

    async def test_reject_returns_updated_model(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_approval_row(status="rejected", reviewed_by=USER_ID))
        result = await resolve_pending_approval(
            conn,
            tenant_id=TENANT_ID,
            approval_id=APPROVAL_ID,
            new_status="rejected",
            reviewed_by=USER_ID,
            review_comment="Pedido ya enviado",
        )
        assert result is not None
        assert result.status == "rejected"

    async def test_returns_none_if_not_pending(self) -> None:
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        result = await resolve_pending_approval(
            conn,
            tenant_id=TENANT_ID,
            approval_id=APPROVAL_ID,
            new_status="approved",
            reviewed_by=USER_ID,
        )
        assert result is None
