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
            tokens_cache_write=0,
            tokens_cache_read=0,
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


class TestFreeTextPiiIsMasked:
    """El texto libre del cliente/agente no lleva emails ni teléfonos a terceros."""

    def test_input_masked_for_primary_and_mirror(self) -> None:
        primary = _client(enabled=True, trace_id="ls-1")
        mirror = _client(enabled=True, trace_id="lf-1")
        client = ObservabilityClient(primary=primary, mirror=mirror)

        client.start_conversation_trace(
            tenant_id="t",
            conversation_id="c",
            end_customer_id="cu",
            channel="zendesk",
            input_text="¿Pedido #1429? soy ana@test.com, tel 612 345 678",
        )

        for fake in (primary, mirror):
            sent = fake.start_conversation_trace.call_args.kwargs["input_text"]
            assert sent == "¿Pedido #1429? soy <email>, tel ***-5678"

    def test_response_and_escalation_reason_masked(self) -> None:
        primary = _client(enabled=True, trace_id="ls-1")
        client = ObservabilityClient(primary=primary)
        trace = client.start_conversation_trace(
            tenant_id="t", conversation_id="c", end_customer_id="cu", channel="x", input_text="hi"
        )

        client.finalize_trace(
            trace,
            decision="escalate",
            confidence=0.5,
            response_text="Te escribimos a ana@test.com",
            escalation_reason="Cliente ana@test.com pide reembolso",
            tokens_in=1,
            tokens_cache_write=0,
            tokens_cache_read=0,
            tokens_out=1,
            cost_usd=0.0,
            model="m",
            error=None,
        )

        kwargs = primary.finalize_trace.call_args.kwargs
        assert kwargs["response_text"] == "Te escribimos a <email>"
        assert kwargs["escalation_reason"] == "Cliente <email> pide reembolso"

    def test_node_outputs_masked_recursively(self) -> None:
        primary = _client(enabled=True, trace_id="ls-1")
        primary.record_node_run = MagicMock()
        client = ObservabilityClient(primary=primary)

        client.record_node_run(
            trace_run_id="00000000-0000-0000-0000-000000000001",
            trace_dotted_order="x",
            node_name="reason",
            start_time=MagicMock(),
            end_time=MagicMock(),
            outputs={"agent_response": "ok ana@test.com", "tool_results": [{"n": 1429}]},
        )

        outputs = primary.record_node_run.call_args.kwargs["outputs"]
        assert outputs == {"agent_response": "ok <email>", "tool_results": [{"n": 1429}]}
