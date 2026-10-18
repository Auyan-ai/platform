"""Lectura de la política en cada turno: un fallo de la tabla no tumba el turno (ADR 0014)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import asyncpg
import pytest
from apps.api.db.returns_policy import load_current_returns_policy

TENANT = UUID("11111111-1111-1111-1111-111111111111")


class _Conn:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.savepoints = 0

    @asynccontextmanager
    async def transaction(self) -> Any:
        self.savepoints += 1
        yield

    async def fetchrow(self, *args: Any) -> Any:
        if self.error:
            raise self.error
        return None


async def test_a_missing_table_reads_as_no_policy_inside_a_savepoint(
    caplog: pytest.LogCaptureFixture,
) -> None:
    conn = _Conn(asyncpg.exceptions.UndefinedTableError("relation does not exist"))

    assert await load_current_returns_policy(conn, TENANT) is None  # type: ignore[arg-type]
    assert conn.savepoints == 1
    assert "returns_policy_read_failed" in caplog.text


async def test_without_rows_there_is_no_policy() -> None:
    assert await load_current_returns_policy(_Conn(None), TENANT) is None  # type: ignore[arg-type]
