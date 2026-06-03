"""Tests para el redactor del mensaje al cliente tras aprobar/rechazar un L3."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from apps.api.services.approval_reply import (
    _DEFAULT_DONE,
    _FAILED,
    fallback_message,
    generate_customer_reply,
)


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
        assert msg == "¡Listo! Cancelamos tu pedido, cualquier cosa aquí estamos. 😊"

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
