"""Tests del wrapper combinado de observabilidad."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.integrations.observability import ObservabilityClient


@dataclass
class _FakeClient:
    is_enabled: bool
    trace_id_value: str | None

    def __post_init__(self) -> None:
        self.start_conversation_trace = MagicMock(
            return_value=MagicMock(id=self.trace_id_value) if self.trace_id_value else None
        )
        self.finalize_trace = MagicMock()
        self.trace_id = MagicMock(return_value=self.trace_id_value)
        self.flush = AsyncMock()


def _client(*, enabled: bool, trace_id: str | None) -> _FakeClient:
    return _FakeClient(is_enabled=enabled, trace_id_value=trace_id)


class TestStartAndTraceId:
    def test_uses_primary_trace_id_when_available(self) -> None:
        primary = _client(enabled=True, trace_id="ls-1")
        mirror = _client(enabled=True, trace_id="lf-1")
        client = ObservabilityClient(primary=primary, mirror=mirror)

        trace = client.start_conversation_trace(
            tenant_id="t",
            conversation_id="c",
            end_customer_id="cu",
            channel="chat",
            input_text="hola",
        )

        assert client.trace_id(trace) == "ls-1"
        primary.start_conversation_trace.assert_called_once()
        mirror.start_conversation_trace.assert_called_once()

    def test_falls_back_to_mirror_trace_id(self) -> None:
        primary = _client(enabled=False, trace_id=None)
        mirror = _client(enabled=True, trace_id="lf-1")
        client = ObservabilityClient(primary=primary, mirror=mirror)

        trace = client.start_conversation_trace(
            tenant_id="t",
            conversation_id="c",
            end_customer_id="cu",
            channel="chat",
            input_text="hola",
        )

        assert client.trace_id(trace) == "lf-1"


class TestFinalize:
    def test_finalizes_primary_and_mirror(self) -> None:
        primary = _client(enabled=True, trace_id="ls-1")
        mirror = _client(enabled=True, trace_id="lf-1")
        client = ObservabilityClient(primary=primary, mirror=mirror)
        trace = client.start_conversation_trace(
            tenant_id="t",
            conversation_id="c",
            end_customer_id="cu",
            channel="chat",
            input_text="hola",
        )

        client.finalize_trace(
            trace,
            decision="respond",
            confidence=0.9,
            response_text="ok",
            escalation_reason=None,
            tokens_in=1,
            tokens_out=2,
            cost_usd=0.001,
            model="m",
            error=None,
        )

        primary.finalize_trace.assert_called_once()
        mirror.finalize_trace.assert_called_once()


class TestFlush:
    @pytest.mark.asyncio
    async def test_flushes_primary_and_mirror(self) -> None:
        primary = _client(enabled=True, trace_id="ls-1")
        mirror = _client(enabled=True, trace_id="lf-1")
        client = ObservabilityClient(primary=primary, mirror=mirror)

        await client.flush()

        primary.flush.assert_awaited_once()
        mirror.flush.assert_awaited_once()
