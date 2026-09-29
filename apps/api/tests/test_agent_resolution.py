"""Tests de la resolución autónoma condicionada a la entrega outbound.

Bug de la auditoría s71 (#3): `respond` marcaba `resolved` (y cobraba la
resolución) aunque `send_outbound` fallara → cliente sin respuesta, ticket
cerrado y resolución facturada. Ahora solo se resuelve tras confirmar entrega.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import ANY, AsyncMock

import pytest
from apps.api.services import agent_resolution
from apps.api.tests.conftest import (
    CONVERSATION_ID,
    TENANT_ID,
    make_conversation,
    make_fake_tenant_scope,
)

MODULE = "apps.api.services.agent_resolution"


class _Adapter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str]] = []

    async def send_outbound(self, ctx: Any, ref: str, content: str) -> None:
        if self.fail:
            raise RuntimeError("helpdesk down")
        self.sent.append((ref, content))


@pytest.fixture
def db_mocks(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "mark": AsyncMock(return_value=True),
        "event": AsyncMock(),
        "close": AsyncMock(return_value=True),
    }
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.mark_conversation_resolved", mocks["mark"])
    monkeypatch.setattr(f"{MODULE}.insert_resolution_event", mocks["event"])
    monkeypatch.setattr(f"{MODULE}.close_external_helpdesk_ticket_safe", mocks["close"])
    return mocks


class TestSendAgentReply:
    @pytest.mark.asyncio
    async def test_returns_true_when_delivered(self) -> None:
        adapter = _Adapter()
        ok = await agent_resolution.send_agent_reply(
            adapter, None, "10", "hola", tenant_id=TENANT_ID, provider="zendesk"
        )
        assert ok is True
        assert adapter.sent == [("10", "hola")]

    @pytest.mark.asyncio
    async def test_returns_false_and_logs_on_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        ok = await agent_resolution.send_agent_reply(
            _Adapter(fail=True), None, "10", "hola", tenant_id=TENANT_ID, provider="zendesk"
        )
        assert ok is False
        assert "agent_reply_delivery_failed" in caplog.text


class TestFinalizeAgentResolution:
    @pytest.mark.asyncio
    async def test_delivered_marks_resolved_bills_and_closes(
        self, db_mocks: dict[str, AsyncMock]
    ) -> None:
        conversation = make_conversation()
        resolved = await agent_resolution.finalize_agent_resolution(
            tenant_id=TENANT_ID, conversation=conversation, delivered=True, settings=ANY
        )

        assert resolved is True
        db_mocks["mark"].assert_awaited_once_with(ANY, TENANT_ID, CONVERSATION_ID)
        db_mocks["event"].assert_awaited_once_with(ANY, TENANT_ID, CONVERSATION_ID)
        db_mocks["close"].assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_delivered_does_not_resolve_bill_or_close(
        self, db_mocks: dict[str, AsyncMock], caplog: pytest.LogCaptureFixture
    ) -> None:
        resolved = await agent_resolution.finalize_agent_resolution(
            tenant_id=TENANT_ID, conversation=make_conversation(), delivered=False, settings=ANY
        )

        assert resolved is False
        db_mocks["mark"].assert_not_awaited()
        db_mocks["event"].assert_not_awaited()
        db_mocks["close"].assert_not_awaited()
        assert "agent_resolution_blocked_undelivered" in caplog.text

    @pytest.mark.asyncio
    async def test_already_resolved_does_not_double_bill(
        self, db_mocks: dict[str, AsyncMock]
    ) -> None:
        """mark_conversation_resolved=False (ya cerrada/escalada) → ni evento ni cierre."""
        db_mocks["mark"].return_value = False
        resolved = await agent_resolution.finalize_agent_resolution(
            tenant_id=TENANT_ID, conversation=make_conversation(), delivered=True, settings=ANY
        )

        assert resolved is False
        db_mocks["event"].assert_not_awaited()
        db_mocks["close"].assert_not_awaited()
