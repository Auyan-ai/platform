"""Reintentos y presupuesto de tiempo de las llamadas a Claude (#389).

SDK real con el transporte HTTP falso (`tests/anthropic_http.py`): el error lo construye
el SDK a partir del código de estado, igual que en producción.
"""

from __future__ import annotations

from collections.abc import Iterator

import anthropic
import pytest
from apps.api.agents.schemas import RESPOND_OR_ESCALATE_TOOL
from apps.api.integrations.anthropic_client import (
    ToolCalled,
    ToolDecision,
    call_claude_for_decision,
)
from apps.api.tests.anthropic_http import (
    ConnectionDrop,
    RecordingAnthropic,
    api_error,
    message,
    overloaded,
    tool_use,
)

RESPOND = {"decision": "respond", "confidence": 0.9, "response_text": "Tardan 3 días."}


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("asyncio.sleep", _sleep)
    yield slept


async def _decide(api: RecordingAnthropic, *, max_retries: int = 3) -> object:
    return await call_claude_for_decision(
        client=api.client,
        model="claude-sonnet-4-6",
        role="default_agent_model",
        system="s",
        messages=[{"role": "user", "content": "¿Cuánto tarda?"}],
        tools=[RESPOND_OR_ESCALATE_TOOL],
        decision=ToolDecision("respond_or_escalate", any_tool=True),
        max_retries=max_retries,
    )


@pytest.mark.asyncio
async def test_overloaded_529_is_retried_and_the_turn_gets_its_decision() -> None:
    api = RecordingAnthropic(overloaded(), message(tool_use("respond_or_escalate", RESPOND)))

    outcome = await _decide(api)

    assert isinstance(outcome, ToolCalled)
    assert outcome.block.input == RESPOND
    assert len(api.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 503, 529])
async def test_transient_statuses_are_retried_up_to_max_retries(status: int) -> None:
    api = RecordingAnthropic(*[api_error(status)] * 3)

    with pytest.raises(anthropic.APIStatusError) as raised:
        await _decide(api, max_retries=3)

    assert raised.value.status_code == status
    assert len(api.requests) == 3


@pytest.mark.asyncio
async def test_dropped_connection_is_retried() -> None:
    api = RecordingAnthropic(
        ConnectionDrop(), ConnectionDrop(), message(tool_use("respond_or_escalate", RESPOND))
    )

    outcome = await _decide(api)

    assert isinstance(outcome, ToolCalled)
    assert len(api.requests) == 3


@pytest.mark.asyncio
async def test_bad_request_is_not_retried() -> None:
    api = RecordingAnthropic(api_error(400))

    with pytest.raises(anthropic.BadRequestError):
        await _decide(api)

    assert len(api.requests) == 1
