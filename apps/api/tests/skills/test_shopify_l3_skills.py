"""Tests para las skills L3 de Shopify: cancel_order, update_shipping_address,
refund_partial, start_return.

ShopifyClient mockeado con AsyncMock — sin llamadas HTTP reales.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from apps.api.skills.base import SkillContext
from apps.api.skills.shopify.cancel_order import (
    CancelOrder,
    CancelOrderInput,
    CancelOrderOutput,
)
from apps.api.skills.shopify.refund_partial import (
    RefundPartial,
    RefundPartialInput,
    RefundPartialOutput,
)
from apps.api.skills.shopify.start_return import (
    StartReturn,
    StartReturnInput,
    StartReturnOutput,
)
from apps.api.skills.shopify.update_shipping_address import (
    UpdateShippingAddress,
    UpdateShippingAddressInput,
    UpdateShippingAddressOutput,
)

# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------

CTX = SkillContext(
    tenant_id="11111111-1111-1111-1111-111111111111",
    conversation_id="22222222-2222-2222-2222-222222222222",
    shopify_domain="myshop.myshopify.com",
    shopify_token="shpat_test",
)

CTX_NO_SHOPIFY = SkillContext(
    tenant_id="11111111-1111-1111-1111-111111111111",
    conversation_id="22222222-2222-2222-2222-222222222222",
)

_CANCELLED_ORDER = {
    "id": 1001,
    "cancelled_at": "2026-05-18T12:00:00Z",
    "financial_status": "voided",
    "fulfillment_status": None,
}

_UPDATED_ORDER = {
    "id": 1001,
    "shipping_address": {
        "address1": "Calle Nueva 42",
        "city": "Madrid",
        "country": "Spain",
        "province": "Community of Madrid",
        "zip": "28001",
    },
}

_REFUND_RESPONSE = {
    "id": 9001,
    "order_id": 1001,
    "transactions": [{"amount": "12.50", "currency": "EUR"}],
}

_RETURN_RESPONSE = {
    "id": 5001,
    "status": "open",
    "order_id": 1001,
}


# ----------------------------------------------------------------
# CancelOrder
# ----------------------------------------------------------------


class TestCancelOrder:
    def test_tier_is_l3(self) -> None:
        assert CancelOrder.tier == "L3"

    def test_slug(self) -> None:
        assert CancelOrder.slug == "shopify.cancel_order"

    def test_default_threshold(self) -> None:
        assert CancelOrder.default_threshold == 0.95

    def test_requires_idempotency(self) -> None:
        assert CancelOrder.requires_idempotency is True

    @pytest.mark.asyncio
    async def test_cancels_order_successfully(self) -> None:
        skill = CancelOrder()
        inputs = CancelOrderInput(order_id=1001)

        with patch("apps.api.skills.shopify.cancel_order.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.cancel_order = AsyncMock(return_value=_CANCELLED_ORDER)

            result = await skill.execute(CTX, inputs)

        assert isinstance(result, CancelOrderOutput)
        assert result.success is True
        assert result.order_id == 1001
        assert result.cancelled is True
        assert result.financial_status == "voided"
        instance.cancel_order.assert_awaited_once_with(
            1001, reason="customer", email=True, refund=False
        )

    @pytest.mark.asyncio
    async def test_cancels_with_custom_reason(self) -> None:
        skill = CancelOrder()
        inputs = CancelOrderInput(order_id=1001, reason="fraud", send_email=False, refund_payment=True)

        with patch("apps.api.skills.shopify.cancel_order.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.cancel_order = AsyncMock(return_value=_CANCELLED_ORDER)

            await skill.execute(CTX, inputs)

        instance.cancel_order.assert_awaited_once_with(
            1001, reason="fraud", email=False, refund=True
        )

    @pytest.mark.asyncio
    async def test_not_cancelled_if_api_returns_no_cancelled_at(self) -> None:
        skill = CancelOrder()
        inputs = CancelOrderInput(order_id=1001)

        with patch("apps.api.skills.shopify.cancel_order.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.cancel_order = AsyncMock(return_value={"id": 1001})

            result = await skill.execute(CTX, inputs)

        assert result.cancelled is False

    @pytest.mark.asyncio
    async def test_raises_if_shopify_not_configured(self) -> None:
        skill = CancelOrder()
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await skill.execute(CTX_NO_SHOPIFY, CancelOrderInput(order_id=1001))

    def test_anthropic_tool_shape(self) -> None:
        tool = CancelOrder().to_anthropic_tool()
        assert tool["name"] == "shopify_cancel_order"
        assert "order_id" in tool["input_schema"]["properties"]


# ----------------------------------------------------------------
# UpdateShippingAddress
# ----------------------------------------------------------------


class TestUpdateShippingAddress:
    def test_tier_is_l3(self) -> None:
        assert UpdateShippingAddress.tier == "L3"

    def test_slug(self) -> None:
        assert UpdateShippingAddress.slug == "shopify.update_shipping_address"

    def test_requires_idempotency(self) -> None:
        assert UpdateShippingAddress.requires_idempotency is True

    @pytest.mark.asyncio
    async def test_updates_address_successfully(self) -> None:
        skill = UpdateShippingAddress()
        inputs = UpdateShippingAddressInput(
            order_id=1001,
            address1="Calle Nueva 42",
            city="Madrid",
            province="Community of Madrid",
            country="Spain",
            zip_code="28001",
        )

        with patch(
            "apps.api.skills.shopify.update_shipping_address.ShopifyClient"
        ) as MockClient:
            instance = MockClient.return_value
            instance.update_shipping_address = AsyncMock(return_value=_UPDATED_ORDER)

            result = await skill.execute(CTX, inputs)

        assert isinstance(result, UpdateShippingAddressOutput)
        assert result.success is True
        assert result.order_id == 1001
        assert result.new_address1 == "Calle Nueva 42"
        assert result.new_city == "Madrid"
        assert result.new_country == "Spain"

    @pytest.mark.asyncio
    async def test_falls_back_to_input_if_api_omits_shipping(self) -> None:
        skill = UpdateShippingAddress()
        inputs = UpdateShippingAddressInput(
            order_id=1001,
            address1="Fallback St",
            city="Barcelona",
            province="Catalonia",
            country="Spain",
            zip_code="08001",
        )

        with patch(
            "apps.api.skills.shopify.update_shipping_address.ShopifyClient"
        ) as MockClient:
            instance = MockClient.return_value
            instance.update_shipping_address = AsyncMock(return_value={"id": 1001})

            result = await skill.execute(CTX, inputs)

        assert result.new_address1 == "Fallback St"

    @pytest.mark.asyncio
    async def test_raises_if_shopify_not_configured(self) -> None:
        skill = UpdateShippingAddress()
        inputs = UpdateShippingAddressInput(
            order_id=1001,
            address1="X",
            city="X",
            province="X",
            country="X",
            zip_code="X",
        )
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await skill.execute(CTX_NO_SHOPIFY, inputs)

    def test_anthropic_tool_shape(self) -> None:
        tool = UpdateShippingAddress().to_anthropic_tool()
        assert tool["name"] == "shopify_update_shipping_address"
        assert "order_id" in tool["input_schema"]["properties"]
        assert "address1" in tool["input_schema"]["properties"]


# ----------------------------------------------------------------
# RefundPartial
# ----------------------------------------------------------------


class TestRefundPartial:
    def test_tier_is_l3(self) -> None:
        assert RefundPartial.tier == "L3"

    def test_slug(self) -> None:
        assert RefundPartial.slug == "shopify.refund_partial"

    def test_requires_idempotency(self) -> None:
        assert RefundPartial.requires_idempotency is True

    @pytest.mark.asyncio
    async def test_creates_refund_successfully(self) -> None:
        skill = RefundPartial()
        inputs = RefundPartialInput(order_id=1001, amount="12.50", currency="EUR")

        with patch("apps.api.skills.shopify.refund_partial.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.refund_partial = AsyncMock(return_value=_REFUND_RESPONSE)

            result = await skill.execute(CTX, inputs)

        assert isinstance(result, RefundPartialOutput)
        assert result.success is True
        assert result.order_id == 1001
        assert result.refund_id == 9001
        assert result.amount == "12.50"
        assert result.currency == "EUR"
        instance.refund_partial.assert_awaited_once_with(1001, amount="12.50", currency="EUR", note="")

    @pytest.mark.asyncio
    async def test_refund_id_none_if_api_omits_it(self) -> None:
        skill = RefundPartial()
        inputs = RefundPartialInput(order_id=1001, amount="5.00", currency="EUR")

        with patch("apps.api.skills.shopify.refund_partial.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.refund_partial = AsyncMock(return_value={})

            result = await skill.execute(CTX, inputs)

        assert result.refund_id is None

    @pytest.mark.asyncio
    async def test_raises_if_shopify_not_configured(self) -> None:
        skill = RefundPartial()
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await skill.execute(CTX_NO_SHOPIFY, RefundPartialInput(order_id=1, amount="1.00", currency="EUR"))

    def test_anthropic_tool_shape(self) -> None:
        tool = RefundPartial().to_anthropic_tool()
        assert tool["name"] == "shopify_refund_partial"
        assert "amount" in tool["input_schema"]["properties"]
        assert "currency" in tool["input_schema"]["properties"]


# ----------------------------------------------------------------
# StartReturn
# ----------------------------------------------------------------


class TestStartReturn:
    def test_tier_is_l3(self) -> None:
        assert StartReturn.tier == "L3"

    def test_slug(self) -> None:
        assert StartReturn.slug == "shopify.start_return"

    def test_requires_idempotency(self) -> None:
        assert StartReturn.requires_idempotency is True

    @pytest.mark.asyncio
    async def test_starts_return_successfully(self) -> None:
        skill = StartReturn()
        inputs = StartReturnInput(order_id=1001, line_item_id=2001, quantity=1)

        with patch("apps.api.skills.shopify.start_return.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.start_return = AsyncMock(return_value=_RETURN_RESPONSE)

            result = await skill.execute(CTX, inputs)

        assert isinstance(result, StartReturnOutput)
        assert result.success is True
        assert result.order_id == 1001
        assert result.return_id == 5001
        assert result.status == "open"
        instance.start_return.assert_awaited_once_with(
            1001, line_item_id=2001, quantity=1, reason="other"
        )

    @pytest.mark.asyncio
    async def test_starts_return_with_custom_reason(self) -> None:
        skill = StartReturn()
        inputs = StartReturnInput(order_id=1001, line_item_id=2001, quantity=2, reason="defective")

        with patch("apps.api.skills.shopify.start_return.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.start_return = AsyncMock(return_value=_RETURN_RESPONSE)

            await skill.execute(CTX, inputs)

        instance.start_return.assert_awaited_once_with(
            1001, line_item_id=2001, quantity=2, reason="defective"
        )

    @pytest.mark.asyncio
    async def test_return_id_none_if_api_omits_it(self) -> None:
        skill = StartReturn()
        inputs = StartReturnInput(order_id=1001, line_item_id=2001, quantity=1)

        with patch("apps.api.skills.shopify.start_return.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.start_return = AsyncMock(return_value={})

            result = await skill.execute(CTX, inputs)

        assert result.return_id is None
        assert result.status is None

    @pytest.mark.asyncio
    async def test_raises_if_shopify_not_configured(self) -> None:
        skill = StartReturn()
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await skill.execute(CTX_NO_SHOPIFY, StartReturnInput(order_id=1, line_item_id=1, quantity=1))

    def test_anthropic_tool_shape(self) -> None:
        tool = StartReturn().to_anthropic_tool()
        assert tool["name"] == "shopify_start_return"
        assert "line_item_id" in tool["input_schema"]["properties"]
        assert "quantity" in tool["input_schema"]["properties"]
