"""Tests para las skills L2 de Shopify: add_order_note y tag_order.

ShopifyClient mockeado con AsyncMock — sin llamadas HTTP reales.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.skills.base import SkillContext
from apps.api.skills.shopify.add_order_note import (
    AddOrderNote,
    AddOrderNoteInput,
    AddOrderNoteOutput,
)
from apps.api.skills.shopify.tag_order import (
    TagOrder,
    TagOrderInput,
    TagOrderOutput,
)

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

_ORDER_WITH_NOTE = {
    "id": 1001,
    "note": "Cliente reportó paquete dañado.",
    "tags": "priority",
}

_ORDER_WITH_TAGS = {
    "id": 1001,
    "tags": "damaged, priority, return-requested",
}


# ----------------------------------------------------------------
# AddOrderNote
# ----------------------------------------------------------------


class TestAddOrderNote:
    def test_tier_is_l2(self) -> None:
        assert AddOrderNote.tier == "L2"

    def test_slug(self) -> None:
        assert AddOrderNote.slug == "shopify.add_order_note"

    def test_default_threshold(self) -> None:
        assert AddOrderNote.default_threshold == 0.85

    @pytest.mark.asyncio
    async def test_adds_note_successfully(self) -> None:
        skill = AddOrderNote()
        inputs = AddOrderNoteInput(order_id=1001, note="Cliente reportó paquete dañado.")

        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.get_order_by_name = AsyncMock(return_value=None)
            instance.add_order_note = AsyncMock(return_value=_ORDER_WITH_NOTE)

            result = await skill.execute(CTX, inputs)

        assert isinstance(result, AddOrderNoteOutput)
        assert result.success is True
        assert result.order_id == 1001
        assert result.note == "Cliente reportó paquete dañado."
        instance.add_order_note.assert_awaited_once_with(1001, "Cliente reportó paquete dañado.")

    @pytest.mark.asyncio
    async def test_uses_input_note_as_fallback_if_api_omits_note(self) -> None:
        """Si la API devuelve sin campo note, se usa el input como fallback."""
        skill = AddOrderNote()
        inputs = AddOrderNoteInput(order_id=1001, note="Nota de prueba")

        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.get_order_by_name = AsyncMock(return_value=None)
            instance.add_order_note = AsyncMock(return_value={"id": 1001})  # sin note

            result = await skill.execute(CTX, inputs)

        assert result.note == "Nota de prueba"

    @pytest.mark.asyncio
    async def test_raises_if_shopify_not_configured(self) -> None:
        skill = AddOrderNote()
        inputs = AddOrderNoteInput(order_id=1001, note="Test")

        with pytest.raises(ValueError, match="shopify_not_configured"):
            await skill.execute(CTX_NO_SHOPIFY, inputs)

    def test_to_anthropic_tool_shape(self) -> None:
        skill = AddOrderNote()
        tool = skill.to_anthropic_tool()
        assert tool["name"] == "shopify_add_order_note"
        assert "order_id" in tool["input_schema"]["properties"]
        assert "note" in tool["input_schema"]["properties"]


# ----------------------------------------------------------------
# TagOrder
# ----------------------------------------------------------------


class TestTagOrder:
    def test_tier_is_l2(self) -> None:
        assert TagOrder.tier == "L2"

    def test_slug(self) -> None:
        assert TagOrder.slug == "shopify.tag_order"

    def test_default_threshold(self) -> None:
        assert TagOrder.default_threshold == 0.85

    @pytest.mark.asyncio
    async def test_tags_order_successfully(self) -> None:
        skill = TagOrder()
        inputs = TagOrderInput(order_id=1001, tags=["return-requested", "damaged"])

        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.get_order_by_name = AsyncMock(return_value=None)
            instance.tag_order = AsyncMock(return_value=_ORDER_WITH_TAGS)

            result = await skill.execute(CTX, inputs)

        assert isinstance(result, TagOrderOutput)
        assert result.success is True
        assert result.order_id == 1001
        assert "damaged" in result.current_tags
        assert "return-requested" in result.current_tags
        instance.tag_order.assert_awaited_once_with(1001, ["return-requested", "damaged"])

    @pytest.mark.asyncio
    async def test_empty_tags_string_returns_empty_list(self) -> None:
        """Si el pedido no tiene tags, current_tags debe ser lista vacía."""
        skill = TagOrder()
        inputs = TagOrderInput(order_id=1001, tags=["priority"])

        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.get_order_by_name = AsyncMock(return_value=None)
            instance.tag_order = AsyncMock(return_value={"id": 1001, "tags": ""})

            result = await skill.execute(CTX, inputs)

        assert result.current_tags == []

    @pytest.mark.asyncio
    async def test_raises_if_shopify_not_configured(self) -> None:
        skill = TagOrder()
        inputs = TagOrderInput(order_id=1001, tags=["priority"])

        with pytest.raises(ValueError, match="shopify_not_configured"):
            await skill.execute(CTX_NO_SHOPIFY, inputs)

    def test_to_anthropic_tool_shape(self) -> None:
        skill = TagOrder()
        tool = skill.to_anthropic_tool()
        assert tool["name"] == "shopify_tag_order"
        assert "order_id" in tool["input_schema"]["properties"]
        assert "tags" in tool["input_schema"]["properties"]
