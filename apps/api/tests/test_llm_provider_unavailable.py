"""Caída total de Anthropic (saldo agotado, 401, 403): clasificación, alerta, escalado, doctor."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.nodes.handle_error import make_handle_error_node
from apps.api.integrations.anthropic_client import (
    LLMProviderUnavailable,
    call_claude_with_tools,
    classify_provider_error,
)
from apps.api.services.doctor.live import llm_provider_check
from apps.api.services.llm_alert import LLMProviderAlerter, configure_alerter

from tests.conftest import (
    CONVERSATION_ID,
    TENANT_ID,
    make_escalation,
    make_fake_tenant_scope,
)

_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls: type[anthropic.APIStatusError], status: int, message: str):
    response = httpx.Response(status, request=_REQUEST)
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    return cls(message, response=response, body=body)


def _credit_error() -> anthropic.BadRequestError:
    return _status_error(
        anthropic.BadRequestError,
        400,
        "Your credit balance is too low to access the Anthropic API.",
    )


def _auth_error() -> anthropic.AuthenticationError:
    return _status_error(anthropic.AuthenticationError, 401, "invalid x-api-key")


def _permission_error() -> anthropic.PermissionDeniedError:
    return _status_error(anthropic.PermissionDeniedError, 403, "forbidden")


@pytest.fixture(autouse=True)
def _reset_alerter():
    yield
    configure_alerter(None)


class TestClassification:
    @pytest.mark.parametrize(
        ("exc", "reason"),
        [
            (_credit_error(), "credit_balance_exhausted"),
            (_auth_error(), "authentication_failed"),
            (_permission_error(), "permission_denied"),
        ],
    )
    def test_total_outage_errors(self, exc, reason) -> None:
        assert classify_provider_error(exc) == reason

    def test_other_bad_request_is_not_an_outage(self) -> None:
        exc = _status_error(anthropic.BadRequestError, 400, "max_tokens: must be positive")
        assert classify_provider_error(exc) is None

    def test_rate_limit_and_server_errors_are_not_an_outage(self) -> None:
        assert classify_provider_error(_status_error(anthropic.RateLimitError, 429, "slow")) is None
        assert (
            classify_provider_error(_status_error(anthropic.InternalServerError, 500, "boom"))
            is None
        )


class TestCallWrapper:
    @pytest.mark.asyncio
    async def test_credit_error_raises_unavailable_without_retrying(self) -> None:
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=_credit_error())

        with pytest.raises(LLMProviderUnavailable) as info:
            await call_claude_with_tools(
                client=client, model="m", system="s", messages=[], tools=[{"name": "t"}]
            )

        assert info.value.reason == "credit_balance_exhausted"
        assert info.value.status_code == 400
        assert client.messages.create.await_count == 1

    @pytest.mark.asyncio
    async def test_other_4xx_keeps_raising_the_sdk_error(self) -> None:
        client = MagicMock()
        client.messages.create = AsyncMock(
            side_effect=_status_error(anthropic.BadRequestError, 400, "bad schema")
        )

        with pytest.raises(anthropic.BadRequestError):
            await call_claude_with_tools(
                client=client, model="m", system="s", messages=[], tools=[{"name": "t"}]
            )


class _FakeSender:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self._fail = fail

    async def send_email_now(self, **kwargs):
        if self._fail:
            raise RuntimeError("postmark down")
        self.sent.append(kwargs)
        return {"MessageID": "x"}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def _report(alerter: LLMProviderAlerter) -> bool:
    return await alerter.report(
        reason="credit_balance_exhausted",
        status_code=400,
        detail="credit balance too low",
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
    )


class TestAlerter:
    @pytest.mark.asyncio
    async def test_sends_one_email_per_hour_and_logs_every_time(self, caplog) -> None:
        sender, clock = _FakeSender(), _Clock()
        alerter = LLMProviderAlerter(sender, "ops@example.com", clock=clock)

        with caplog.at_level(logging.ERROR):
            assert await _report(alerter) is True
            assert await _report(alerter) is False
            clock.now += 3599
            assert await _report(alerter) is False
            clock.now += 2
            assert await _report(alerter) is True

        assert len(sender.sent) == 2
        assert sender.sent[0]["to"] == "ops@example.com"
        assert "credit_balance_exhausted" in sender.sent[0]["subject"]
        errors = [
            r for r in caplog.records if r.getMessage().startswith("llm_provider_unavailable")
        ]
        assert len(errors) == 4
        assert errors[0].category == "llm_provider_unavailable"

    @pytest.mark.asyncio
    async def test_failed_send_does_not_burn_the_hour(self, caplog) -> None:
        sender = _FakeSender(fail=True)
        alerter = LLMProviderAlerter(sender, "ops@example.com", clock=_Clock())
        assert await _report(alerter) is False
        sender._fail = False
        assert await _report(alerter) is True

    @pytest.mark.asyncio
    async def test_without_recipient_logs_and_does_not_send(self, caplog) -> None:
        sender = _FakeSender()
        alerter = LLMProviderAlerter(sender, None, clock=_Clock())
        with caplog.at_level(logging.ERROR):
            assert await _report(alerter) is False
        assert sender.sent == []
        assert any("alert_not_sent" in r.getMessage() for r in caplog.records)


class TestGuardAndEscalation:
    @pytest.mark.asyncio
    async def test_guard_alerts_once_across_turns_and_sets_categorized_error(self) -> None:
        sender = _FakeSender()
        configure_alerter(LLMProviderAlerter(sender, "ops@example.com", clock=_Clock()))

        @guarded(name="reason")
        async def node(state):  # type: ignore[no-untyped-def]
            raise LLMProviderUnavailable("authentication_failed", status_code=401, detail="x")

        state = {"tenant_id": str(TENANT_ID), "conversation_id": str(CONVERSATION_ID)}
        first = await node(state)
        second = await node(state)

        assert first["error"].startswith("llm_provider_unavailable: authentication_failed")
        assert second == first
        assert len(sender.sent) == 1

    @pytest.mark.asyncio
    async def test_handle_error_escalates_with_explicit_reason(
        self, fake_deps, monkeypatch
    ) -> None:
        module = "apps.api.agents.nodes.handle_error"
        insert_mock = AsyncMock(return_value=make_escalation())
        monkeypatch.setattr(f"{module}.tenant_scope", make_fake_tenant_scope())
        monkeypatch.setattr(
            f"{module}.get_open_escalation_for_conversation", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(f"{module}.insert_escalation", insert_mock)
        monkeypatch.setattr(f"{module}.update_conversation_status", AsyncMock())
        node = make_handle_error_node(fake_deps)

        out = await node(
            {
                "tenant_id": str(TENANT_ID),
                "conversation_id": str(CONVERSATION_ID),
                "error": "llm_provider_unavailable: credit_balance_exhausted (node reason)",
            }
        )

        assert insert_mock.await_args.kwargs["reason"].startswith("llm_provider_unavailable:")
        assert out["escalation_created"] is True
        assert out["escalation_reason"].startswith("llm_provider_unavailable:")


class TestDoctorCheck:
    @pytest.mark.asyncio
    async def test_ok_when_minimal_call_succeeds(self) -> None:
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=MagicMock())
        check = await llm_provider_check(client, "claude-haiku-4-5-20251001")
        assert check.status == "ok"
        kwargs = client.messages.create.await_args.kwargs
        assert kwargs["max_tokens"] == 1
        assert "tools" not in kwargs

    @pytest.mark.asyncio
    async def test_fail_on_exhausted_balance(self) -> None:
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=_credit_error())
        check = await llm_provider_check(client, "m")
        assert check.status == "fail"
        assert "credit_balance_exhausted" in check.detail
        assert check.hint

    @pytest.mark.asyncio
    async def test_warn_when_anthropic_is_unreachable(self) -> None:
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=httpx.ConnectError("no route"))
        check = await llm_provider_check(client, "m")
        assert check.status == "warn"
