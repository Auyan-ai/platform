"""Tests del job de limpieza de conversaciones abandonadas + nudges (Sprint 6.4 + 9.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from apps.api.services.cleanup import (
    DEFAULT_NUDGE_BEFORE_SECONDS,
    DEFAULT_NUDGE_MESSAGE,
    DEFAULT_TIMEOUTS,
    _build_cutoffs,
    _build_nudge_cutoffs,
    _close_abandoned_for_tenant,
    _nudge_for_tenant,
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
        patch("apps.api.services.cleanup._nudge_for_tenant", return_value=0),
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
        patch("apps.api.services.cleanup._nudge_for_tenant", return_value=0),
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
        patch("apps.api.services.cleanup._nudge_for_tenant", return_value=0),
        patch("apps.api.services.cleanup._close_abandoned_for_tenant", side_effect=fake_close),
    ):
        mock_boot.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_boot.return_value.__aexit__ = AsyncMock(return_value=False)

        results = await run_abandoned_cleanup()

    # tenant_a falló, tenant_b (2 cerradas) sigue incluido
    assert "beta" in results
    assert results["beta"] == 2
    assert "acme" not in results


# ============================================================
# _build_nudge_cutoffs
# ============================================================


def test_build_nudge_cutoffs_disabled_by_default() -> None:
    """nudge_enabled no seteado → retorna None."""
    result = _build_nudge_cutoffs(None, NOW)
    assert result is None


def test_build_nudge_cutoffs_disabled_when_false() -> None:
    config = make_tenant_configuration(extra={"nudge_enabled": False})
    assert _build_nudge_cutoffs(config, NOW) is None


def test_build_nudge_cutoffs_returns_ranges_when_enabled() -> None:
    config = make_tenant_configuration(extra={"nudge_enabled": True})
    result = _build_nudge_cutoffs(config, NOW)
    assert result is not None
    channel_ranges, default_range = result
    cutoff_min, cutoff_max = default_range
    # cutoff_min = NOW - timeout_default; cutoff_max = NOW - (timeout - nudge_before)
    expected_min = NOW - timedelta(seconds=DEFAULT_TIMEOUTS["default"])
    expected_max = NOW - timedelta(seconds=DEFAULT_TIMEOUTS["default"] - DEFAULT_NUDGE_BEFORE_SECONDS)
    assert cutoff_min == expected_min
    assert cutoff_max == expected_max


def test_build_nudge_cutoffs_custom_nudge_before() -> None:
    config = make_tenant_configuration(
        extra={"nudge_enabled": True, "nudge_before_seconds": 7200}
    )
    result = _build_nudge_cutoffs(config, NOW)
    assert result is not None
    _, default_range = result
    _, cutoff_max = default_range
    expected_max = NOW - timedelta(seconds=DEFAULT_TIMEOUTS["default"] - 7200)
    assert cutoff_max == expected_max


def test_build_nudge_cutoffs_invalid_nudge_before_returns_none() -> None:
    """nudge_before >= timeout del canal default → None (ventana inválida)."""
    config = make_tenant_configuration(
        extra={
            "nudge_enabled": True,
            "nudge_before_seconds": DEFAULT_TIMEOUTS["default"] + 1,
        }
    )
    assert _build_nudge_cutoffs(config, NOW) is None


# ============================================================
# _nudge_for_tenant
# ============================================================


@pytest.mark.asyncio
async def test_nudge_for_tenant_disabled_returns_zero() -> None:
    config = make_tenant_configuration(extra={"nudge_enabled": False})
    result = await _nudge_for_tenant(TENANT_ID, config)
    assert result == 0


@pytest.mark.asyncio
async def test_nudge_for_tenant_no_candidates_returns_zero() -> None:
    config = make_tenant_configuration(extra={"nudge_enabled": True})

    with (
        patch("apps.api.services.cleanup.tenant_scope") as mock_scope,
        patch("apps.api.services.cleanup.get_nudge_candidates", return_value=[]),
    ):
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _nudge_for_tenant(TENANT_ID, config)

    assert result == 0


@pytest.mark.asyncio
async def test_nudge_for_tenant_sends_message_and_marks_nudged() -> None:
    """Conversación chat con 23h de inactividad (chat timeout 24h, nudge 1h antes)."""
    config = make_tenant_configuration(extra={"nudge_enabled": True})

    # 23h de inactividad → dentro de la ventana (24h - 1h = 23h < 23h < 24h)
    activity = (NOW - timedelta(hours=23)).replace(tzinfo=None)
    candidates = [(CONV_A, "chat", activity)]

    with (
        patch("apps.api.services.cleanup.tenant_scope") as mock_scope,
        patch("apps.api.services.cleanup.get_nudge_candidates", return_value=candidates),
        patch("apps.api.services.cleanup.insert_message", return_value=MagicMock()) as mock_insert,
        patch("apps.api.services.cleanup.mark_conversations_nudged", return_value=1) as mock_mark,
        patch("apps.api.services.cleanup.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = NOW
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _nudge_for_tenant(TENANT_ID, config)

    assert result == 1
    mock_insert.assert_called_once()
    assert mock_insert.call_args.kwargs["conversation_id"] == CONV_A
    assert mock_insert.call_args.kwargs["content"] == DEFAULT_NUDGE_MESSAGE
    mock_mark.assert_called_once()


@pytest.mark.asyncio
async def test_nudge_for_tenant_skips_out_of_window_conversation() -> None:
    """Conversación chat con 10h de inactividad — todavía no en ventana de nudge."""
    config = make_tenant_configuration(extra={"nudge_enabled": True})

    activity = (NOW - timedelta(hours=10)).replace(tzinfo=None)
    candidates = [(CONV_B, "chat", activity)]

    with (
        patch("apps.api.services.cleanup.tenant_scope") as mock_scope,
        patch("apps.api.services.cleanup.get_nudge_candidates", return_value=candidates),
        patch("apps.api.services.cleanup.insert_message") as mock_insert,
        patch("apps.api.services.cleanup.mark_conversations_nudged") as mock_mark,
        patch("apps.api.services.cleanup.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = NOW
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _nudge_for_tenant(TENANT_ID, config)

    assert result == 0
    mock_insert.assert_not_called()
    mock_mark.assert_not_called()


@pytest.mark.asyncio
async def test_nudge_for_tenant_uses_custom_message() -> None:
    config = make_tenant_configuration(
        extra={
            "nudge_enabled": True,
            "nudge_message": "Hola, ¿seguimos en contacto?",
        }
    )

    activity = (NOW - timedelta(hours=23)).replace(tzinfo=None)
    candidates = [(CONV_A, "chat", activity)]

    with (
        patch("apps.api.services.cleanup.tenant_scope") as mock_scope,
        patch("apps.api.services.cleanup.get_nudge_candidates", return_value=candidates),
        patch("apps.api.services.cleanup.insert_message", return_value=MagicMock()) as mock_insert,
        patch("apps.api.services.cleanup.mark_conversations_nudged", return_value=1),
        patch("apps.api.services.cleanup.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = NOW
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

        await _nudge_for_tenant(TENANT_ID, config)

    assert mock_insert.call_args.kwargs["content"] == "Hola, ¿seguimos en contacto?"


@pytest.mark.asyncio
async def test_run_abandoned_cleanup_calls_nudge_before_close() -> None:
    """El job llama a _nudge_for_tenant antes que _close_abandoned_for_tenant."""
    tenant = make_tenant(id=TENANT_ID, slug="acme")
    config = make_tenant_configuration()
    call_order: list[str] = []

    async def fake_nudge(tid: UUID, cfg: object) -> int:
        call_order.append("nudge")
        return 1

    async def fake_close(tid: UUID, cfg: object) -> int:
        call_order.append("close")
        return 2

    with (
        patch("apps.api.services.cleanup.bootstrap_connection") as mock_boot,
        patch("apps.api.services.cleanup.list_all_tenants", return_value=[tenant]),
        patch("apps.api.services.cleanup.get_tenant_configuration", return_value=config),
        patch("apps.api.services.cleanup._nudge_for_tenant", side_effect=fake_nudge),
        patch("apps.api.services.cleanup._close_abandoned_for_tenant", side_effect=fake_close),
    ):
        mock_boot.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_boot.return_value.__aexit__ = AsyncMock(return_value=False)

        await run_abandoned_cleanup()

    assert call_order == ["nudge", "close"]
