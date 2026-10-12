"""Punto 1 y 4 del mini-sprint (E2E pedido #1429).

1. get_order_status devuelve el pedido, con la dirección de envío, SOLO si quien
   escribe es el dueño (email o teléfono verificados del remitente). Si no, responde
   igual que a un pedido inexistente (ADR 0013).
4. update_shipping_address acepta address2 (piso/puerta/portal).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from apps.api.agents.nodes import execute_skill
from apps.api.integrations.base import IntegrationContext
from apps.api.skills.base import SkillContext
from apps.api.skills.shopify.get_order_status import (
    NOT_FOUND_NOTE,
    GetOrderStatus,
    GetOrderStatusInput,
)
from apps.api.skills.shopify.update_shipping_address import (
    UpdateShippingAddress,
    UpdateShippingAddressInput,
)
from apps.api.tests.conftest import TENANT_ID
from apps.api.tests.identity_support import identity_state, patch_commerce
from apps.api.tests.order_snapshots import snapshot

_ORDER: dict[str, Any] = {
    "id": 7404799197464,
    "name": "#1429",
    "email": "Kenny.Medina@ahoracrypto.com",
    "financial_status": "paid",
    "fulfillment_status": None,
    "total_price": "49.90",
    "currency": "EUR",
    "created_at": "2026-09-29T20:40:00Z",
    "fulfillments": [],
    "line_items": [],
    "shipping_address": {
        "first_name": "Kenny",
        "address1": "Calle de Serrano 1",
        "address2": None,
        "city": "Madrid",
        "zip": "28001",
        "province": "Madrid",
        "country": "Spain",
        "phone": "+34600123456",
    },
}


def _ctx(customer_email: str | None, mock: Any, **extra: Any) -> SkillContext:
    return SkillContext(
        tenant_id=str(TENANT_ID),
        conversation_id="c",
        integration_ctx=IntegrationContext(tenant_id=TENANT_ID, credentials={}, config={}),
        commerce_mock=mock,
        customer_email=customer_email,
        **extra,
    )


async def _status(customer_email: str | None, **extra: Any) -> Any:
    mock = AsyncMock()
    mock.get_order_by_name = AsyncMock(return_value=_ORDER)
    return await GetOrderStatus().execute(
        _ctx(customer_email, mock, **extra), GetOrderStatusInput(order_identifier="#1429")
    )


@pytest.mark.asyncio
async def test_owner_sees_shipping_address() -> None:
    out = await _status(" kenny.medina@AHORACRYPTO.com ")
    assert out.found is True
    assert out.shipping_address is not None
    assert out.shipping_address.address1 == "Calle de Serrano 1"
    assert out.shipping_address.zip == "28001"
    # Solo campos de dirección: ni teléfono ni nombre.
    assert "phone" not in out.shipping_address.model_dump()


@pytest.mark.parametrize(
    ("email", "phone", "channel"),
    [
        ("otro@example.com", None, "zendesk"),
        (None, None, "zendesk"),
        (None, "+34610637711", "whatsapp"),
    ],
    ids=["email_ajeno", "sin_remitente", "whatsapp_otro_telefono"],
)
@pytest.mark.asyncio
async def test_non_owner_is_stopped_by_the_gate(
    monkeypatch: pytest.MonkeyPatch, email: str | None, phone: str | None, channel: str
) -> None:
    """ADR 0013: a quien no es dueño no se le da el pedido ni se le dice si existe."""
    mock = AsyncMock()
    mock.get_order_by_name = AsyncMock(return_value=_ORDER)
    patch_commerce(monkeypatch, mock)
    state = identity_state(email=email, phone=phone, channel=channel)
    blocked = await execute_skill._identity_gate(state, GetOrderStatus, {"order_identifier": "1429"})
    assert blocked is not None and blocked[0] == "identity_required"


@pytest.mark.asyncio
async def test_owner_passes_the_gate_with_any_case_of_the_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = AsyncMock()
    mock.get_order_by_name = AsyncMock(return_value=_ORDER)
    patch_commerce(monkeypatch, mock)
    state = identity_state(email=" kenny.medina@AHORACRYPTO.com ")
    assert await execute_skill._identity_gate(state, GetOrderStatus, {"order_identifier": "1429"}) is None


@pytest.mark.asyncio
async def test_order_that_vanishes_after_the_gate_answers_not_found() -> None:
    mock = AsyncMock()
    mock.get_order_by_name = AsyncMock(return_value=None)
    out = await GetOrderStatus().execute(
        _ctx("kenny.medina@ahoracrypto.com", mock), GetOrderStatusInput(order_identifier="#1429")
    )
    assert (out.found, out.order_id, out.shipping_address) == (False, None, None)
    assert out.note == NOT_FOUND_NOTE


@pytest.mark.asyncio
async def test_update_shipping_address_sends_address2() -> None:
    mock = AsyncMock()
    mock.update_shipping_address = AsyncMock(return_value={"id": 7404799197464})
    mock.get_order_snapshot = AsyncMock(
        side_effect=[
            snapshot(order_id=7404799197464),
            snapshot(
                order_id=7404799197464,
                address={
                    "address1": "Calle José Hierro, 18",
                    "address2": "Portal 5, 1ºA",
                    "city": "San Sebastián de los Reyes",
                    "zip": "28702",
                    "country": "Spain",
                },
            ),
        ]
    )
    out = await UpdateShippingAddress().execute(
        _ctx(None, mock),
        UpdateShippingAddressInput(
            order_id=7404799197464,
            address1="Calle José Hierro, 18",
            address2="Portal 5, 1ºA",
            city="San Sebastián de los Reyes",
            province="Madrid",
            zip_code="28702",
        ),
    )
    assert mock.update_shipping_address.await_args.kwargs["address2"] == "Portal 5, 1ºA"
    assert out.new_address2 == "Portal 5, 1ºA"
    assert out.new_zip == "28702"
