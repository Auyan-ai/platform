"""Tests del retry behavior de `call_claude_with_tools`.

Verifica que tenacity reintenta sólo errores transitorios, que respeta
`max_retries`, y que el wrapper pasa `tool_choice` correctamente al cliente.
Parchea `asyncio.sleep` para que el test sea instantáneo en lugar de esperar
los backoffs reales.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest
from apps.api.agents.schemas import RESPOND_OR_ESCALATE_TOOL
from apps.api.integrations.anthropic_client import call_claude_with_tools


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """Hace que los backoffs de tenacity no esperen tiempo real."""
    import asyncio

    async def _noop(seconds):  # type: ignore[no-untyped-def]
        return

    monkeypatch.setattr(asyncio, "sleep", _noop)


def _conn_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )


def _fake_response() -> MagicMock:
    """Mock con la forma mínima que call_claude_with_tools espera devolver."""
    resp = MagicMock()
    resp.content = []
    resp.usage = MagicMock(input_tokens=10, output_tokens=5)
    return resp


@pytest.mark.asyncio
async def test_succeeds_on_first_attempt() -> None:
    client = MagicMock()
    fake_resp = _fake_response()
    client.messages.create = AsyncMock(return_value=fake_resp)

    result = await call_claude_with_tools(
        client=client,
        model="claude-sonnet-4-6",
        system="x",
        messages=[{"role": "user", "content": "y"}],
        tools=[RESPOND_OR_ESCALATE_TOOL],
        tool_choice={"type": "any"},
        max_retries=3,
    )

    assert result is fake_resp
    assert client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_retries_on_connection_error_and_succeeds() -> None:
    """Falla dos veces, tercera vez OK → debe reintentar y devolver la buena."""
    client = MagicMock()
    fake_resp = _fake_response()
    client.messages.create = AsyncMock(
        side_effect=[_conn_error(), _conn_error(), fake_resp]
    )

    result = await call_claude_with_tools(
        client=client,
        model="claude-sonnet-4-6",
        system="x",
        messages=[{"role": "user", "content": "y"}],
        tools=[RESPOND_OR_ESCALATE_TOOL],
        tool_choice={"type": "any"},
        max_retries=3,
    )

    assert result is fake_resp
    assert client.messages.create.await_count == 3


@pytest.mark.asyncio
async def test_raises_after_exhausting_retries() -> None:
    """Si los 3 intentos fallan, el error original se propaga."""
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=_conn_error())

    with pytest.raises(anthropic.APIConnectionError):
        await call_claude_with_tools(
            client=client,
            model="claude-sonnet-4-6",
            system="x",
            messages=[{"role": "user", "content": "y"}],
            tools=[RESPOND_OR_ESCALATE_TOOL],
            tool_choice={"type": "any"},
            max_retries=3,
        )

    assert client.messages.create.await_count == 3


@pytest.mark.asyncio
async def test_does_not_retry_non_transient_errors() -> None:
    """`anthropic.BadRequestError` (4xx) no es retryable — falla al primer intento."""
    client = MagicMock()
    bad_request = anthropic.BadRequestError(
        message="invalid request",
        response=MagicMock(status_code=400, headers={}),
        body=None,
    )
    client.messages.create = AsyncMock(side_effect=bad_request)

    with pytest.raises(anthropic.BadRequestError):
        await call_claude_with_tools(
            client=client,
            model="claude-sonnet-4-6",
            system="x",
            messages=[{"role": "user", "content": "y"}],
            tools=[RESPOND_OR_ESCALATE_TOOL],
            tool_choice={"type": "any"},
            max_retries=3,
        )

    assert client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_passes_tool_choice_any() -> None:
    """Verifica que `tool_choice={"type":"any"}` llega al cliente."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_fake_response())

    await call_claude_with_tools(
        client=client,
        model="claude-sonnet-4-6",
        system="x",
        messages=[{"role": "user", "content": "y"}],
        tools=[RESPOND_OR_ESCALATE_TOOL],
        tool_choice={"type": "any"},
        max_retries=1,
    )

    kwargs = client.messages.create.await_args.kwargs
    assert kwargs["tool_choice"] == {"type": "any"}
    assert kwargs["tools"] == [RESPOND_OR_ESCALATE_TOOL]


@pytest.mark.asyncio
async def test_passes_specific_tool_choice() -> None:
    """tool_choice puede forzar una tool específica por nombre."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_fake_response())

    await call_claude_with_tools(
        client=client,
        model="claude-sonnet-4-6",
        system="x",
        messages=[{"role": "user", "content": "y"}],
        tools=[RESPOND_OR_ESCALATE_TOOL],
        tool_choice={"type": "tool", "name": "respond_or_escalate"},
        max_retries=1,
    )

    kwargs = client.messages.create.await_args.kwargs
    assert kwargs["tool_choice"]["type"] == "tool"
    assert kwargs["tool_choice"]["name"] == "respond_or_escalate"


@pytest.mark.asyncio
async def test_no_tool_choice_means_auto() -> None:
    """Si no se pasa tool_choice, no se envía al cliente (Claude decide libre)."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_fake_response())

    await call_claude_with_tools(
        client=client,
        model="claude-sonnet-4-6",
        system="x",
        messages=[{"role": "user", "content": "y"}],
        tools=[RESPOND_OR_ESCALATE_TOOL],
        max_retries=1,
    )

    kwargs = client.messages.create.await_args.kwargs
    assert "tool_choice" not in kwargs


@pytest.mark.asyncio
async def test_passes_multiple_tools() -> None:
    """call_claude_with_tools acepta lista de tools (loop ReAct)."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_fake_response())

    extra_tool = {"name": "shopify_get_order", "description": "x", "input_schema": {}}

    await call_claude_with_tools(
        client=client,
        model="claude-sonnet-4-6",
        system="x",
        messages=[{"role": "user", "content": "y"}],
        tools=[RESPOND_OR_ESCALATE_TOOL, extra_tool],
        tool_choice={"type": "any"},
        max_retries=1,
    )

    kwargs = client.messages.create.await_args.kwargs
    assert len(kwargs["tools"]) == 2


@pytest.mark.asyncio
async def test_cache_false_passes_system_and_tools_untouched() -> None:
    """Sin cache, system (str) y tools pasan tal cual — sin cache_control."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_fake_response())

    await call_claude_with_tools(
        client=client,
        model="claude-sonnet-4-6",
        system="x",
        messages=[{"role": "user", "content": "y"}],
        tools=[RESPOND_OR_ESCALATE_TOOL],
        max_retries=1,
    )

    kwargs = client.messages.create.await_args.kwargs
    assert kwargs["system"] == "x"
    assert "cache_control" not in kwargs["tools"][-1]


@pytest.mark.asyncio
async def test_cache_true_marks_last_tool_and_wraps_system() -> None:
    """Con cache=True: cache_control en la última tool y system (str) → bloque cacheado."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_fake_response())

    extra_tool = {"name": "shopify_get_order", "description": "x", "input_schema": {}}
    await call_claude_with_tools(
        client=client,
        model="claude-sonnet-4-6",
        system="system base",
        messages=[{"role": "user", "content": "y"}],
        tools=[RESPOND_OR_ESCALATE_TOOL, extra_tool],
        max_retries=1,
        cache=True,
    )

    kwargs = client.messages.create.await_args.kwargs
    # última tool marcada, las anteriores no
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in kwargs["tools"][0]
    # system string envuelto en un bloque cacheado
    assert kwargs["system"] == [
        {"type": "text", "text": "system base", "cache_control": {"type": "ephemeral"}}
    ]


@pytest.mark.asyncio
async def test_cache_true_does_not_mutate_caller_tools() -> None:
    """El wrapper copia las tools; no muta la lista del caller."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_fake_response())

    tools = [{"name": "t", "description": "x", "input_schema": {}}]
    await call_claude_with_tools(
        client=client,
        model="claude-sonnet-4-6",
        system="x",
        messages=[{"role": "user", "content": "y"}],
        tools=tools,
        max_retries=1,
        cache=True,
    )

    assert "cache_control" not in tools[0]


@pytest.mark.asyncio
async def test_cache_true_respects_system_blocks_from_caller() -> None:
    """Si system ya es lista de bloques, el wrapper no la re-envuelve (caller manda)."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_fake_response())

    blocks = [
        {"type": "text", "text": "estable", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "dinamico"},
    ]
    await call_claude_with_tools(
        client=client,
        model="claude-sonnet-4-6",
        system=blocks,
        messages=[{"role": "user", "content": "y"}],
        tools=[RESPOND_OR_ESCALATE_TOOL],
        max_retries=1,
        cache=True,
    )

    kwargs = client.messages.create.await_args.kwargs
    assert kwargs["system"] == blocks


@pytest.mark.asyncio
async def test_trace_label_logs_duration_and_cache_breakdown(caplog) -> None:
    """Con trace_label, loguea a INFO una línea con duración + breakdown de cache."""
    client = MagicMock()
    resp = MagicMock()
    resp.content = []
    resp.usage = MagicMock(
        input_tokens=12,
        output_tokens=7,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=2000,
    )
    client.messages.create = AsyncMock(return_value=resp)

    with caplog.at_level(logging.INFO, logger="apps.api.integrations.anthropic_client"):
        await call_claude_with_tools(
            client=client,
            model="claude-sonnet-4-6",
            system="x",
            messages=[{"role": "user", "content": "y"}],
            tools=[RESPOND_OR_ESCALATE_TOOL],
            tool_choice={"type": "any"},
            max_retries=1,
            cache=True,
            trace_label="reason",
        )

    lines = [r.getMessage() for r in caplog.records if "llm_call" in r.getMessage()]
    assert len(lines) == 1
    msg = lines[0]
    assert "label=reason" in msg
    assert "cache_r=2000" in msg
    assert "cache_w=0" in msg
    assert "out=7" in msg
    assert "dur_ms=" in msg


@pytest.mark.asyncio
async def test_no_trace_label_does_not_log(caplog) -> None:
    """Sin trace_label no se emite la línea de instrumentación (callers que no la piden)."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_fake_response())

    with caplog.at_level(logging.INFO, logger="apps.api.integrations.anthropic_client"):
        await call_claude_with_tools(
            client=client,
            model="claude-sonnet-4-6",
            system="x",
            messages=[{"role": "user", "content": "y"}],
            tools=[RESPOND_OR_ESCALATE_TOOL],
            max_retries=1,
        )

    assert not [r for r in caplog.records if "llm_call" in r.getMessage()]


@pytest.mark.asyncio
async def test_trace_label_survives_missing_cache_fields(caplog) -> None:
    """Si el usage no trae campos de cache (respuesta sin caching), loguea 0 sin romper."""
    client = MagicMock()
    resp = MagicMock()
    resp.content = []
    # usage sólo con input/output; sin atributos de cache → cuentan 0.
    resp.usage = MagicMock(spec=["input_tokens", "output_tokens"])
    resp.usage.input_tokens = 30
    resp.usage.output_tokens = 4
    client.messages.create = AsyncMock(return_value=resp)

    with caplog.at_level(logging.INFO, logger="apps.api.integrations.anthropic_client"):
        await call_claude_with_tools(
            client=client,
            model="claude-sonnet-4-6",
            system="x",
            messages=[{"role": "user", "content": "y"}],
            tools=[RESPOND_OR_ESCALATE_TOOL],
            tool_choice={"type": "any"},
            max_retries=1,
            trace_label="supervise",
        )

    lines = [r.getMessage() for r in caplog.records if "llm_call" in r.getMessage()]
    assert len(lines) == 1
    assert "cache_r=0" in lines[0]
    assert "cache_w=0" in lines[0]
    assert "in=30" in lines[0]
