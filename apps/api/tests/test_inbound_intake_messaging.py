"""Intake de canales de mensajería (WhatsApp): identidad BSUID/teléfono y sesiones."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from apps.api.db.models import BillingSubscription
from apps.api.services.inbound_intake import persist_and_enqueue_inbound, resolve_end_customer

from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    INBOUND_MSG_ID,
    TENANT_ID,
    make_conversation,
    make_end_customer,
    make_fake_tenant_scope,
    make_message,
)

INTAKE = "apps.api.services.inbound_intake"
JOB_ID = UUID("88888888-8888-8888-8888-888888888888")
NEW_CONV_ID = UUID("99999999-0000-0000-0000-000000000001")
OTHER_CUSTOMER = UUID("33333333-3333-3333-3333-000000000002")
BSUID = "wa:bsuid:ES.123456"
PHONE = "+34600111222"


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "claim_webhook_idempotency_key": AsyncMock(return_value=True),
        "find_end_customer_by_email": AsyncMock(return_value=None),
        "find_end_customer_by_phone": AsyncMock(return_value=None),
        "find_end_customer_by_external_id": AsyncMock(return_value=None),
        "fill_end_customer_identity": AsyncMock(
            side_effect=lambda _c, _t, _id, phone=None, external_id=None: make_end_customer(
                phone=phone or PHONE, external_id=external_id or BSUID
            )
        ),
        "create_end_customer": AsyncMock(return_value=make_end_customer()),
        "find_conversation_by_external": AsyncMock(return_value=None),
        "create_conversation": AsyncMock(
            return_value=make_conversation(id=NEW_CONV_ID, channel="whatsapp")
        ),
        "reopen_if_resolved": AsyncMock(side_effect=lambda _c, _t, conv: conv),
        "get_billing_subscription": AsyncMock(return_value=None),
        "insert_message": AsyncMock(return_value=make_message(id=INBOUND_MSG_ID)),
        "update_conversation_last_message": AsyncMock(),
        "enqueue_inbound_job": AsyncMock(return_value=JOB_ID),
        "lock_inbound_intake": AsyncMock(),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(f"{INTAKE}.{name}", mock)
    monkeypatch.setattr(f"{INTAKE}.tenant_scope", make_fake_tenant_scope())
    return mocks


async def _intake(**overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "channel": "whatsapp",
        "external_id": "zconv-1",
        "idempotency_key": "zernio:evt_1",
        "request_path": "/webhooks/zernio",
        "content": "hola",
        "customer_email": None,
        "customer_name": "Ana",
        "subject": None,
        "message_metadata": {"channel": "whatsapp"},
        "customer_phone": PHONE,
        "customer_external_id": BSUID,
    }
    kwargs.update(overrides)
    return await persist_and_enqueue_inbound(**kwargs)


# ─── Identidad ────────────────────────────────────────────────────────────────


async def test_new_customer_created_with_bsuid_and_phone(db: dict[str, AsyncMock]) -> None:
    await _intake()
    create = db["create_end_customer"].await_args.kwargs
    assert (create["phone"], create["external_id"], create["email"]) == (PHONE, BSUID, None)
    assert db["lock_inbound_intake"].await_args.kwargs["customer_phone"] == PHONE
    assert db["lock_inbound_intake"].await_args.kwargs["customer_external_id"] == BSUID


async def test_only_bsuid_creates_customer_without_phone(db: dict[str, AsyncMock]) -> None:
    await _intake(customer_phone=None)
    create = db["create_end_customer"].await_args.kwargs
    assert (create["phone"], create["external_id"]) == (None, BSUID)
    db["find_end_customer_by_phone"].assert_not_awaited()


async def test_only_phone_creates_customer_without_external_id(db: dict[str, AsyncMock]) -> None:
    await _intake(customer_external_id=None)
    create = db["create_end_customer"].await_args.kwargs
    assert (create["phone"], create["external_id"]) == (PHONE, None)
    db["find_end_customer_by_external_id"].assert_not_awaited()


async def test_bsuid_match_wins(db: dict[str, AsyncMock]) -> None:
    db["find_end_customer_by_external_id"].return_value = make_end_customer(
        external_id=BSUID, phone=PHONE
    )
    await _intake()
    db["create_end_customer"].assert_not_awaited()
    db["find_end_customer_by_phone"].assert_not_awaited()
    db["fill_end_customer_identity"].assert_not_awaited()


async def test_phone_match_gets_bsuid_attached(db: dict[str, AsyncMock]) -> None:
    """Cliente conocido por teléfono (p. ej. de Zendesk) que ahora escribe con BSUID."""
    db["find_end_customer_by_phone"].side_effect = [
        make_end_customer(phone=PHONE, external_id=None),
    ]
    await _intake()
    db["create_end_customer"].assert_not_awaited()
    fill = db["fill_end_customer_identity"].await_args
    assert fill.kwargs == {"phone": None, "external_id": BSUID}


async def test_bsuid_customer_gets_phone_when_nobody_else_has_it(
    db: dict[str, AsyncMock],
) -> None:
    db["find_end_customer_by_external_id"].side_effect = [
        make_end_customer(external_id=BSUID, phone=None),
        None,
    ]
    await _intake()
    assert db["fill_end_customer_identity"].await_args.kwargs == {
        "phone": PHONE,
        "external_id": None,
    }


async def test_phone_owned_by_other_customer_is_not_reassigned(
    db: dict[str, AsyncMock],
) -> None:
    db["find_end_customer_by_external_id"].return_value = make_end_customer(
        external_id=BSUID, phone=None
    )
    db["find_end_customer_by_phone"].return_value = make_end_customer(
        id=OTHER_CUSTOMER, phone=PHONE
    )
    customer = await resolve_end_customer(
        AsyncMock(),
        tenant_id=TENANT_ID,
        email=None,
        phone=PHONE,
        external_id=BSUID,
        full_name=None,
    )
    assert customer.id == CUSTOMER_ID
    db["fill_end_customer_identity"].assert_not_awaited()


# ─── Sesiones ─────────────────────────────────────────────────────────────────


async def test_live_session_is_reused(db: dict[str, AsyncMock]) -> None:
    db["find_conversation_by_external"].return_value = make_conversation(
        channel="whatsapp", external_id="zconv-1", status="open"
    )
    result = await _intake()
    assert result.conversation_id == CONVERSATION_ID
    db["create_conversation"].assert_not_awaited()


async def test_recently_resolved_session_is_reopened(db: dict[str, AsyncMock]) -> None:
    db["find_conversation_by_external"].return_value = make_conversation(
        channel="whatsapp",
        external_id="zconv-1",
        status="resolved",
        resolved_at=datetime.now(UTC) - timedelta(days=2),
    )
    result = await _intake()
    assert result.conversation_id == CONVERSATION_ID
    db["reopen_if_resolved"].assert_awaited_once()
    db["create_conversation"].assert_not_awaited()


async def test_old_resolved_session_starts_new_conversation(db: dict[str, AsyncMock]) -> None:
    db["find_conversation_by_external"].return_value = make_conversation(
        channel="whatsapp",
        external_id="zconv-1",
        status="resolved",
        resolved_at=datetime.now(UTC) - timedelta(days=10),
    )
    result = await _intake()
    assert result.conversation_id == NEW_CONV_ID
    db["reopen_if_resolved"].assert_not_awaited()


async def test_reopen_window_comes_from_billing_subscription(db: dict[str, AsyncMock]) -> None:
    db["get_billing_subscription"].return_value = BillingSubscription(
        tenant_id=TENANT_ID,
        tier="starter",
        floor_cents=0,
        included_resolutions=0,
        overage_cents=0,
        currency="eur",
        reopen_window_days=14,
        period_anchor_day=1,
        status="active",
    )
    db["find_conversation_by_external"].return_value = make_conversation(
        channel="whatsapp",
        external_id="zconv-1",
        status="resolved",
        resolved_at=datetime.now(UTC) - timedelta(days=10),
    )
    result = await _intake()
    assert result.conversation_id == CONVERSATION_ID


@pytest.mark.parametrize("status", ["closed", "closed_abandoned"])
async def test_closed_session_starts_new_conversation(
    db: dict[str, AsyncMock], status: str
) -> None:
    db["find_conversation_by_external"].return_value = make_conversation(
        channel="whatsapp", external_id="zconv-1", status=status
    )
    result = await _intake()
    assert result.conversation_id == NEW_CONV_ID


async def test_helpdesk_closed_conversation_is_not_split(db: dict[str, AsyncMock]) -> None:
    """Los helpdesks no tienen sesiones: un ticket = una conversación, como antes."""
    db["find_conversation_by_external"].return_value = make_conversation(
        channel="zendesk", external_id="42", status="closed"
    )
    result = await _intake(channel="zendesk", external_id="42")
    assert result.conversation_id == CONVERSATION_ID
    db["create_conversation"].assert_not_awaited()
    db["get_billing_subscription"].assert_not_awaited()
