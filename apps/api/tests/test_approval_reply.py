"""Tests para el redactor del mensaje al cliente tras aprobar/rechazar un L3."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from apps.api.services.approval_reply import (
    _DEFAULT_DONE,
    _DEFAULT_DONE_FOLLOWUP,
    _DEFAULT_GATE,
    _DEFAULT_WAITING,
    _FAILED,
    done_followup_message,
    fallback_message,
    gate_message,
    generate_customer_reply,
    waiting_message,
)


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
        from apps.api.services import approval_reply as ar
        from apps.api.services.reply_format import has_emoji

        texts = [
            *ar._SKILL_DONE.values(), *ar._SKILL_GATE.values(), *ar._SKILL_WAITING.values(),
            *ar._SKILL_DONE_FOLLOWUP.values(),
            ar._DEFAULT_DONE, ar._DEFAULT_GATE, ar._DEFAULT_WAITING, ar._DEFAULT_DONE_FOLLOWUP,
        ]
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
