"""Tests del retry behavior de `call_claude_with_tool`.

Verifica que tenacity reintenta sólo errores transitorios y que respeta `max_retries`.
Parchea `asyncio.sleep` para que el test sea instantáneo en lugar de esperar
los backoffs reales.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest

from apps.api.agents.schemas import RESPOND_OR_ESCALATE_TOOL
from apps.api.integrations.anthropic_client import call_claude_with_tool


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
    """Mock con la forma mínima que call_claude_with_tool espera devolver."""
    resp = MagicMock()
    resp.content = []
    resp.usage = MagicMock(input_tokens=10, output_tokens=5)
    return resp


@pytest.mark.asyncio
async def test_succeeds_on_first_attempt() -> None:
    client = MagicMock()
    fake_resp = _fake_response()
    client.messages.create = AsyncMock(return_value=fake_resp)

    result = await call_claude_with_tool(
        client=client,
        model="claude-sonnet-4-6",
        system="x",
        messages=[{"role": "user", "content": "y"}],
        tool=RESPOND_OR_ESCALATE_TOOL,
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

    result = await call_claude_with_tool(
        client=client,
        model="claude-sonnet-4-6",
        system="x",
        messages=[{"role": "user", "content": "y"}],
        tool=RESPOND_OR_ESCALATE_TOOL,
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
        await call_claude_with_tool(
            client=client,
            model="claude-sonnet-4-6",
            system="x",
            messages=[{"role": "user", "content": "y"}],
            tool=RESPOND_OR_ESCALATE_TOOL,
            max_retries=3,
        )

    assert client.messages.create.await_count == 3


@pytest.mark.asyncio
async def test_does_not_retry_non_transient_errors() -> None:
    """`anthropic.BadRequestError` (4xx) no es retryable — falla al primer intento."""
    client = MagicMock()
    # BadRequestError no está en RETRYABLE_ERRORS
    bad_request = anthropic.BadRequestError(
        message="invalid request",
        response=MagicMock(status_code=400, headers={}),
        body=None,
    )
    client.messages.create = AsyncMock(side_effect=bad_request)

    with pytest.raises(anthropic.BadRequestError):
        await call_claude_with_tool(
            client=client,
            model="claude-sonnet-4-6",
            system="x",
            messages=[{"role": "user", "content": "y"}],
            tool=RESPOND_OR_ESCALATE_TOOL,
            max_retries=3,
        )

    # Sólo un intento — no retries en 4xx
    assert client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_forces_tool_choice() -> None:
    """Verifica que enviamos tool_choice=forced (no opcional) para garantizar tool use."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_fake_response())

    await call_claude_with_tool(
        client=client,
        model="claude-sonnet-4-6",
        system="x",
        messages=[{"role": "user", "content": "y"}],
        tool=RESPOND_OR_ESCALATE_TOOL,
        max_retries=1,
    )

    kwargs = client.messages.create.await_args.kwargs
    assert kwargs["tool_choice"]["type"] == "tool"
    assert kwargs["tool_choice"]["name"] == "respond_or_escalate"
