"""`shopify.start_return` y `shopify.start_exchange` con la política del tenant (ADR 0014)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.integrations.base import IntegrationContext, MutationNotApplied
from apps.api.integrations.shopify import CreatedReturn
from apps.api.services.approval_execution import (
    Applied,
    NotApplied,
    Unknown,
    execute_once,
)
from apps.api.services.approval_reply import outcome_message
from apps.api.services.approval_resolution import team_followup_reason
from apps.api.services.returns import (
    CalculatedLine,
    ExchangeVariant,
    PhotoRef,
    ReturnableLine,
    ReturnableOrder,
    ReturnCalculation,
    ReturnPlan,
)
from apps.api.services.returns_policy import ActivePolicy, ReturnsPolicy
from apps.api.skills.base import ReconcileUnknown, SkillContext, SkillRefusal, SkillRejection
from apps.api.skills.shopify._order_guard import ActionOutcome
from apps.api.skills.shopify.start_exchange import StartExchange
from apps.api.skills.shopify.start_return import (
    StartReturn,
    StartReturnInput,
    StartReturnOutput,
)

NOW = datetime.now(UTC)
UNIT = Decimal("76.95")
FLI = "gid://shopify/FulfillmentLineItem/9001"


def _policy(**overrides: Any) -> ActivePolicy:
    raw: dict[str, Any] = {
        "schema_version": 1,
        "window": {"days": 30, "starts_at": "delivery"},
        "reasons": [
            {
                "code": "defective",
                "label": "Defectuoso",
                "fault": "store",
                "required_evidence": ["photo"],
                "shopify_reason": "damaged-or-defective",
            },
            {
                "code": "too_small",
                "label": "Pequeña",
                "fault": "customer",
                "shopify_reason": "too-small",
                "required_evidence": [],
            },
        ],
        "shipping": {
            "method": "customer_ships",
            "return_address": "Calle Mayor 1, 28013 Madrid",
            "payer": {"store_fault": "store", "customer_fault": "customer"},
        },
        "refund_days": 14,
        "refund_method": "original_payment",
        "restocking_fee_percent": {"store_fault": "0", "customer_fault": "0"},
        "excluded_product_tags": [],
        "exchanges": {
            "enabled": True,
            "kinds": ["variant"],
            "requires_approval": True,
            "higher_price": "customer_pays",
            "lower_price": "refund_difference",
            "ship_replacement": "after_receipt",
        },
        "returns_require_approval": False,
        "evidence_requires_approval": True,
    }
    raw.update(overrides)
    return ActivePolicy(version=5, policy=ReturnsPolicy.model_validate(raw))


def _order(delivered_days_ago: int = 3, quantity: int = 1) -> ReturnableOrder:
    return ReturnableOrder(
        order_id=7409804542232,
        name="#1431",
        ordered_at=NOW - timedelta(days=delivered_days_ago + 2),
        currency="USD",
        taxes_included=False,
        cancelled=False,
        lines=(
            ReturnableLine(
                line_item_id=17463441195288,
                fulfillment_line_item_id=FLI,
                title="Bolso Bandolera - Marino",
                returnable_quantity=quantity,
                product_id=10287987851544,
                product_tags=frozenset({"básicos"}),
                shipped_at=NOW - timedelta(days=delivered_days_ago + 1),
                delivered_at=NOW - timedelta(days=delivered_days_ago),
            ),
        ),
    )


@dataclass
class FakeShopify:
    order: ReturnableOrder = field(default_factory=_order)
    variants: tuple[ExchangeVariant, ...] = ()
    created_status: str = "open"
    note_fails: bool = False
    # Devoluciones que existen en Shopify, por `plan_id` (la marca de sus líneas).
    returns: dict[str, CreatedReturn] = field(default_factory=dict)
    find_fails: bool = False
    order_read_fails: bool = False
    calls: list[tuple[str, Any]] = field(default_factory=list)

    async def get_returnable_order(self, ctx: Any, order_id: int) -> ReturnableOrder:
        self.calls.append(("get_returnable_order", order_id))
        if self.order_read_fails:
            raise RuntimeError("Shopify 503")
        return self.order

    async def find_return(self, ctx: Any, plan: ReturnPlan) -> CreatedReturn | None:
        self.calls.append(("find_return", plan.plan_id))
        if self.find_fails:
            raise RuntimeError("Shopify 502")
        return self.returns.get(str(plan.plan_id))

    async def get_exchange_variants(self, ctx: Any, ids: list[int]) -> tuple[ExchangeVariant, ...]:
        self.calls.append(("get_exchange_variants", ids))
        return self.variants

    async def calculate_return(
        self,
        ctx: Any,
        order_id: int,
        *,
        lines: list[tuple[str, int]],
        exchange: list[tuple[int, int]],
    ) -> ReturnCalculation:
        self.calls.append(("calculate_return", (lines, exchange)))
        # Como Shopify: el subtotal de cada línea es precio unitario x cantidad.
        return ReturnCalculation(
            currency="USD",
            returned=tuple(
                CalculatedLine(key=fli, quantity=q, subtotal=-UNIT * q, tax=Decimal("0"))
                for fli, q in lines
            ),
            exchanged=tuple(
                CalculatedLine(
                    key=f"gid://shopify/ProductVariant/{v}",
                    quantity=q,
                    subtotal=UNIT * q,
                    tax=Decimal("0"),
                )
                for v, q in exchange
            ),
        )

    async def create_return(self, ctx: Any, plan: ReturnPlan) -> CreatedReturn:
        self.calls.append(("create_return", plan))
        created = CreatedReturn(
            return_id=5001, name="#1431-R2", status=self.created_status, reason_handle="too-small"
        )
        self.returns[str(plan.plan_id)] = created
        return created

    async def append_order_note(self, ctx: Any, order_id: int, text: str) -> None:
        self.calls.append(("append_order_note", text))
        if self.note_fails:
            raise RuntimeError("shopify 500")

    def called(self, name: str) -> list[Any]:
        return [arg for n, arg in self.calls if n == name]


def _ctx(shopify: FakeShopify, policy: ActivePolicy | None = None, **kw: Any) -> SkillContext:
    return SkillContext(
        tenant_id="11111111-1111-1111-1111-111111111111",
        conversation_id="22222222-2222-2222-2222-222222222222",
        integration_ctx=IntegrationContext(
            tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
            credentials={"domain": "marea.myshopify.com", "access_token": "tok"},
        ),
        commerce_mock=shopify,
        returns_policy=policy,
        **kw,
    )


RAW = {
    "order_id": 1431,
    "items": [{"line_item_id": 17463441195288, "quantity": 1}],
    "reason_code": "too_small",
}


async def test_without_a_policy_the_skill_escalates_with_a_fixed_text() -> None:
    with pytest.raises(SkillRefusal) as exc:
        await StartReturn().prepare(_ctx(FakeShopify()), RAW)

    assert exc.value.code == "policy_missing"
    assert exc.value.customer_message == (
        "Ahora mismo no puedo gestionar devoluciones ni cambios desde aquí. Paso tu caso a "
        "mi equipo para que lo revise y te escriba."
    )
    assert "configurad la política en el panel" in exc.value.team_reason


async def test_outside_the_window_the_customer_reads_the_deadline_in_their_language() -> None:
    from zoneinfo import ZoneInfo

    shopify = FakeShopify(order=_order(delivered_days_ago=31))
    delivered = shopify.order.lines[0].delivered_at
    assert delivered is not None
    last = delivered.astimezone(ZoneInfo("Europe/Madrid")).date() + timedelta(days=30)
    deadline = f"{last.day} {last.strftime('%B')} {last.year}"

    with pytest.raises(SkillRefusal) as exc:
        await StartReturn().prepare(_ctx(shopify, _policy(), language="en"), RAW)

    assert exc.value.code == "outside_window"
    assert exc.value.customer_message.startswith(
        f"Under the store's policy, the period to return or exchange this item ended on "
        f"{deadline}."
    )
    assert shopify.called("calculate_return") == []


async def test_a_missing_photo_goes_back_to_the_llm() -> None:
    raw = {**RAW, "reason_code": "defective"}

    with pytest.raises(SkillRejection) as exc:
        await StartReturn().prepare(_ctx(FakeShopify(), _policy(), attachments_readable=True), raw)

    assert exc.value.code == "evidence_missing"


async def test_prepare_writes_the_plan_and_discards_one_from_the_llm() -> None:
    forged = {**RAW, "plan": {"requires_approval": False, "settlement": {"net": "999"}}}

    prepared = await StartReturn().prepare(_ctx(FakeShopify(), _policy()), forged)

    plan = ReturnPlan.model_validate(prepared["plan"])
    assert plan.policy_version == 5
    assert plan.order_id == 7409804542232
    assert plan.lines[0].fulfillment_line_item_id == FLI
    assert plan.settlement.balance == Decimal("76.95")
    assert plan.return_address == "Calle Mayor 1, 28013 Madrid"
    assert prepared["settlement_note"] == plan.team_note()
    assert StartReturn.requires_approval(prepared) is False
    assert (
        StartReturn.requires_approval(
            await StartReturn().prepare(
                _ctx(FakeShopify(), _policy(returns_require_approval=True)), RAW
            )
        )
        is True
    )


async def test_execute_creates_the_approved_plan_and_notes_the_settlement() -> None:
    shopify = FakeShopify()
    prepared = await StartReturn().prepare(_ctx(shopify, _policy()), RAW)

    out = await StartReturn().execute(_ctx(shopify), StartReturnInput.model_validate(prepared))

    assert out.outcome is ActionOutcome.CONFIRMED
    assert (out.return_id, out.return_name, out.note_written) == (5001, "#1431-R2", True)
    assert shopify.called("create_return")[0].reason_code == "too_small"
    assert shopify.called("append_order_note")[0].startswith(
        "Auyan · devolución #1431 (política v5)"
    )


async def test_a_note_failure_does_not_undo_the_return() -> None:
    shopify = FakeShopify(note_fails=True)
    prepared = await StartReturn().prepare(_ctx(shopify, _policy()), RAW)

    out = await StartReturn().execute(_ctx(shopify), StartReturnInput.model_validate(prepared))

    assert out.outcome is ActionOutcome.CONFIRMED
    assert out.note_written is False


async def test_a_return_shopify_does_not_open_is_not_confirmed() -> None:
    shopify = FakeShopify(created_status="declined")
    prepared = await StartReturn().prepare(_ctx(shopify, _policy()), RAW)

    out = await StartReturn().execute(_ctx(shopify), StartReturnInput.model_validate(prepared))

    assert out.outcome is ActionOutcome.NOT_CONFIRMED
    assert out.success is False


async def test_execute_refuses_when_the_item_is_no_longer_returnable() -> None:
    shopify = FakeShopify()
    prepared = await StartReturn().prepare(_ctx(shopify, _policy()), RAW)
    shopify.order = replace(_order(), lines=())

    with pytest.raises(SkillRefusal) as exc:
        await StartReturn().execute(_ctx(shopify), StartReturnInput.model_validate(prepared))

    assert exc.value.code == "no_longer_possible"
    assert shopify.called("create_return") == []


async def test_execute_without_a_plan_fails_closed() -> None:
    with pytest.raises(ValueError, match="return_plan_missing"):
        await StartReturn().execute(_ctx(FakeShopify()), StartReturnInput.model_validate(RAW))


EXCHANGE = {**RAW, "exchange_items": [{"variant_id": 52117802090776, "quantity": 1}]}
CAQUI = ExchangeVariant(
    variant_id=52117802090776,
    product_id=10287987851544,
    title="Bolso Bandolera - Caqui",
    available=True,
)


async def test_an_exchange_follows_the_store_approval_choice() -> None:
    terms = {
        "enabled": True,
        "kinds": ["variant"],
        "requires_approval": False,
        "higher_price": "customer_pays",
        "lower_price": "refund_difference",
        "ship_replacement": "immediately",
    }

    prepared = await StartExchange().prepare(
        _ctx(FakeShopify(variants=(CAQUI,)), _policy(exchanges=terms)), EXCHANGE
    )

    assert StartExchange.requires_approval(prepared) is False


async def test_an_exchange_with_approval_nets_the_difference() -> None:
    prepared = await StartExchange().prepare(
        _ctx(FakeShopify(variants=(CAQUI,)), _policy()), EXCHANGE
    )

    plan = ReturnPlan.model_validate(prepared["plan"])
    assert StartExchange.requires_approval(prepared) is True
    assert plan.exchange_lines[0].title == "Bolso Bandolera - Caqui"
    assert plan.settlement.balance == Decimal("0.00")


async def test_an_exchange_for_another_product_is_rejected_when_only_variants_count() -> None:
    other = replace(CAQUI, product_id=1)

    with pytest.raises(SkillRejection) as exc:
        await StartExchange().prepare(_ctx(FakeShopify(variants=(other,)), _policy()), EXCHANGE)

    assert exc.value.code == "exchange_kind_not_allowed"


async def test_an_exchange_when_the_store_has_none_escalates() -> None:
    policy = _policy(exchanges={"enabled": False})
    shopify = FakeShopify(variants=(CAQUI,))

    with pytest.raises(SkillRefusal) as exc:
        await StartExchange().prepare(_ctx(shopify, policy), EXCHANGE)

    assert exc.value.code == "exchanges_disabled"
    assert shopify.called("get_exchange_variants") == []


def test_the_llm_never_sees_the_plan_in_the_tool_schema() -> None:
    returns = StartReturn().to_anthropic_tool()["input_schema"]["properties"]
    exchange = StartExchange().to_anthropic_tool()["input_schema"]["properties"]

    assert sorted(returns) == ["items", "order_id", "reason_code", "refund_preference"]
    assert sorted(exchange) == [
        "exchange_items",
        "items",
        "order_id",
        "reason_code",
        "refund_preference",
    ]


def test_photo_refs_travel_in_the_plan() -> None:
    assert PhotoRef(message_id="m-1", index=0).model_dump() == {"message_id": "m-1", "index": 0}


@pytest.mark.parametrize("skill", [StartReturn, StartExchange])
async def test_the_same_request_reuses_its_pending_approval(skill: Any) -> None:
    from apps.api.agents.nodes.execute_skill import _same_order_action

    raw = {**RAW, "exchange_items": [{"variant_id": CAQUI.variant_id, "quantity": 1}]}
    if skill is StartReturn:
        raw.pop("exchange_items")
    shopify = FakeShopify(variants=(CAQUI,))
    first = await skill().prepare(_ctx(shopify, _policy()), raw)
    again = await skill().prepare(_ctx(shopify, _policy()), raw)
    again["plan"]["requested_at"] = "2030-01-01T00:00:00+00:00"
    again["settlement_note"] = "otra redacción"

    assert await _same_order_action({}, first, again, skill) is True
    assert (
        await _same_order_action({}, first, {**again, "reason_code": "defectuoso"}, skill) is False
    )


async def test_several_units_are_settled_per_unit() -> None:
    shopify = FakeShopify(order=_order(quantity=3))
    raw = {**RAW, "items": [{"line_item_id": 17463441195288, "quantity": 2}]}

    prepared = await StartReturn().prepare(_ctx(shopify, _policy()), raw)

    plan = ReturnPlan.model_validate(prepared["plan"])
    assert plan.settlement.returned_total == Decimal("153.90")
    assert plan.settlement.balance == Decimal("153.90")
    assert shopify.called("calculate_return") == [([(FLI, 2)], [])]


@dataclass
class BrokenShopify(FakeShopify):
    fail_on: str = "calculate_return"
    # True: Shopify crea la devolución y la respuesta se pierde (timeout tras enviarla).
    created_before_failing: bool = False

    async def calculate_return(self, ctx: Any, order_id: int, **kw: Any) -> ReturnCalculation:
        if self.fail_on == "calculate_return":
            raise RuntimeError("Shopify 502")
        return await super().calculate_return(ctx, order_id, **kw)

    async def create_return(self, ctx: Any, plan: ReturnPlan) -> CreatedReturn:
        if self.created_before_failing:
            await super().create_return(ctx, plan)
        raise httpx.ReadTimeout("ReadTimeout")


async def test_a_shopify_failure_while_preparing_escalates_with_a_fixed_text() -> None:
    with pytest.raises(SkillRefusal) as exc:
        await StartReturn().prepare(_ctx(BrokenShopify(), _policy()), RAW)

    assert exc.value.code == "shopify_error"
    assert exc.value.customer_message.startswith("No he podido preparar la devolución")
    assert "RuntimeError: Shopify 502" in exc.value.team_reason


async def _approved(shopify: FakeShopify) -> StartReturnInput:
    prepared = await StartReturn().prepare(_ctx(shopify, _policy()), RAW)
    return StartReturnInput.model_validate(prepared)


async def test_a_shopify_failure_while_creating_is_unknown_and_reconciled() -> None:
    """Un timeout tras enviar `returnCreate` no dice si se creó: ni texto fijo de "no se
    abrió nada" ni vuelta a pending; se lee Shopify y, si no aparece, al equipo."""
    shopify = BrokenShopify(fail_on="create_return")
    inputs = await _approved(shopify)

    with pytest.raises(httpx.ReadTimeout):
        await StartReturn().execute(_ctx(shopify), inputs)
    result = await execute_once(StartReturn(), _ctx(shopify), inputs, earlier_attempt=False)

    assert isinstance(result, Unknown)
    assert "ReadTimeout" in result.error
    assert shopify.called("find_return") == [inputs.plan.plan_id] * 3


async def test_a_return_created_before_a_timeout_is_applied() -> None:
    shopify = BrokenShopify(fail_on="create_return", created_before_failing=True)
    inputs = await _approved(shopify)

    result = await execute_once(StartReturn(), _ctx(shopify), inputs, earlier_attempt=False)

    assert isinstance(result, Applied)
    assert (result.output["return_id"], result.output["outcome"]) == (5001, "confirmed")
    assert result.output["plan"]["plan_id"] == str(inputs.plan.plan_id)
    assert len(shopify.called("create_return")) == 1
    assert outcome_message("shopify.start_return", result.output, "es", "es")
    assert team_followup_reason("shopify.start_return", result.output) is None


async def test_a_read_failure_before_creating_is_not_applied() -> None:
    shopify = FakeShopify()
    inputs = await _approved(shopify)
    shopify.order_read_fails = True

    with pytest.raises(MutationNotApplied, match="leer el pedido"):
        await StartReturn().execute(_ctx(shopify), inputs)
    result = await execute_once(StartReturn(), _ctx(shopify), inputs, earlier_attempt=False)

    assert isinstance(result, NotApplied)
    assert shopify.called("create_return") == []


async def test_a_retry_finds_its_own_return_before_checking_the_order() -> None:
    """La devolución que creó el intento anterior deja la línea sin unidades devolvibles:
    el reintento la encuentra por la marca antes de mirar el pedido y no la repite."""
    shopify = FakeShopify()
    inputs = await _approved(shopify)
    await StartReturn().execute(_ctx(shopify), inputs)
    shopify.order = replace(_order(), lines=())

    result = await execute_once(StartReturn(), _ctx(shopify), inputs, earlier_attempt=True)

    assert isinstance(result, Applied)
    assert result.output["return_id"] == 5001
    assert len(shopify.called("create_return")) == 1


async def test_reconcile_reads_shopify_by_the_plan_marker() -> None:
    shopify = FakeShopify()
    inputs = await _approved(shopify)

    assert await StartReturn().reconcile(_ctx(shopify), inputs) is None
    await StartReturn().execute(_ctx(shopify), inputs)
    found = await StartReturn().reconcile(_ctx(shopify), inputs)
    assert isinstance(found, StartReturnOutput)
    assert (found.return_id, found.plan, found.note_written) == (5001, inputs.plan, True)

    shopify.find_fails = True
    with pytest.raises(ReconcileUnknown):
        await StartReturn().reconcile(_ctx(shopify), inputs)


async def test_fees_above_the_refund_escalate_with_a_fixed_text_and_no_amount() -> None:
    shopify = FakeShopify()
    policy = _policy(
        shipping={
            "method": "store_label",
            "payer": {"store_fault": "store", "customer_fault": "customer"},
            "customer_fee_mode": "fixed",
            "customer_fee": {"amount": "100.00", "currency": "USD"},
        }
    )

    with pytest.raises(SkillRefusal) as exc:
        await StartReturn().prepare(_ctx(shopify, policy), RAW)

    assert exc.value.code == "fees_exceed_refund"
    assert exc.value.customer_message.startswith(
        "Los gastos de la devolución superan el importe de lo que devuelves"
    )
    assert "USD" not in exc.value.customer_message
    assert "76.95 USD" in exc.value.team_reason


async def test_the_approval_key_uses_the_resolved_refund_form() -> None:
    """Una preferencia que la política ignora no distingue dos peticiones; con
    `customer_choice`, sí."""
    from apps.api.agents.nodes.execute_skill import _same_order_action

    shopify = FakeShopify()
    fixed = _policy(refund_method="original_payment")
    silent = await StartReturn().prepare(_ctx(shopify, fixed), RAW)
    ignored = await StartReturn().prepare(
        _ctx(shopify, fixed), {**RAW, "refund_preference": "store_credit"}
    )
    choice = _policy(refund_method="customer_choice")
    money = await StartReturn().prepare(
        _ctx(shopify, choice), {**RAW, "refund_preference": "original_payment"}
    )
    credit = await StartReturn().prepare(
        _ctx(shopify, choice), {**RAW, "refund_preference": "store_credit"}
    )

    assert await _same_order_action({}, silent, ignored, StartReturn) is True
    assert await _same_order_action({}, money, credit, StartReturn) is False
