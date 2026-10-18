"""Tests para el redactor del mensaje al cliente tras aprobar/rechazar un L3."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from apps.api.services.approval_reply import (
    done_followup_message,
    fallback_message,
    gate_message,
    generate_customer_reply,
    waiting_message,
)
from apps.api.services.fixed_texts import LANGUAGE_CODES, fixed_text

_DEFAULT_DONE = fixed_text("done.default", "es")
_DEFAULT_DONE_FOLLOWUP = fixed_text("done_followup.default", "es")
_DEFAULT_GATE = fixed_text("gate.default", "es")
_DEFAULT_WAITING = fixed_text("waiting.default", "es")
_FAILED = fixed_text("failed", "es")


class TestDoneFollowupMessage:
    def test_known_skill_says_already_applied_not_in_review(self) -> None:
        msg = done_followup_message("shopify.update_shipping_address")
        assert "ya quedó aplicado" in msg
        assert "shopify." not in msg
        # No debe contradecir un cambio ya confirmado.
        assert "sigue en revisión" not in msg

    def test_unknown_skill_uses_default(self) -> None:
        assert done_followup_message("shopify.whatever") == _DEFAULT_DONE_FOLLOWUP

    def test_none_uses_default(self) -> None:
        assert done_followup_message(None) == _DEFAULT_DONE_FOLLOWUP


class TestGateMessage:
    def test_known_skill_is_warm_and_contextual(self) -> None:
        msg = gate_message("shopify.update_shipping_address")
        assert "dirección de tu pedido" in msg
        assert "shopify." not in msg
        # No la plantilla robótica antigua.
        assert "requiere revisión por parte de nuestro equipo" not in msg

    def test_unknown_skill_uses_default(self) -> None:
        assert gate_message("shopify.whatever") == _DEFAULT_GATE

    def test_none_uses_default(self) -> None:
        assert gate_message(None) == _DEFAULT_GATE


class TestWaitingMessage:
    def test_known_skill_says_still_in_review(self) -> None:
        msg = waiting_message("shopify.update_shipping_address")
        assert "sigue en revisión" in msg
        assert "shopify." not in msg
        # No repite el gate ("lo paso a mi equipo").
        assert "Lo paso a mi equipo" not in msg

    def test_unknown_skill_uses_default(self) -> None:
        assert waiting_message("shopify.whatever") == _DEFAULT_WAITING

    def test_none_uses_default(self) -> None:
        assert waiting_message(None) == _DEFAULT_WAITING


class TestFallbackMessage:
    def test_success_known_skill(self) -> None:
        msg = fallback_message("shopify.update_shipping_address", success=True)
        assert "dirección de envío" in msg
        assert "shopify." not in msg

    def test_success_unknown_skill_uses_default(self) -> None:
        assert fallback_message("shopify.whatever", success=True) == _DEFAULT_DONE

    def test_failure(self) -> None:
        assert fallback_message("shopify.cancel_order", success=False) == _FAILED

    def test_reject_includes_comment(self) -> None:
        msg = fallback_message("shopify.cancel_order", success=False, reject_comment="No procede.")
        assert "No procede." in msg
        assert "shopify." not in msg


class TestGenerateCustomerReply:
    async def test_no_client_returns_template(self) -> None:
        msg = await generate_customer_reply(None, "shopify.cancel_order", success=True)
        assert msg == "Hemos cancelado tu pedido."

    async def test_uses_llm_text_when_available(self) -> None:
        block = MagicMock()
        block.type = "text"
        block.text = "  ¡Listo! Cancelamos tu pedido, cualquier cosa aquí estamos. 😊  "
        resp = MagicMock()
        resp.content = [block]
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=resp)

        msg = await generate_customer_reply(client, "shopify.cancel_order", success=True)
        assert msg == "¡Listo! Cancelamos tu pedido, cualquier cosa aquí estamos."

    async def test_falls_back_when_llm_raises(self) -> None:
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=RuntimeError("boom"))

        msg = await generate_customer_reply(client, "shopify.cancel_order", success=True)
        assert msg == "Hemos cancelado tu pedido."

    async def test_falls_back_when_no_text_block(self) -> None:
        resp = MagicMock()
        resp.content = []
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=resp)

        msg = await generate_customer_reply(client, "shopify.refund_partial", success=True)
        assert msg == "Hemos procesado el reembolso de tu pedido."


# ----------------------------------------------------------------
# Punto 3 del mini-sprint: la confirmación repite lo que se hizo
# ----------------------------------------------------------------


def test_address_confirmation_restates_new_address() -> None:
    from apps.api.services.approval_reply import fallback_message

    msg = fallback_message(
        "shopify.update_shipping_address",
        success=True,
        output={
            "new_address1": "Calle José Hierro, 18",
            "new_address2": "Portal 5, 1ºA",
            "new_zip": "28702",
            "new_city": "San Sebastián de los Reyes",
            "new_country": "Spain",
        },
    )
    assert "Calle José Hierro, 18, Portal 5, 1ºA, 28702 San Sebastián de los Reyes" in msg


def test_confirmation_without_output_keeps_generic_template() -> None:
    from apps.api.services.approval_reply import fallback_message

    assert fallback_message("shopify.update_shipping_address", success=True) == (
        "Hemos actualizado la dirección de envío de tu pedido."
    )


class TestNoEmojiOrMarkdownToCustomer:
    def test_fixed_texts_have_no_emoji(self) -> None:
        from apps.api.services.fixed_texts import CATALOG
        from apps.api.services.reply_format import has_emoji

        texts = [t for per_language in CATALOG.values() for t in per_language.values()]
        assert texts and not [t for t in texts if has_emoji(t)]

    async def test_llm_reply_is_stripped_but_details_kept_literal(self) -> None:
        block = MagicMock()
        block.type = "text"
        block.text = "**Listo**, ya está 😊"
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=MagicMock(content=[block]))

        msg = await generate_customer_reply(
            client,
            "shopify.update_shipping_address",
            success=True,
            output={"address": {"address1": "Calle *Mayor* 1"}},
        )
        assert msg.startswith("Listo, ya está")
        assert "😊" not in msg


# ----------------------------------------------------------------
# #318: skills que releen el pedido → plantilla fija por resultado, sin LLM
# ----------------------------------------------------------------


class TestOutcomeReplies:
    async def test_outcome_reply_skips_the_llm(self) -> None:
        client = MagicMock()
        client.messages.create = AsyncMock()

        msg = await generate_customer_reply(
            client,
            "shopify.cancel_order",
            success=True,
            output={"order_id": 1001, "outcome": "refund_pending"},
        )

        assert msg == (
            "Hemos cancelado tu pedido. El reembolso a tu método de pago original está en "
            "proceso con la pasarela de pago."
        )
        client.messages.create.assert_not_awaited()

    async def test_failed_refund_promises_the_team_not_the_money(self) -> None:
        msg = await generate_customer_reply(
            None,
            "shopify.cancel_order",
            success=True,
            output={"outcome": "refund_failed", "detail": "CARD_DECLINED"},
        )
        assert msg == (
            "Hemos cancelado tu pedido, pero el reembolso no se ha podido completar de forma "
            "automática. Nuestro equipo ya está avisado y te escribirá en cuanto lo tenga "
            "resuelto."
        )

    async def test_confirmed_address_restates_it_without_delivery_promise(self) -> None:
        msg = await generate_customer_reply(
            None,
            "shopify.update_shipping_address",
            success=True,
            output={
                "outcome": "confirmed",
                "new_address1": "Calle Nueva 42",
                "new_zip": "28001",
                "new_city": "Madrid",
            },
        )
        assert msg == (
            "Hemos actualizado la dirección de envío de tu pedido.\n\n"
            "Nueva dirección de envío: Calle Nueva 42, 28001 Madrid."
        )

    async def test_unconfirmed_address_does_not_restate_it(self) -> None:
        msg = await generate_customer_reply(
            None,
            "shopify.update_shipping_address",
            success=True,
            output={"outcome": "not_confirmed", "new_address1": "Calle Vieja 1"},
        )
        assert msg == (
            "No hemos podido confirmar el cambio de dirección de tu pedido. Nuestro equipo "
            "ya está avisado y te escribirá en cuanto lo tenga resuelto."
        )


# ----------------------------------------------------------------
# Idioma de la conversación: cada mensaje sale en el idioma pedido
# ----------------------------------------------------------------


class TestLanguages:
    def test_gate_waiting_followup_in_english(self) -> None:
        assert gate_message("shopify.cancel_order", "en").startswith("Understood.")
        assert waiting_message("shopify.cancel_order", "en").startswith("Your cancellation")
        assert done_followup_message(None, "en") == (
            "Your request has already been completed. If you need anything else, I'm here."
        )

    def test_unsupported_language_uses_tenant_default_then_spanish(self) -> None:
        assert gate_message("shopify.cancel_order", "de", "ca").startswith("Entesos.")
        assert gate_message("shopify.cancel_order", "de").startswith("Entendido.")

    def test_every_template_exists_in_every_language(self) -> None:
        for language in LANGUAGE_CODES:
            for slug in ("shopify.cancel_order", "shopify.start_return", "shopify.other", None):
                assert gate_message(slug, language)
                assert waiting_message(slug, language)
                assert done_followup_message(slug, language)

    def test_rejection_keeps_the_team_comment_verbatim(self) -> None:
        msg = fallback_message(
            "shopify.cancel_order", success=False, reject_comment="Fuera de plazo.", language="fr"
        )
        assert msg.startswith("Nous avons examiné ta demande")
        assert msg.endswith("Fuera de plazo.")

    async def test_outcome_and_address_details_in_english(self) -> None:
        msg = await generate_customer_reply(
            None,
            "shopify.update_shipping_address",
            success=True,
            output={
                "outcome": "confirmed",
                "new_address1": "Calle Nueva 42",
                "new_zip": "28001",
                "new_city": "Madrid",
            },
            language="en",
        )
        assert msg == (
            "We've updated the shipping address of your order.\n\n"
            "New shipping address: Calle Nueva 42, 28001 Madrid."
        )

    async def test_unsettled_outcome_in_catalan(self) -> None:
        msg = await generate_customer_reply(
            None,
            "shopify.cancel_order",
            success=True,
            output={"outcome": "refund_failed"},
            language="ca",
        )
        assert msg == (
            "Hem cancel·lat la teva comanda, però el reemborsament no s'ha pogut completar de "
            "manera automàtica. El nostre equip ja està avisat i t'escriurà tan bon punt ho "
            "tingui resolt."
        )

    async def test_llm_prompt_asks_for_the_conversation_language(self) -> None:
        block = MagicMock()
        block.type = "text"
        block.text = "All done, we have cancelled your order. Anything else, just ask."
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=MagicMock(content=[block]))

        msg = await generate_customer_reply(
            client, "shopify.cancel_order", success=True, language="en"
        )

        assert msg == "All done, we have cancelled your order. Anything else, just ask."
        sent = client.messages.create.await_args.kwargs
        assert "en inglés" in sent["system"]
        assert sent["messages"][0]["content"] == "We've cancelled your order."

    async def test_llm_reply_in_the_wrong_language_falls_back_to_the_template(self) -> None:
        block = MagicMock()
        block.type = "text"
        block.text = "¡Listo! Hemos cancelado tu pedido, cualquier cosa aquí estamos."
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=MagicMock(content=[block]))

        msg = await generate_customer_reply(
            client, "shopify.cancel_order", success=True, language="en"
        )

        assert msg == "We've cancelled your order."


def _return_output(**plan_overrides: object) -> dict:
    from datetime import UTC, datetime
    from decimal import Decimal

    from apps.api.services.returns import PlanLine, ReturnPlan, Settlement, SettlementLine

    plan = {
        "plan_id": "a" * 32,
        "policy_version": 2,
        "requested_at": datetime(2026, 10, 18, tzinfo=UTC),
        "order_id": 1,
        "order_name": "#1042",
        "reason_code": "talla",
        "reason_label": "Talla",
        "fault": "customer",
        "shopify_reason": "too-small",
        "lines": (
            PlanLine(
                line_item_id=1, fulfillment_line_item_id="gid://x/1", title="Blusa", quantity=1
            ),
        ),
        "exchange_lines": (),
        "evidence": (),
        "shipping_method": "store_label",
        "return_address": None,
        "refund_days": 14,
        "ship_replacement": None,
        "requires_approval": True,
        "settlement": Settlement(
            currency="EUR",
            returned=(SettlementLine(title="Blusa", quantity=1, amount=Decimal("52.15")),),
            exchanged=(),
            shipping_payer="customer",
            fee=Decimal("4.95"),
            fee_pending=None,
            fee_label_cost=False,
            restocking_percent=Decimal("0"),
            restocking_fee=Decimal("0"),
            price_rule="none",
            refund_as="original_payment",
        ),
    }
    plan.update(plan_overrides)
    return {
        "outcome": "confirmed",
        "order_id": 1,
        "plan": ReturnPlan(**plan).model_dump(mode="json"),
    }


def test_opened_return_says_what_happens_next_and_never_that_money_is_back() -> None:
    from apps.api.services.approval_reply import outcome_message

    text = outcome_message("shopify.start_return", _return_output(), "es")

    assert text == (
        "Hemos abierto la devolución de tu pedido.\n\n"
        "Te enviaremos la etiqueta de devolución. Por el envío de vuelta descontaremos "
        "4,95 EUR del reembolso. Cuando recibamos el artículo y lo revisemos, te "
        "devolveremos el dinero en un plazo de 14 días."
    )


def test_customer_ships_to_the_store_address_in_english() -> None:
    from decimal import Decimal

    from apps.api.services.approval_reply import outcome_message
    from apps.api.services.returns import Settlement, SettlementLine

    output = _return_output(
        shipping_method="customer_ships",
        return_address="Calle Mayor 1, Madrid",
        settlement=Settlement(
            currency="EUR",
            returned=(SettlementLine(title="Blusa", quantity=1, amount=Decimal("52.15")),),
            exchanged=(),
            shipping_payer="customer",
            fee=Decimal("0"),
            fee_pending=None,
            fee_label_cost=False,
            restocking_percent=Decimal("0"),
            restocking_fee=Decimal("0"),
            price_rule="none",
            refund_as="original_payment",
        ),
    )

    text = outcome_message("shopify.start_return", output, "en")

    assert text == (
        "We've opened the return for your order.\n\n"
        "Send the item to this address: Calle Mayor 1, Madrid. Return shipping is at your "
        "expense. Once we receive and check the item, we'll refund you within 14 days."
    )


def test_cheaper_exchange_as_store_credit_after_receipt() -> None:
    from decimal import Decimal

    from apps.api.services.approval_reply import outcome_message
    from apps.api.services.returns import PlanExchangeLine, Settlement, SettlementLine

    output = _return_output(
        exchange_lines=(PlanExchangeLine(variant_id=9, title="Blusa M", quantity=1),),
        ship_replacement="after_receipt",
        settlement=Settlement(
            currency="EUR",
            returned=(SettlementLine(title="Blusa", quantity=1, amount=Decimal("52.15")),),
            exchanged=(SettlementLine(title="Blusa M", quantity=1, amount=Decimal("40.00")),),
            shipping_payer="store",
            fee=Decimal("0"),
            fee_pending=None,
            fee_label_cost=False,
            restocking_percent=Decimal("0"),
            restocking_fee=Decimal("0"),
            price_rule="store_credit",
            refund_as="store_credit",
        ),
    )

    text = outcome_message("shopify.start_exchange", output, "es")

    assert text == (
        "Hemos abierto el cambio de tu pedido.\n\n"
        "Te enviaremos la etiqueta de devolución. El envío de vuelta corre de nuestra cuenta. "
        "Te enviaremos el artículo de cambio cuando recibamos el que devuelves. Cuando "
        "recibamos el artículo, te abonaremos 12,15 EUR en crédito de la tienda en un plazo "
        "de 14 días."
    )


def test_an_exchange_the_customer_pays_never_mentions_a_refund() -> None:
    from decimal import Decimal

    from apps.api.services.approval_reply import outcome_message
    from apps.api.services.returns import PlanExchangeLine, Settlement, SettlementLine

    output = _return_output(
        exchange_lines=(PlanExchangeLine(variant_id=9, title="Blusa M", quantity=1),),
        ship_replacement="immediately",
        settlement=Settlement(
            currency="EUR",
            returned=(SettlementLine(title="Blusa", quantity=1, amount=Decimal("52.15")),),
            exchanged=(SettlementLine(title="Blusa M", quantity=1, amount=Decimal("52.15")),),
            shipping_payer="customer",
            fee=Decimal("4.95"),
            fee_pending=None,
            fee_label_cost=False,
            restocking_percent=Decimal("0"),
            restocking_fee=Decimal("0"),
            price_rule="none",
            refund_as="original_payment",
        ),
    )

    text = outcome_message("shopify.start_exchange", output, "es")

    assert "reembolso" not in text
    assert text.endswith(
        "Te quedan por pagar 4,95 EUR, incluidos los gastos de la devolución; nuestro equipo "
        "te indicará cómo hacerlo."
    )
