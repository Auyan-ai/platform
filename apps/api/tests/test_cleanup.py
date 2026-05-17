"""Tests del job de limpieza de conversaciones abandonadas (Sprint 6.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from apps.api.services.cleanup import (
    DEFAULT_TIMEOUTS,
    _build_cutoffs,
    _close_abandoned_for_tenant,
    run_abandoned_cleanup,
)
from apps.api.tests.conftest import make_tenant, make_tenant_configuration

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
CONV_A = uuid4()
CONV_B = uuid4()
CONV_C = uuid4()

NOW = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)


# ============================================================
# DEFAULT_TIMEOUTS — valores razonables
# ============================================================


def test_default_timeouts_have_default_key() -> None:
    assert "default" in DEFAULT_TIMEOUTS


def test_default_timeouts_all_positive() -> None:
    for ch, secs in DEFAULT_TIMEOUTS.items():
        assert secs > 0, f"timeout de {ch!r} debe ser positivo"


def test_default_timeout_email_longer_than_chat() -> None:
    assert DEFAULT_TIMEOUTS["email"] > DEFAULT_TIMEOUTS["chat"]


# ============================================================
# _build_cutoffs
# ============================================================


def test_build_cutoffs_no_config_uses_defaults() -> None:
    cutoffs, default_cutoff = _build_cutoffs(None, NOW)
    expected_chat = NOW - timedelta(seconds=DEFAULT_TIMEOUTS["chat"])
    assert cutoffs["chat"] == expected_chat
    assert default_cutoff == NOW - timedelta(seconds=DEFAULT_TIMEOUTS["default"])


def test_build_cutoffs_tenant_override_respected() -> None:
    config = make_tenant_configuration(
        extra={"conversation_timeouts": {"email": 3600, "default": 7200}}
    )
    cutoffs, default_cutoff = _build_cutoffs(config, NOW)
    assert cutoffs["email"] == NOW - timedelta(seconds=3600)
    assert default_cutoff == NOW - timedelta(seconds=7200)


def test_build_cutoffs_partial_override_keeps_other_defaults() -> None:
    config = make_tenant_configuration(
        extra={"conversation_timeouts": {"chat": 1800}}
    )
    cutoffs, _ = _build_cutoffs(config, NOW)
    assert cutoffs["chat"] == NOW - timedelta(seconds=1800)
    # email no fue overrideado → sigue con el default del módulo
    assert cutoffs["email"] == NOW - timedelta(seconds=DEFAULT_TIMEOUTS["email"])


def test_build_cutoffs_invalid_extra_ignored() -> None:
    """Si conversation_timeouts no es dict, se ignora sin explotar."""
    config = make_tenant_configuration(extra={"conversation_timeouts": "bad_value"})
    cutoffs, default_cutoff = _build_cutoffs(config, NOW)
    assert cutoffs["chat"] == NOW - timedelta(seconds=DEFAULT_TIMEOUTS["chat"])


# ============================================================
# _close_abandoned_for_tenant
# ============================================================


@pytest.mark.asyncio
async def test_close_abandoned_no_candidates_returns_zero() -> None:
    with (
        patch("apps.api.services.cleanup.tenant_scope") as mock_scope,
        patch("apps.api.services.cleanup.get_stale_conversations", return_value=[]),
        patch("apps.api.services.cleanup.mark_conversations_abandoned") as mock_mark,
    ):
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _close_abandoned_for_tenant(TENANT_ID, None)

    assert result == 0
    mock_mark.assert_not_called()


@pytest.mark.asyncio
async def test_close_abandoned_marks_stale_conversations() -> None:
    # chat tiene timeout 24h; la conversación tiene last_activity = 30h atrás
    old_activity = NOW - timedelta(hours=30)
    candidates = [(CONV_A, "chat", old_activity.replace(tzinfo=None))]  # asyncpg devuelve naive

    with (
        patch("apps.api.services.cleanup.tenant_scope") as mock_scope,
        patch("apps.api.services.cleanup.get_stale_conversations", return_value=candidates),
        patch("apps.api.services.cleanup.mark_conversations_abandoned", return_value=1) as mock_mark,
        patch("apps.api.services.cleanup.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = NOW
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _close_abandoned_for_tenant(TENANT_ID, None)

    assert result == 1
    mock_mark.assert_called_once()
    marked_ids = mock_mark.call_args[0][2]
    assert CONV_A in marked_ids


@pytest.mark.asyncio
async def test_close_abandoned_filters_by_channel_timeout() -> None:
    """Un email con 50h de inactividad NO debería cerrarse (email timeout=72h)."""
    not_yet_stale = NOW - timedelta(hours=50)
    candidates = [(CONV_B, "email", not_yet_stale.replace(tzinfo=None))]

    with (
        patch("apps.api.services.cleanup.tenant_scope") as mock_scope,
        patch("apps.api.services.cleanup.get_stale_conversations", return_value=candidates),
        patch("apps.api.services.cleanup.mark_conversations_abandoned", return_value=0) as mock_mark,
        patch("apps.api.services.cleanup.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = NOW
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _close_abandoned_for_tenant(TENANT_ID, None)

    assert result == 0
    mock_mark.assert_not_called()


@pytest.mark.asyncio
async def test_close_abandoned_tenant_override_timeout() -> None:
    """Un tenant con email timeout=3600s (1h) cierra un email de 2h de inactividad."""
    config = make_tenant_configuration(
        extra={"conversation_timeouts": {"email": 3600}}
    )
    stale_email = NOW - timedelta(hours=2)
    candidates = [(CONV_C, "email", stale_email.replace(tzinfo=None))]

    with (
        patch("apps.api.services.cleanup.tenant_scope") as mock_scope,
        patch("apps.api.services.cleanup.get_stale_conversations", return_value=candidates),
        patch("apps.api.services.cleanup.mark_conversations_abandoned", return_value=1) as mock_mark,
        patch("apps.api.services.cleanup.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = NOW
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _close_abandoned_for_tenant(TENANT_ID, config)

    assert result == 1
    marked_ids = mock_mark.call_args[0][2]
    assert CONV_C in marked_ids


# ============================================================
# run_abandoned_cleanup — orquestación
# ============================================================


@pytest.mark.asyncio
async def test_run_abandoned_cleanup_returns_dict_with_closed() -> None:
    tenant = make_tenant(id=TENANT_ID, slug="acme")
    config = make_tenant_configuration()

    with (
        patch("apps.api.services.cleanup.bootstrap_connection") as mock_boot,
        patch("apps.api.services.cleanup.list_all_tenants", return_value=[tenant]),
        patch("apps.api.services.cleanup.get_tenant_configuration", return_value=config),
        patch(
            "apps.api.services.cleanup._close_abandoned_for_tenant",
            return_value=3,
        ),
    ):
        mock_boot.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_boot.return_value.__aexit__ = AsyncMock(return_value=False)

        results = await run_abandoned_cleanup()

    assert results == {"acme": 3}


@pytest.mark.asyncio
async def test_run_abandoned_cleanup_skips_tenants_with_zero_closed() -> None:
    tenant = make_tenant(id=TENANT_ID, slug="acme")

    with (
        patch("apps.api.services.cleanup.bootstrap_connection") as mock_boot,
        patch("apps.api.services.cleanup.list_all_tenants", return_value=[tenant]),
        patch("apps.api.services.cleanup.get_tenant_configuration", return_value=None),
        patch("apps.api.services.cleanup._close_abandoned_for_tenant", return_value=0),
    ):
        mock_boot.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_boot.return_value.__aexit__ = AsyncMock(return_value=False)

        results = await run_abandoned_cleanup()

    assert results == {}


@pytest.mark.asyncio
async def test_run_abandoned_cleanup_continues_after_tenant_error() -> None:
    """Un error en un tenant no debe abortar el job para los demás."""
    tenant_a = make_tenant(id=uuid4(), slug="acme")
    tenant_b = make_tenant(id=uuid4(), slug="beta")

    close_calls = [Exception("db error"), 2]

    async def fake_close(tid: UUID, cfg: object) -> int:
        val = close_calls.pop(0)
        if isinstance(val, Exception):
            raise val
        return val  # type: ignore[return-value]

    with (
        patch("apps.api.services.cleanup.bootstrap_connection") as mock_boot,
        patch("apps.api.services.cleanup.list_all_tenants", return_value=[tenant_a, tenant_b]),
        patch("apps.api.services.cleanup.get_tenant_configuration", return_value=None),
        patch("apps.api.services.cleanup._close_abandoned_for_tenant", side_effect=fake_close),
    ):
        mock_boot.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_boot.return_value.__aexit__ = AsyncMock(return_value=False)

        results = await run_abandoned_cleanup()

    # tenant_a falló, tenant_b (2 cerradas) sigue incluido
    assert "beta" in results
    assert results["beta"] == 2
    assert "acme" not in results
