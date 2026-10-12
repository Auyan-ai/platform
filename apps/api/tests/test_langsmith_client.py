"""Tests del wrapper `LangSmithClient`."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from apps.api.integrations.langsmith_client import LangSmithClient, LangSmithTrace


class TestEnabled:
    def test_is_enabled_when_inner_client_present(self) -> None:
        client = LangSmithClient(MagicMock(), project_name="auyan-test")
        assert client.is_enabled is True

    def test_is_disabled_when_inner_client_none(self) -> None:
        client = LangSmithClient(None, project_name="auyan-test")
        assert client.is_enabled is False


class TestStartTrace:
    def test_returns_none_when_disabled(self) -> None:
        client = LangSmithClient(None, project_name="auyan-test")
        assert (
            client.start_conversation_trace(
                tenant_id="t",
                conversation_id="c",
                end_customer_id="cu",
                channel="chat",
                input_text="hi",
            )
            is None
        )

    def test_calls_inner_create_run_when_enabled(self) -> None:
        inner = MagicMock()
        client = LangSmithClient(inner, project_name="auyan-test")

        result = client.start_conversation_trace(
            tenant_id="t1",
            conversation_id="c1",
            end_customer_id="cu1",
            channel="chat",
            input_text="hola",
        )

        assert isinstance(result, LangSmithTrace)
        inner.create_run.assert_called_once()
        kwargs = inner.create_run.call_args.kwargs
        assert isinstance(kwargs["id"], UUID)
        assert kwargs["trace_id"] == kwargs["id"]
        assert isinstance(kwargs["dotted_order"], str)
        assert kwargs["project_name"] == "auyan-test"
        assert kwargs["name"] == "agent_conversation"
        assert kwargs["run_type"] == "chain"
        assert kwargs["inputs"] == {"message": "hola"}
        assert "tenant:t1" in kwargs["tags"]
        assert kwargs["extra"]["metadata"]["conversation_id"] == "c1"

    def test_swallows_exceptions_from_inner_client(self) -> None:
        inner = MagicMock()
        inner.create_run.side_effect = RuntimeError("langsmith_down")
        client = LangSmithClient(inner, project_name="auyan-test")

        result = client.start_conversation_trace(
            tenant_id="t",
            conversation_id="c",
            end_customer_id="cu",
            channel="chat",
            input_text="x",
        )

        assert result is None


class TestFinalizeTrace:
    def test_noop_when_trace_is_none(self) -> None:
        client = LangSmithClient(MagicMock(), project_name="auyan-test")
        client.finalize_trace(
            None,
            decision="respond",
            confidence=0.9,
            response_text="x",
            escalation_reason=None,
            tokens_in=10,
            tokens_cache_write=0,
            tokens_cache_read=0,
            tokens_out=5,
            cost_usd=0.001,
            model="m",
            error=None,
        )

    def test_calls_update_run_with_outputs_and_metadata(self) -> None:
        inner = MagicMock()
        client = LangSmithClient(inner, project_name="auyan-test")
        trace = LangSmithTrace(
            run_id=UUID("00000000-0000-0000-0000-000000000001"),
            dotted_order="20260101T000000000000Z00000000-0000-0000-0000-000000000001",
        )

        client.finalize_trace(
            trace,
            decision="respond",
            confidence=0.9,
            response_text="x",
            escalation_reason=None,
            tokens_in=10,
            tokens_cache_write=2,
            tokens_cache_read=6,
            tokens_out=5,
            cost_usd=0.001,
            model="m",
            error=None,
        )

        assert inner.create_run.call_count == 1
        usage_create_kwargs = inner.create_run.call_args.kwargs
        assert usage_create_kwargs["name"] == "agent_model_call"
        assert usage_create_kwargs["run_type"] == "llm"
        assert usage_create_kwargs["trace_id"] == trace.run_id
        assert usage_create_kwargs["parent_run_id"] == trace.run_id
        assert usage_create_kwargs["extra"]["metadata"]["usage_metadata"] == {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_token_details": {"cache_creation": 2, "cache_read": 6},
            "total_cost": 0.001,
        }

        assert inner.update_run.call_count == 2
        args, kwargs = inner.update_run.call_args_list[-1]
        assert args[0] == trace.run_id
        assert kwargs["trace_id"] == trace.run_id
        assert kwargs["dotted_order"] == trace.dotted_order
        assert kwargs["outputs"]["decision"] == "respond"
        assert kwargs["extra"]["metadata"]["tokens_in"] == 10
        assert kwargs["error"] is None

    def test_sets_error_on_error(self) -> None:
        inner = MagicMock()
        client = LangSmithClient(inner, project_name="auyan-test")
        trace = LangSmithTrace(
            run_id=UUID("00000000-0000-0000-0000-000000000001"),
            dotted_order="20260101T000000000000Z00000000-0000-0000-0000-000000000001",
        )

        client.finalize_trace(
            trace,
            decision="error",
            confidence=None,
            response_text=None,
            escalation_reason=None,
            tokens_in=0,
            tokens_cache_write=0,
            tokens_cache_read=0,
            tokens_out=0,
            cost_usd=0.0,
            model=None,
            error="boom",
        )

        kwargs = inner.update_run.call_args.kwargs
        assert kwargs["error"] == "boom"
        assert kwargs["extra"]["metadata"]["had_error"] is True

    def test_finalizes_root_when_model_usage_child_fails(self) -> None:
        inner = MagicMock()
        inner.create_run.side_effect = RuntimeError("child failed")
        client = LangSmithClient(inner, project_name="auyan-test")
        trace = LangSmithTrace(
            run_id=UUID("00000000-0000-0000-0000-000000000001"),
            dotted_order="20260101T000000000000Z00000000-0000-0000-0000-000000000001",
        )

        client.finalize_trace(
            trace,
            decision="respond",
            confidence=0.9,
            response_text="x",
            escalation_reason=None,
            tokens_in=10,
            tokens_cache_write=0,
            tokens_cache_read=0,
            tokens_out=5,
            cost_usd=0.001,
            model="m",
            error=None,
        )

        inner.update_run.assert_called_once()
        assert inner.update_run.call_args.args[0] == trace.run_id

    def test_swallows_exceptions_from_inner_client(self) -> None:
        inner = MagicMock()
        inner.update_run.side_effect = RuntimeError("network_error")
        client = LangSmithClient(inner, project_name="auyan-test")
        trace = LangSmithTrace(
            run_id=UUID("00000000-0000-0000-0000-000000000001"),
            dotted_order="20260101T000000000000Z00000000-0000-0000-0000-000000000001",
        )

        client.finalize_trace(
            trace,
            decision="respond",
            confidence=0.9,
            response_text="x",
            escalation_reason=None,
            tokens_in=10,
            tokens_cache_write=0,
            tokens_cache_read=0,
            tokens_out=5,
            cost_usd=0.001,
            model="m",
            error=None,
        )


class TestTraceId:
    def test_returns_none_for_none_trace(self) -> None:
        assert LangSmithClient(MagicMock(), project_name="auyan-test").trace_id(None) is None

    def test_extracts_run_id(self) -> None:
        run_id = UUID("00000000-0000-0000-0000-000000000001")
        trace = LangSmithTrace(
            run_id=run_id,
            dotted_order="20260101T000000000000Z00000000-0000-0000-0000-000000000001",
        )
        assert LangSmithClient(MagicMock(), project_name="auyan-test").trace_id(trace) == str(
            run_id
        )


class TestFlush:
    @pytest.mark.asyncio
    async def test_flush_when_disabled_is_noop(self) -> None:
        await LangSmithClient(None, project_name="auyan-test").flush()

    @pytest.mark.asyncio
    async def test_flush_calls_inner_via_thread(self) -> None:
        inner = MagicMock()
        client = LangSmithClient(inner, project_name="auyan-test")

        await client.flush()

        inner.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_swallows_inner_errors(self) -> None:
        inner = MagicMock()
        inner.flush.side_effect = RuntimeError("flush failed")
        client = LangSmithClient(inner, project_name="auyan-test")

        await client.flush()


def test_finalize_keeps_supabase_correlation_metadata() -> None:
    """`update_run` reemplaza extra.metadata: el finalize debe reenviar tenant_id y
    conversation_id o el run deja de correlacionar con Supabase (visto en staging)."""
    inner = MagicMock()
    client = LangSmithClient(inner, project_name="auyan-test")
    trace = client.start_conversation_trace(
        tenant_id="t-1",
        conversation_id="c-1",
        end_customer_id="cu-1",
        channel="zendesk",
        input_text="hola",
    )
    assert trace is not None

    client.finalize_trace(
        trace,
        decision="respond",
        confidence=0.9,
        response_text="x",
        escalation_reason=None,
        tokens_in=10,
        tokens_cache_write=0,
        tokens_cache_read=0,
        tokens_out=5,
        cost_usd=0.001,
        model="m",
        error=None,
    )

    metadata = inner.update_run.call_args_list[-1].kwargs["extra"]["metadata"]
    assert metadata["tenant_id"] == "t-1"
    assert metadata["conversation_id"] == "c-1"
    assert metadata["end_customer_id"] == "cu-1"
    assert metadata["channel"] == "zendesk"
    assert metadata["tokens_in"] == 10
