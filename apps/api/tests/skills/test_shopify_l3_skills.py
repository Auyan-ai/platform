"""Tests para las skills L3 de Shopify: cancel_order, update_shipping_address,
refund_partial, start_return.

ShopifyClient mockeado con AsyncMock — sin llamadas HTTP reales.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from apps.api.integrations.base import IntegrationContext, MutationNotApplied
from apps.api.integrations.shopify import IssuedRefund, RefundableBalance, ShopifyActionError
from apps.api.skills.base import SkillContext, SkillRefusal
from apps.api.skills.shopify._models import Money
from apps.api.skills.shopify._order_guard import ActionOutcome
from apps.api.skills.shopify.cancel_order import (
    CancelOrder,
    CancelOrderInput,
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
from apps.api.tests.order_snapshots import CARD_SALE, MANUAL_SALE, snapshot, tx

# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------

_SHOPIFY_INTEGRATION_CTX = IntegrationContext(
    tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
    credentials={"domain": "myshop.myshopify.com", "token": "shpat_test"},
)

CTX = SkillContext(
    tenant_id="11111111-1111-1111-1111-111111111111",
    conversation_id="22222222-2222-2222-2222-222222222222",
    integration_ctx=_SHOPIFY_INTEGRATION_CTX,
)

CTX_NO_SHOPIFY = SkillContext(
    tenant_id="11111111-1111-1111-1111-111111111111",
    conversation_id="22222222-2222-2222-2222-222222222222",
)

_GBP_BALANCE = RefundableBalance(
    captured=Decimal("45.00"), refunded=Decimal("0"), currency="GBP"
)

_RETURN_RESPONSE = {
    "id": 5001,
    "status": "open",
    "order_id": 1001,
}


# ----------------------------------------------------------------
# Defensas sobre pedidos ya hechos (#318): adapter con snapshots en orden
# ----------------------------------------------------------------

_SHIPPED_WITH_TRACKING = {
    "fulfillment_status": "UNFULFILLED",
    "fulfillments": [{"status": "SUCCESS", "trackingInfo": [{"number": "1Z999"}]}],
}

_NEW_ADDRESS = {
    "address1": "Calle Nueva 42",
    "address2": None,
    "city": "Madrid",
    "zip": "28001",
    "country": "Spain",
}


def _adapter(*snapshots: object) -> AsyncMock:
    adapter = AsyncMock()
    adapter.get_order_snapshot = AsyncMock(side_effect=list(snapshots))
    adapter.cancel_order = AsyncMock(return_value={"id": 1001})
    adapter.update_shipping_address = AsyncMock(return_value={"id": 1001})
    return adapter


def _ctx(adapter: AsyncMock) -> SkillContext:
    return SkillContext(
        tenant_id=CTX.tenant_id,
        conversation_id=CTX.conversation_id,
        integration_ctx=_SHOPIFY_INTEGRATION_CTX,
        commerce_mock=adapter,
    )


# ----------------------------------------------------------------
# CancelOrder
# ----------------------------------------------------------------


class TestCancelOrder:
    def test_tier_is_l3(self) -> None:
        assert CancelOrder.tier == "L3"

    def test_requires_idempotency(self) -> None:
        assert CancelOrder.requires_idempotency is True

    def test_refund_payment_is_not_an_llm_input(self) -> None:
        tool = CancelOrder().to_anthropic_tool()
        assert "refund_payment" not in tool["input_schema"]["properties"]
        inputs = CancelOrderInput.model_validate({"order_id": 1001, "refund_payment": False})
        assert inputs.model_dump() == {"order_id": 1001, "reason": "customer", "send_email": True}

    @pytest.mark.asyncio
    async def test_prepare_approval_marks_the_refund_route_and_drops_refund_payment(
        self,
    ) -> None:
        adapter = _adapter(snapshot(transactions=[MANUAL_SALE]))
        approved = await CancelOrder().prepare_approval(
            _ctx(adapter), {"order_id": 1001, "refund_payment": False}
        )
        assert approved == {
            "order_id": 1001,
            "reason": "customer",
            "send_email": True,
            "refund_mode": "manual",
            "refund_gateway": None,
        }

    @pytest.mark.asyncio
    async def test_prepare_approval_names_the_automatic_gateway(self) -> None:
        adapter = _adapter(snapshot(transactions=[CARD_SALE]))
        approved = await CancelOrder().prepare_approval(_ctx(adapter), {"order_id": 1001})
        assert (approved["refund_mode"], approved["refund_gateway"]) == (
            "automatic",
            "shopify_payments",
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "order",
        [
            {"fulfillment_status": "FULFILLED"},
            {"fulfillment_status": "PARTIALLY_FULFILLED"},
            _SHIPPED_WITH_TRACKING,
        ],
        ids=["fulfilled", "partial", "tracking"],
    )
    async def test_prepare_approval_refuses_a_shipped_order(self, order: dict) -> None:
        adapter = _adapter(snapshot(**order))
        with pytest.raises(SkillRefusal) as refused:
            await CancelOrder().prepare_approval(_ctx(adapter), {"order_id": 1001})
        assert refused.value.code == "order_shipped"
        assert refused.value.customer_message.startswith("Tu pedido ya ha salido del almacén")

    @pytest.mark.asyncio
    async def test_cancelled_tracking_does_not_count_as_shipped(self) -> None:
        adapter = _adapter(
            snapshot(fulfillments=[{"status": "CANCELLED", "trackingInfo": [{"number": "X"}]}])
        )
        approved = await CancelOrder().prepare_approval(_ctx(adapter), {"order_id": 1001})
        assert approved["refund_mode"] == "manual"

    @pytest.mark.asyncio
    async def test_prepare_approval_refuses_an_already_cancelled_order(self) -> None:
        adapter = _adapter(snapshot(cancelled=True))
        with pytest.raises(SkillRefusal) as refused:
            await CancelOrder().prepare_approval(_ctx(adapter), {"order_id": 1001})
        assert refused.value.code == "order_cancelled"

    @pytest.mark.asyncio
    async def test_execute_rechecks_and_refuses_if_it_shipped_while_waiting(self) -> None:
        adapter = _adapter(snapshot(fulfillment_status="FULFILLED"))
        with pytest.raises(SkillRefusal):
            await CancelOrder().execute(_ctx(adapter), CancelOrderInput(order_id=1001))
        adapter.cancel_order.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_order_unreadable_before_cancelling_is_not_applied(self) -> None:
        adapter = _adapter(ShopifyActionError("graphql_errors: THROTTLED"))
        with pytest.raises(MutationNotApplied):
            await CancelOrder().execute(_ctx(adapter), CancelOrderInput(order_id=1001))
        adapter.cancel_order.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failure_after_cancelling_is_not_marked_not_applied(self) -> None:
        adapter = _adapter(snapshot(transactions=[CARD_SALE]), TimeoutError("read timeout"))
        with pytest.raises(TimeoutError) as raised:
            await CancelOrder().execute(_ctx(adapter), CancelOrderInput(order_id=1001))
        assert not isinstance(raised.value, MutationNotApplied)
        adapter.cancel_order.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_paid_card_order_refunds_restocks_and_confirms(self) -> None:
        adapter = _adapter(
            snapshot(transactions=[CARD_SALE]),
            snapshot(cancelled=True, transactions=[CARD_SALE, tx(2, "REFUND")]),
        )
        out = await CancelOrder().execute(_ctx(adapter), CancelOrderInput(order_id=1001))
        assert out.model_dump(mode="json") == {
            "order_id": 1001,
            "cancelled": True,
            "outcome": "confirmed",
            "detail": None,
            "refund_mode": "automatic",
            "refund_gateway": "shopify_payments",
            "success": True,
        }
        assert adapter.cancel_order.await_args.kwargs == {
            "reason": "customer",
            "email": True,
            "refund": True,
            "restock": True,
        }

    @pytest.mark.asyncio
    async def test_unpaid_order_is_cancelled_without_refund(self) -> None:
        adapter = _adapter(snapshot(), snapshot(cancelled=True))
        out = await CancelOrder().execute(_ctx(adapter), CancelOrderInput(order_id=1001))
        assert adapter.cancel_order.await_args.kwargs["refund"] is False
        # Sin cobro en Shopify no se sabe si pagó por fuera: devuelve la tienda.
        assert (out.outcome, out.success) == (ActionOutcome.REFUND_MANUAL, False)

    @pytest.mark.asyncio
    async def test_open_fulfillment_without_tracking_skips_restock(self) -> None:
        fulfillments = [{"status": "OPEN", "trackingInfo": []}]
        adapter = _adapter(
            snapshot(transactions=[CARD_SALE], fulfillments=fulfillments),
            snapshot(cancelled=True, transactions=[CARD_SALE, tx(2, "REFUND")]),
        )
        await CancelOrder().execute(_ctx(adapter), CancelOrderInput(order_id=1001))
        assert adapter.cancel_order.await_args.kwargs["restock"] is False

    @pytest.mark.asyncio
    async def test_manual_gateway_reports_manual_refund(self) -> None:
        manual_refund = tx(2, "REFUND", gateway=None, manual=True)
        adapter = _adapter(
            snapshot(transactions=[MANUAL_SALE]),
            snapshot(cancelled=True, transactions=[MANUAL_SALE, manual_refund]),
        )
        out = await CancelOrder().execute(_ctx(adapter), CancelOrderInput(order_id=1001))
        assert (out.outcome, out.refund_mode, out.success) == (
            ActionOutcome.REFUND_MANUAL,
            "manual",
            False,
        )

    @pytest.mark.asyncio
    async def test_pending_refund_is_in_process(self) -> None:
        adapter = _adapter(
            snapshot(transactions=[CARD_SALE]),
            snapshot(cancelled=True, transactions=[CARD_SALE, tx(2, "REFUND", "PENDING")]),
        )
        out = await CancelOrder().execute(_ctx(adapter), CancelOrderInput(order_id=1001))
        assert (out.outcome, out.success) == (ActionOutcome.REFUND_PENDING, True)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["FAILURE", "ERROR"])
    async def test_failed_refund_carries_the_gateway_error(self, status: str) -> None:
        failed = tx(2, "REFUND", status, error_code="CARD_DECLINED")
        adapter = _adapter(
            snapshot(transactions=[CARD_SALE]),
            snapshot(cancelled=True, transactions=[CARD_SALE, failed]),
        )
        out = await CancelOrder().execute(_ctx(adapter), CancelOrderInput(order_id=1001))
        assert (out.outcome, out.detail, out.success) == (
            ActionOutcome.REFUND_FAILED,
            "CARD_DECLINED",
            False,
        )

    @pytest.mark.asyncio
    async def test_missing_refund_transaction_is_a_failure(self) -> None:
        adapter = _adapter(
            snapshot(transactions=[CARD_SALE]),
            snapshot(cancelled=True, transactions=[CARD_SALE]),
        )
        out = await CancelOrder().execute(_ctx(adapter), CancelOrderInput(order_id=1001))
        assert (out.outcome, out.detail) == (
            ActionOutcome.REFUND_FAILED,
            "refund_transaction_missing",
        )

    @pytest.mark.asyncio
    async def test_order_still_open_after_cancel_is_not_confirmed(self) -> None:
        adapter = _adapter(
            snapshot(transactions=[CARD_SALE]), snapshot(transactions=[CARD_SALE])
        )
        out = await CancelOrder().execute(_ctx(adapter), CancelOrderInput(order_id=1001))
        assert (out.cancelled, out.outcome, out.success) == (
            False,
            ActionOutcome.NOT_CONFIRMED,
            False,
        )

    @pytest.mark.asyncio
    async def test_raises_if_shopify_not_configured(self) -> None:
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await CancelOrder().execute(CTX_NO_SHOPIFY, CancelOrderInput(order_id=1001))


# ----------------------------------------------------------------
# UpdateShippingAddress
# ----------------------------------------------------------------

_ADDRESS_INPUT = UpdateShippingAddressInput(
    order_id=1001,
    address1="Calle Nueva 42",
    city="Madrid",
    province="Community of Madrid",
    zip_code="28001",
)


class TestUpdateShippingAddress:
    def test_tier_is_l3(self) -> None:
        assert UpdateShippingAddress.tier == "L3"

    def test_requires_idempotency(self) -> None:
        assert UpdateShippingAddress.requires_idempotency is True

    @pytest.mark.asyncio
    async def test_prepare_approval_passes_an_unshipped_order(self) -> None:
        raw = _ADDRESS_INPUT.model_dump()
        approved = await UpdateShippingAddress().prepare_approval(_ctx(_adapter(snapshot())), raw)
        assert approved == raw

    @pytest.mark.asyncio
    async def test_prepare_approval_refuses_a_shipped_order(self) -> None:
        adapter = _adapter(snapshot(**_SHIPPED_WITH_TRACKING))
        with pytest.raises(SkillRefusal) as refused:
            await UpdateShippingAddress().prepare_approval(
                _ctx(adapter), _ADDRESS_INPUT.model_dump()
            )
        assert refused.value.code == "order_shipped"
        assert "no puedo cambiar la dirección" in refused.value.customer_message
        assert "#1500" in refused.value.team_reason

    @pytest.mark.asyncio
    async def test_order_unreadable_before_the_change_is_not_applied(self) -> None:
        adapter = _adapter(ShopifyActionError("order_not_found: 1001"))
        with pytest.raises(MutationNotApplied):
            await UpdateShippingAddress().execute(_ctx(adapter), _ADDRESS_INPUT)
        adapter.update_shipping_address.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_confirms_the_address_reread_from_shopify(self) -> None:
        saved = {**_NEW_ADDRESS, "address1": "  calle nueva 42 "}
        adapter = _adapter(snapshot(), snapshot(address=saved))
        out = await UpdateShippingAddress().execute(_ctx(adapter), _ADDRESS_INPUT)
        assert isinstance(out, UpdateShippingAddressOutput)
        assert (out.outcome, out.success, out.new_city, out.new_country) == (
            ActionOutcome.CONFIRMED,
            True,
            "Madrid",
            "Spain",
        )

    @pytest.mark.asyncio
    async def test_address_not_saved_is_not_confirmed(self) -> None:
        old = {**_NEW_ADDRESS, "address1": "Calle Vieja 1", "zip": "28002"}
        adapter = _adapter(snapshot(), snapshot(address=old))
        out = await UpdateShippingAddress().execute(_ctx(adapter), _ADDRESS_INPUT)
        assert (out.outcome, out.detail, out.success) == (
            ActionOutcome.NOT_CONFIRMED,
            "address_mismatch: address1, zip",
            False,
        )

    @pytest.mark.asyncio
    async def test_execute_refuses_if_it_shipped_while_waiting(self) -> None:
        adapter = _adapter(snapshot(fulfillment_status="FULFILLED"))
        with pytest.raises(SkillRefusal):
            await UpdateShippingAddress().execute(_ctx(adapter), _ADDRESS_INPUT)
        adapter.update_shipping_address.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_if_shopify_not_configured(self) -> None:
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await UpdateShippingAddress().execute(CTX_NO_SHOPIFY, _ADDRESS_INPUT)


# ----------------------------------------------------------------
# RefundPartial
# ----------------------------------------------------------------


class TestRefundPartial:
    def test_tier_is_l3(self) -> None:
        assert RefundPartial.tier == "L3"

    def test_requires_idempotency(self) -> None:
        assert RefundPartial.requires_idempotency is True

    @pytest.mark.asyncio
    async def test_refund_reports_the_currency_derived_from_the_order(self) -> None:
        adapter = _adapter(
            snapshot(transactions=[CARD_SALE]),
            snapshot(transactions=[CARD_SALE, tx(2, "REFUND")]),
        )
        adapter.refund_partial = AsyncMock(
            return_value=IssuedRefund(refund_id=9001, amount=Decimal("12.50"), currency="GBP")
        )
        out = await RefundPartial().execute(
            replace(_ctx(adapter), idempotency_key="aprob-1"), RefundPartialInput(order_id=1001, amount="12.50")
        )
        assert isinstance(out, RefundPartialOutput)
        assert (out.refund_id, out.amount, out.outcome, out.success) == (
            9001,
            Money(amount="12.50", currency="GBP"),
            ActionOutcome.CONFIRMED,
            True,
        )

    @pytest.mark.asyncio
    async def test_manual_gateway_refund_is_reported_as_manual(self) -> None:
        manual_refund = tx(2, "REFUND", gateway=None, manual=True)
        adapter = _adapter(
            snapshot(transactions=[MANUAL_SALE]),
            snapshot(transactions=[MANUAL_SALE, manual_refund]),
        )
        adapter.refund_partial = AsyncMock(
            return_value=IssuedRefund(refund_id=9001, amount=Decimal("5"), currency="EUR")
        )
        out = await RefundPartial().execute(
            replace(_ctx(adapter), idempotency_key="aprob-1"), RefundPartialInput(order_id=1001, amount="5")
        )
        assert (out.outcome, out.refund_mode, out.success) == (
            ActionOutcome.REFUND_MANUAL,
            "manual",
            False,
        )

    def test_llm_supplied_currency_is_ignored(self) -> None:
        inputs = RefundPartialInput.model_validate(
            {"order_id": 1001, "amount": "12.50", "currency": "EUR"}
        )
        assert "currency" not in inputs.model_dump()

    @pytest.mark.asyncio
    async def test_raises_if_shopify_not_configured(self) -> None:
        skill = RefundPartial()
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await skill.execute(CTX_NO_SHOPIFY, RefundPartialInput(order_id=1, amount="1.00"))

    @pytest.mark.asyncio
    async def test_prepare_approval_pins_currency_and_refund_route(self) -> None:
        adapter = _adapter(snapshot(transactions=[MANUAL_SALE]))
        adapter.get_refundable_balance = AsyncMock(return_value=_GBP_BALANCE)
        approved = await RefundPartial().prepare_approval(
            _ctx(adapter), {"order_id": 1001, "amount": "12.50", "currency": "EUR"}
        )
        assert approved == {
            "order_id": 1001,
            "amount": "12.50",
            "currency": "GBP",
            "refund_mode": "manual",
            "refund_gateway": None,
        }

    @pytest.mark.asyncio
    async def test_prepare_approval_rejects_amount_above_refundable(self) -> None:
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.get_order_by_name = AsyncMock(return_value=None)
            instance.get_refundable_balance = AsyncMock(return_value=_GBP_BALANCE)

            with pytest.raises(ShopifyActionError, match="refund_amount_exceeds_refundable"):
                await RefundPartial().prepare_approval(
                    CTX, {"order_id": 1001, "amount": "45.01"}
                )

    def test_anthropic_tool_shape(self) -> None:
        tool = RefundPartial().to_anthropic_tool()
        assert tool["name"] == "shopify_refund_partial"
        assert "amount" in tool["input_schema"]["properties"]
        assert "currency" not in tool["input_schema"]["properties"]

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

        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.get_order_by_name = AsyncMock(return_value=None)
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

        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.get_order_by_name = AsyncMock(return_value=None)
            instance.start_return = AsyncMock(return_value=_RETURN_RESPONSE)

            await skill.execute(CTX, inputs)

        instance.start_return.assert_awaited_once_with(
            1001, line_item_id=2001, quantity=2, reason="defective"
        )

    @pytest.mark.asyncio
    async def test_return_id_none_if_api_omits_it(self) -> None:
        skill = StartReturn()
        inputs = StartReturnInput(order_id=1001, line_item_id=2001, quantity=1)

        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.get_order_by_name = AsyncMock(return_value=None)
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "default", "start"),
    [
        ("en", "es", "Your order has already left the warehouse"),
        ("fr", "es", "Ta commande a déjà"),
        ("ca", "es", "La teva comanda ja ha sortit"),
        ("de", "en", "Your order has already left"),
    ],
)
async def test_order_refusal_speaks_the_conversation_language(
    language: str, default: str, start: str
) -> None:
    from dataclasses import replace

    ctx = replace(
        _ctx(_adapter(snapshot(fulfillment_status="FULFILLED"))),
        language=language,
        default_language=default,
    )
    with pytest.raises(SkillRefusal) as refused:
        await CancelOrder().prepare_approval(ctx, {"order_id": 1001})
    assert refused.value.customer_message.startswith(start)
    # El motivo para el equipo no cambia de idioma.
    assert refused.value.team_reason.startswith("El cliente pidió cancelar el pedido")
