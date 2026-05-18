"""Tests para AopCacheListener y las funciones de soporte de invalidación de cache."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apps.api.aops.compiler import _AOP_CACHE, invalidate_aop_cache
from apps.api.services.aop_listener import AopCacheListener


def _make_mock_conn(*, closed: bool = False) -> AsyncMock:
    """Crea un AsyncMock de asyncpg.Connection con is_closed() síncrono."""
    conn = AsyncMock()
    conn.is_closed = MagicMock(return_value=closed)
    return conn

# ─── invalidate_aop_cache ────────────────────────────────────────────────────


def test_invalidate_removes_existing_key():
    key = ("tenant-1", "consulta_envio", "production")
    _AOP_CACHE[key] = MagicMock()  # type: ignore[assignment]
    assert key in _AOP_CACHE
    invalidate_aop_cache("tenant-1", "consulta_envio", "production")
    assert key not in _AOP_CACHE


def test_invalidate_noop_for_missing_key():
    """No lanza si la clave no existe."""
    invalidate_aop_cache("tenant-x", "nonexistent", "staging")  # debe ser silencioso


def test_invalidate_only_removes_specific_key():
    key_a = ("tenant-1", "aop_a", "production")
    key_b = ("tenant-1", "aop_b", "production")
    sentinel = MagicMock()
    _AOP_CACHE[key_a] = sentinel  # type: ignore[assignment]
    _AOP_CACHE[key_b] = MagicMock()  # type: ignore[assignment]
    invalidate_aop_cache("tenant-1", "aop_a", "production")
    assert key_a not in _AOP_CACHE
    assert key_b in _AOP_CACHE
    del _AOP_CACHE[key_b]


# ─── notify_aop_cache_invalidated ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_executes_pg_notify():
    from apps.api.db.queries import notify_aop_cache_invalidated

    conn = AsyncMock()
    await notify_aop_cache_invalidated(conn, "tenant-abc", "my_aop", "production")

    conn.execute.assert_awaited_once()
    call_args = conn.execute.call_args
    sql: str = call_args[0][0]
    payload_str: str = call_args[0][1]

    assert "pg_notify" in sql
    assert "aop_cache_invalidated" in sql

    payload = json.loads(payload_str)
    assert payload == {"tenant_id": "tenant-abc", "slug": "my_aop", "workspace": "production"}


@pytest.mark.asyncio
async def test_notify_stringifies_uuid_tenant_id():
    """tenant_id puede llegar como UUID — debe stringificarse en el payload."""
    from uuid import UUID

    from apps.api.db.queries import notify_aop_cache_invalidated

    conn = AsyncMock()
    uid = UUID("11111111-1111-1111-1111-111111111111")
    await notify_aop_cache_invalidated(conn, uid, "aop_slug", "staging")

    payload_str: str = conn.execute.call_args[0][1]
    payload = json.loads(payload_str)
    assert payload["tenant_id"] == "11111111-1111-1111-1111-111111111111"


# ─── AopCacheListener.start / stop ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_listener_start_creates_connection_and_listens():
    listener = AopCacheListener()
    mock_conn = _make_mock_conn()

    with patch("apps.api.services.aop_listener.asyncpg.connect", return_value=mock_conn):
        await listener.start("postgresql://test/db")

    mock_conn.add_listener.assert_awaited_once_with("aop_cache_invalidated", listener._on_notify)
    assert listener._task is not None
    assert not listener._task.done()
    await listener.stop()


@pytest.mark.asyncio
async def test_listener_stop_cancels_task_and_closes_conn():
    listener = AopCacheListener()
    mock_conn = _make_mock_conn()

    with patch("apps.api.services.aop_listener.asyncpg.connect", return_value=mock_conn):
        await listener.start("postgresql://test/db")

    await listener.stop()

    mock_conn.close.assert_awaited_once()
    assert listener._conn is None
    assert listener._task is None


# ─── AopCacheListener._on_notify ─────────────────────────────────────────────


def test_on_notify_valid_payload_calls_invalidate():
    listener = AopCacheListener()
    payload = json.dumps(
        {"tenant_id": "t-1", "slug": "returns_aop", "workspace": "production"}
    )

    key = ("t-1", "returns_aop", "production")
    _AOP_CACHE[key] = MagicMock()  # type: ignore[assignment]

    listener._on_notify(MagicMock(), 1234, "aop_cache_invalidated", payload)

    assert key not in _AOP_CACHE


def test_on_notify_invalid_json_logs_error_silently():
    listener = AopCacheListener()
    # No debe lanzar excepción — solo loguear
    listener._on_notify(MagicMock(), 1234, "aop_cache_invalidated", "NOT_JSON{{{")


def test_on_notify_missing_key_logs_error_silently():
    listener = AopCacheListener()
    # payload sin campo 'slug'
    payload = json.dumps({"tenant_id": "t-1", "workspace": "production"})
    listener._on_notify(MagicMock(), 1234, "aop_cache_invalidated", payload)


# ─── Keep-alive loop ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_keep_alive_pings_connection():
    listener = AopCacheListener()
    mock_conn = _make_mock_conn(closed=False)
    listener._conn = mock_conn

    with patch("apps.api.services.aop_listener._KEEPALIVE_INTERVAL", 0):
        task = asyncio.create_task(listener._keep_alive_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    mock_conn.execute.assert_awaited_with("SELECT 1")


@pytest.mark.asyncio
async def test_keep_alive_skips_closed_connection():
    listener = AopCacheListener()
    mock_conn = _make_mock_conn(closed=True)
    listener._conn = mock_conn

    with patch("apps.api.services.aop_listener._KEEPALIVE_INTERVAL", 0):
        task = asyncio.create_task(listener._keep_alive_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    mock_conn.execute.assert_not_awaited()
