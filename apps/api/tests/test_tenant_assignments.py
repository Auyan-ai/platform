"""Tests para tenant_assignments: asignación, desasignación y filtrado por rol."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from apps.api.db.models import TenantAssignment
from apps.api.db.queries import (
    assign_internal_user_to_tenant,
    is_user_assigned_to_tenant,
    list_tenant_assignments_for_tenant,
    list_tenant_assignments_for_user,
    unassign_internal_user_from_tenant,
)

# ----------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
TENANT_ID_2 = UUID("22222222-2222-2222-2222-222222222222")
INTERNAL_USER_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
ASSIGNMENT_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


# ----------------------------------------------------------------
# Factories
# ----------------------------------------------------------------


def make_assignment_row(
    *,
    id: UUID = ASSIGNMENT_ID,
    tenant_id: UUID = TENANT_ID,
    internal_user_id: UUID = INTERNAL_USER_ID,
    role_in_tenant: str = "aide_primary",
    assigned_by: UUID | None = None,
    unassigned_at: datetime | None = None,
) -> dict:
    return {
        "id": id,
        "tenant_id": tenant_id,
        "internal_user_id": internal_user_id,
        "role_in_tenant": role_in_tenant,
        "assigned_at": NOW,
        "assigned_by": assigned_by,
        "unassigned_at": unassigned_at,
    }


# ----------------------------------------------------------------
# Tests: assign_internal_user_to_tenant
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_creates_assignment() -> None:
    row = make_assignment_row()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)

    result = await assign_internal_user_to_tenant(
        conn,
        tenant_id=TENANT_ID,
        internal_user_id=INTERNAL_USER_ID,
        role_in_tenant="aide_primary",
    )

    assert isinstance(result, TenantAssignment)
    assert result.tenant_id == TENANT_ID
    assert result.internal_user_id == INTERNAL_USER_ID
    assert result.role_in_tenant == "aide_primary"
    assert result.unassigned_at is None


@pytest.mark.asyncio
async def test_assign_with_assigned_by() -> None:
    assigner_id = uuid4()
    row = make_assignment_row(assigned_by=assigner_id)
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)

    result = await assign_internal_user_to_tenant(
        conn,
        tenant_id=TENANT_ID,
        internal_user_id=INTERNAL_USER_ID,
        role_in_tenant="aide_primary",
        assigned_by=assigner_id,
    )
    assert result.assigned_by == assigner_id


# ----------------------------------------------------------------
# Tests: unassign_internal_user_from_tenant
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_unassign_success() -> None:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")
    result = await unassign_internal_user_from_tenant(conn, assignment_id=ASSIGNMENT_ID)
    assert result is True


@pytest.mark.asyncio
async def test_unassign_already_unassigned() -> None:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    result = await unassign_internal_user_from_tenant(conn, assignment_id=ASSIGNMENT_ID)
    assert result is False


# ----------------------------------------------------------------
# Tests: list_tenant_assignments_for_user
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_assignments_for_user_multiple_tenants() -> None:
    rows = [
        make_assignment_row(tenant_id=TENANT_ID, role_in_tenant="aide_primary"),
        make_assignment_row(id=uuid4(), tenant_id=TENANT_ID_2, role_in_tenant="aide_backup"),
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)

    result = await list_tenant_assignments_for_user(conn, internal_user_id=INTERNAL_USER_ID)
    assert len(result) == 2
    roles = {r.role_in_tenant for r in result}
    assert roles == {"aide_primary", "aide_backup"}


@pytest.mark.asyncio
async def test_list_assignments_for_user_empty() -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    result = await list_tenant_assignments_for_user(conn, internal_user_id=uuid4())
    assert result == []


# ----------------------------------------------------------------
# Tests: list_tenant_assignments_for_tenant
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_assignments_for_tenant() -> None:
    aide_id = uuid4()
    qa_id = uuid4()
    rows = [
        make_assignment_row(internal_user_id=aide_id, role_in_tenant="aide_primary"),
        make_assignment_row(id=uuid4(), internal_user_id=qa_id, role_in_tenant="qa_assigned"),
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)

    result = await list_tenant_assignments_for_tenant(conn, tenant_id=TENANT_ID)
    assert len(result) == 2
    roles = {r.role_in_tenant for r in result}
    assert "aide_primary" in roles
    assert "qa_assigned" in roles


@pytest.mark.asyncio
async def test_list_assignments_for_tenant_empty() -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    result = await list_tenant_assignments_for_tenant(conn, tenant_id=uuid4())
    assert result == []


# ----------------------------------------------------------------
# Tests: is_user_assigned_to_tenant
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_user_assigned_true() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"1": 1})
    result = await is_user_assigned_to_tenant(
        conn, internal_user_id=INTERNAL_USER_ID, tenant_id=TENANT_ID
    )
    assert result is True


@pytest.mark.asyncio
async def test_is_user_assigned_false() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    result = await is_user_assigned_to_tenant(conn, internal_user_id=uuid4(), tenant_id=uuid4())
    assert result is False
