"""Punto 1 y 4 del mini-sprint (E2E pedido #1429).

1. get_order_status devuelve la dirección de envío SOLO si quien escribe es el
   dueño del pedido (email del cliente == email del pedido). Si no, la retiene.
4. update_shipping_address acepta address2 (piso/puerta/portal).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.skills.base import SkillContext
from apps.api.skills.shopify.get_order_status import GetOrderStatus, GetOrderStatusInput
from apps.api.skills.shopify.update_shipping_address import (
    UpdateShippingAddress,
    UpdateShippingAddressInput,
)
from apps.api.tests.conftest import TENANT_ID

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


def _ctx(customer_email: str | None, mock: Any) -> SkillContext:
    return SkillContext(
        tenant_id=str(TENANT_ID),
        conversation_id="c",
        integration_ctx=IntegrationContext(tenant_id=TENANT_ID, credentials={}, config={}),
        commerce_mock=mock,
        customer_email=customer_email,
    )


async def _status(customer_email: str | None) -> Any:
    mock = AsyncMock()
    mock.get_order_by_name = AsyncMock(return_value=_ORDER)
    return await GetOrderStatus().execute(
        _ctx(customer_email, mock), GetOrderStatusInput(order_identifier="#1429")
    )


@pytest.mark.asyncio
async def test_owner_sees_shipping_address() -> None:
    out = await _status(" kenny.medina@AHORACRYPTO.com ")
    assert out.shipping_address is not None
    assert out.shipping_address.address1 == "Calle de Serrano 1"
    assert out.shipping_address.zip == "28001"
    assert out.shipping_address_withheld is False
    # Solo campos de dirección: ni teléfono ni nombre.
    assert "phone" not in out.shipping_address.model_dump()


@pytest.mark.parametrize("email", ["otro@example.com", None])
@pytest.mark.asyncio
async def test_non_owner_gets_address_withheld(email: str | None) -> None:
    out = await _status(email)
    assert out.shipping_address is None
    assert out.shipping_address_withheld is True
    assert out.found is True


@pytest.mark.asyncio
async def test_update_shipping_address_sends_address2() -> None:
    mock = AsyncMock()
    mock.update_shipping_address = AsyncMock(
        return_value={
            "id": 7404799197464,
            "shipping_address": {
                "address1": "Calle José Hierro, 18",
                "address2": "Portal 5, 1ºA",
                "city": "San Sebastián de los Reyes",
                "zip": "28702",
                "country": "Spain",
            },
        }
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
