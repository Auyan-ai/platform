from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from apps.api.db.models import OutboundEmailJob
from apps.api.services.outbound_email_dispatcher import (
    dispatch_due_outbound_emails,
    postmark_message_id,
    retry_delay_seconds,
)

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
JOB_ID = UUID("22222222-2222-2222-2222-222222222222")


def _job(*, attempts: int = 1, max_attempts: int = 3) -> OutboundEmailJob:
    return OutboundEmailJob(
        id=JOB_ID,
        tenant_id=TENANT_ID,
        recipient_email="ops@acme.test",
        subject="Auyan update",
        text_body="Texto",
        html_body="<p>Texto</p>",
        tag="ops",
        payload={},
        status="sending",
        attempts=attempts,
        max_attempts=max_attempts,
        next_attempt_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_retry_delay_uses_exponential_backoff_with_cap() -> None:
    assert retry_delay_seconds(_job(attempts=1)) == 60
    assert retry_delay_seconds(_job(attempts=3)) == 240
    assert retry_delay_seconds(_job(attempts=12)) == 3600


def test_postmark_message_id_accepts_both_casings() -> None:
    assert postmark_message_id({"MessageID": "a"}) == "a"
    assert postmark_message_id({"MessageId": "b"}) == "b"
    assert postmark_message_id({}) is None


@pytest.mark.asyncio
async def test_dispatch_sends_claimed_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    claim_mock = AsyncMock(return_value=[_job()])
    mark_sent = AsyncMock(return_value=_job())
    mark_failed = AsyncMock()
    monkeypatch.setattr(
        "apps.api.services.outbound_email_dispatcher.claim_due_outbound_email_jobs",
        claim_mock,
    )
    monkeypatch.setattr(
        "apps.api.services.outbound_email_dispatcher.mark_outbound_email_job_sent",
        mark_sent,
    )
    monkeypatch.setattr(
        "apps.api.services.outbound_email_dispatcher.mark_outbound_email_job_failed",
        mark_failed,
    )
    email_sender = AsyncMock()
    email_sender.send_email_now = AsyncMock(return_value={"MessageID": "pm-123"})

    result = await dispatch_due_outbound_emails(AsyncMock(), email_sender, limit=10)

    assert result.claimed == 1
    assert result.sent == 1
    assert result.retry_scheduled == 0
    assert result.failed == 0
    claim_mock.assert_awaited_once()
    email_sender.send_email_now.assert_awaited_once_with(
        to="ops@acme.test",
        subject="Auyan update",
        text_body="Texto",
        html_body="<p>Texto</p>",
        tag="ops",
    )
    assert mark_sent.await_args.kwargs["postmark_message_id"] == "pm-123"
    mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_schedules_retry_on_send_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_mock = AsyncMock(return_value=[_job(attempts=1, max_attempts=3)])
    mark_failed = AsyncMock(return_value=_job(attempts=1, max_attempts=3))
    monkeypatch.setattr(
        "apps.api.services.outbound_email_dispatcher.claim_due_outbound_email_jobs",
        claim_mock,
    )
    monkeypatch.setattr(
        "apps.api.services.outbound_email_dispatcher.mark_outbound_email_job_sent",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "apps.api.services.outbound_email_dispatcher.mark_outbound_email_job_failed",
        mark_failed,
    )
    email_sender = AsyncMock()
    email_sender.send_email_now = AsyncMock(side_effect=RuntimeError("postmark down"))

    result = await dispatch_due_outbound_emails(AsyncMock(), email_sender)

    assert result.claimed == 1
    assert result.sent == 0
    assert result.retry_scheduled == 1
    assert result.failed == 0
    assert mark_failed.await_args.kwargs["retry_delay_seconds"] == 60
    assert mark_failed.await_args.kwargs["error"] == "postmark down"


@pytest.mark.asyncio
async def test_dispatch_counts_terminal_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    terminal_job = _job(attempts=3, max_attempts=3)
    terminal_job = terminal_job.model_copy(update={"status": "failed"})
    monkeypatch.setattr(
        "apps.api.services.outbound_email_dispatcher.claim_due_outbound_email_jobs",
        AsyncMock(return_value=[_job(attempts=3, max_attempts=3)]),
    )
    monkeypatch.setattr(
        "apps.api.services.outbound_email_dispatcher.mark_outbound_email_job_sent",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "apps.api.services.outbound_email_dispatcher.mark_outbound_email_job_failed",
        AsyncMock(return_value=terminal_job),
    )
    email_sender = AsyncMock()
    email_sender.send_email_now = AsyncMock(side_effect=RuntimeError("still down"))

    result = await dispatch_due_outbound_emails(AsyncMock(), email_sender)

    assert result.claimed == 1
    assert result.retry_scheduled == 0
    assert result.failed == 1
