"""Tests del wrapper `LangfuseClient`."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from apps.api.integrations.langfuse_client import LangfuseClient, build_langfuse_client
from pydantic import HttpUrl, SecretStr


class TestEnabled:
    def test_is_enabled_when_inner_client_present(self) -> None:
        client = LangfuseClient(MagicMock())
        assert client.is_enabled is True

    def test_is_disabled_when_inner_client_none(self) -> None:
        client = LangfuseClient(None)
        assert client.is_enabled is False


class TestStartTrace:
    def test_returns_none_when_disabled(self) -> None:
        client = LangfuseClient(None)
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

    def test_calls_inner_trace_when_enabled(self) -> None:
        inner = MagicMock()
        trace = MagicMock(id="trace-1")
        inner.trace.return_value = trace
        client = LangfuseClient(inner)

        result = client.start_conversation_trace(
            tenant_id="t1",
            conversation_id="c1",
            end_customer_id="cu1",
            channel="chat",
            input_text="hola",
        )

        assert result is trace
        inner.trace.assert_called_once()
        kwargs = inner.trace.call_args.kwargs
        assert kwargs["user_id"] == "cu1"
        assert kwargs["session_id"] == "c1"
        assert kwargs["input"] == "hola"
        assert "tenant:t1" in kwargs["tags"]

    def test_swallows_exceptions_from_inner_client(self) -> None:
        """Si Langfuse SDK explota, no debe propagar al flujo del agente."""
        inner = MagicMock()
        inner.trace.side_effect = RuntimeError("langfuse_down")
        client = LangfuseClient(inner)

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
        client = LangfuseClient(MagicMock())
        # No debería tirar
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

    def test_calls_trace_update_with_output_and_metadata(self) -> None:
        client = LangfuseClient(MagicMock())
        trace = MagicMock()
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
        trace.update.assert_called_once()
        kwargs = trace.update.call_args.kwargs
        assert kwargs["output"]["decision"] == "respond"
        assert kwargs["metadata"]["tokens_in"] == 10
        assert kwargs["level"] == "DEFAULT"

    def test_sets_error_level_on_error(self) -> None:
        client = LangfuseClient(MagicMock())
        trace = MagicMock()
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
        kwargs = trace.update.call_args.kwargs
        assert kwargs["level"] == "ERROR"
        assert kwargs["metadata"]["had_error"] is True

    def test_swallows_exceptions_from_inner_trace(self) -> None:
        client = LangfuseClient(MagicMock())
        trace = MagicMock()
        trace.update.side_effect = RuntimeError("network_error")

        # No debe propagar
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
        assert LangfuseClient(MagicMock()).trace_id(None) is None

    def test_extracts_id_attribute(self) -> None:
        trace = MagicMock(id="trace-xyz")
        assert LangfuseClient(MagicMock()).trace_id(trace) == "trace-xyz"


class TestFlush:
    @pytest.mark.asyncio
    async def test_flush_when_disabled_is_noop(self) -> None:
        await LangfuseClient(None).flush()

    @pytest.mark.asyncio
    async def test_flush_calls_inner_via_thread(self) -> None:
        inner = MagicMock()
        client = LangfuseClient(inner)
        await client.flush()
        inner.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_swallows_inner_errors(self) -> None:
        inner = MagicMock()
        inner.flush.side_effect = RuntimeError("flush failed")
        client = LangfuseClient(inner)
        # No debe propagar
        await client.flush()


class TestBuildLangfuseClient:
    def test_missing_credentials_disables_client(self) -> None:
        settings = MagicMock()
        settings.langfuse_public_key = None
        settings.langfuse_secret_key = None

        client = build_langfuse_client(settings)

        assert client.is_enabled is False

    def test_present_credentials_builds_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = MagicMock()
        settings.langfuse_public_key = SecretStr("public")
        settings.langfuse_secret_key = SecretStr("secret")
        settings.langfuse_host = HttpUrl("https://cloud.langfuse.com")
        inner = MagicMock()
        langfuse_cls = MagicMock(return_value=inner)
        monkeypatch.setattr("apps.api.integrations.langfuse_client.Langfuse", langfuse_cls)

        client = build_langfuse_client(settings)

        assert client.is_enabled is True
        langfuse_cls.assert_called_once()
