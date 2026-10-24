"""Reintentos y presupuesto de tiempo de las llamadas a Claude (#389).

SDK real con el transporte HTTP falso (`tests/anthropic_http.py`): el error lo construye
el SDK a partir del código de estado, igual que en producción.
"""

from __future__ import annotations

from collections.abc import Iterator

import anthropic
import pytest
from apps.api.agents.schemas import RESPOND_OR_ESCALATE_TOOL
from apps.api.core.config import LLM_CALL_BUDGET_SECONDS, Settings
from apps.api.integrations.anthropic_client import (
    ToolCalled,
    ToolDecision,
    build_anthropic_client,
    call_claude_for_decision,
    call_claude_text,
)
from apps.api.tests.anthropic_http import (
    ConnectionDrop,
    RecordingAnthropic,
    api_error,
    message,
    overloaded,
    text,
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


@pytest.mark.asyncio
async def test_text_calls_retry_an_overload_too() -> None:
    api = RecordingAnthropic(overloaded(), message(text("hola"), stop_reason="end_turn"))

    reply = await call_claude_text(
        client=api.client,
        role="judge_sonnet_model",
        system="s",
        messages=[{"role": "user", "content": "m"}],
        max_tokens=100,
    )

    assert reply.text == "hola"
    assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_the_production_client_does_not_retry_on_its_own() -> None:
    """Una sola capa de reintentos: con `max_retries=1` sale una petición, no tres."""
    api = RecordingAnthropic(*[overloaded()] * 3, base=build_anthropic_client("test-key"))

    with pytest.raises(anthropic.APIStatusError):
        await _decide(api, max_retries=1)

    assert len(api.requests) == 1


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_retries_stay_inside_the_call_budget(
    monkeypatch: pytest.MonkeyPatch, _no_backoff: list[float]
) -> None:
    """Cada intento tarda 40 s en devolver un 529. Con 60 s por intento y un presupuesto de
    90 s, el segundo intento se corta a lo que queda y el tercero no cabe entero."""
    clock = _Clock()
    monkeypatch.setattr("apps.api.integrations.anthropic_client.time.monotonic", clock)

    async def _sleep(seconds: float) -> None:
        _no_backoff.append(seconds)
        clock.now += seconds

    monkeypatch.setattr("asyncio.sleep", _sleep)

    def _slow_api(read_timeout: float | None) -> None:
        clock.now += min(40, read_timeout or 40)

    api = RecordingAnthropic(*[overloaded()] * 3, on_request=_slow_api)

    with pytest.raises(anthropic.APIStatusError):
        await call_claude_for_decision(
            client=api.client,
            model="claude-sonnet-4-6",
            role="default_agent_model",
            system="s",
            messages=[{"role": "user", "content": "m"}],
            tools=[RESPOND_OR_ESCALATE_TOOL],
            decision=ToolDecision("respond_or_escalate", any_tool=True),
            max_retries=3,
            timeout_seconds=60,
        )

    assert api.read_timeouts == [60, 49, 7]
    assert _no_backoff == [1, 2]
    assert clock.now - 1000.0 <= LLM_CALL_BUDGET_SECONDS


@pytest.mark.asyncio
async def test_retry_after_from_the_api_is_honoured(_no_backoff: list[float]) -> None:
    api = RecordingAnthropic(
        api_error(429, **{"retry-after": "7"}), message(tool_use("respond_or_escalate", RESPOND))
    )

    await _decide(api)

    assert _no_backoff == [7.0]


def test_the_call_budget_fits_inside_the_inbound_worker_lease() -> None:
    lease = Settings.model_fields["inbound_worker_lease_seconds"].default
    assert LLM_CALL_BUDGET_SECONDS < lease


def test_settings_reject_a_lease_shorter_than_the_call_budget() -> None:
    with pytest.raises(ValueError, match="inbound_worker_lease_seconds"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            database_url="postgresql://u:p@localhost:5432/db",
            supabase_url="https://x.supabase.co",
            supabase_service_role_key="k",
            supabase_anon_key="k",
            anthropic_api_key="k",
            openai_api_key="k",
            webhook_secret="k",
            inbound_worker_lease_seconds=int(LLM_CALL_BUDGET_SECONDS),
        )
