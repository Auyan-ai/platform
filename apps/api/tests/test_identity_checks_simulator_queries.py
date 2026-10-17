"""Queries que usa el simulador: intentos de identidad, aprobaciones y la marca de simulación."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from apps.api.db.identity_checks import count_conversation_attempts, soft_delete_conversation_checks
from apps.api.db.queries import is_simulation_conversation, list_pending_approval_inputs


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


async def test_is_simulation_conversation_is_false_for_missing_or_real() -> None:
    conn = AsyncMock()
    conn.fetchval.return_value = None
    assert await is_simulation_conversation(conn, uuid4(), uuid4()) is False
    conn.fetchval.return_value = False
    assert await is_simulation_conversation(conn, uuid4(), uuid4()) is False
    conn.fetchval.return_value = True
    assert await is_simulation_conversation(conn, uuid4(), uuid4()) is True
    # El run soft-deletea su conversación al terminar: la marca debe seguir viéndose.
    assert "deleted_at" not in conn.fetchval.await_args.args[0]
