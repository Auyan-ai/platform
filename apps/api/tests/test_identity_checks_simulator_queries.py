"""Queries de `identity_checks` que usa el simulador: contar intentos y borrar los de un run."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from apps.api.db.identity_checks import count_conversation_attempts, soft_delete_conversation_checks
from apps.api.db.queries import list_pending_approval_inputs


async def test_count_conversation_attempts_returns_zero_for_no_rows() -> None:
    conn = AsyncMock()
    conn.fetchval.return_value = None
    assert await count_conversation_attempts(conn, uuid4(), uuid4()) == 0
    conn.fetchval.return_value = 4
    assert await count_conversation_attempts(conn, uuid4(), uuid4()) == 4


async def test_soft_delete_conversation_checks_returns_the_rows_deleted() -> None:
    conn = AsyncMock()
    conn.execute.return_value = "UPDATE 3"
    assert await soft_delete_conversation_checks(conn, uuid4(), uuid4()) == 3
    sql = conn.execute.await_args.args[0]
    assert "deleted_at = now()" in sql
    assert "DELETE" not in sql.upper().replace("DELETED_AT", "")


async def test_list_pending_approval_inputs_keys_by_skill_and_accepts_json_text() -> None:
    conn = AsyncMock()
    conn.fetch.return_value = [
        {"skill_slug": "shopify.cancel_order", "inputs_raw": '{"refund_mode": "manual"}'},
        {"skill_slug": "shopify.start_return", "inputs_raw": {"order_id": 1}},
    ]
    assert await list_pending_approval_inputs(conn, uuid4(), uuid4()) == {
        "shopify.cancel_order": {"refund_mode": "manual"},
        "shopify.start_return": {"order_id": 1},
    }
