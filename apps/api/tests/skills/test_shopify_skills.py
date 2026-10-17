"""Tests unitarios para las skills L1 de Shopify.

Como ShopifyAdapter._client() crea un ShopifyClient internamente, el patch
de ShopifyClient sigue capturando la llamada HTTP — sin cambios al mock setup.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.skills.base import SkillContext
from apps.api.skills.shopify._models import Money, OrderSummary
from apps.api.skills.shopify.get_order_status import (
    NOT_FOUND_NOTE,
    GetOrderStatus,
    GetOrderStatusInput,
    OrderDetail,
)
from apps.api.skills.shopify.get_product_info import (
    GetProductInfo,
    GetProductInfoInput,
    GetProductInfoOutput,
)
from apps.api.skills.shopify.get_shop_policies import (
    GetShopPolicies,
    GetShopPoliciesInput,
    GetShopPoliciesOutput,
)
from apps.api.skills.shopify.list_my_orders import (
    NO_VERIFIED_SENDER_NOTE,
    ListMyOrders,
    ListMyOrdersInput,
    ListMyOrdersOutput,
)
from apps.api.tests.identity_support import verified_context

# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------

_SHOPIFY_INTEGRATION_CTX = IntegrationContext(
    tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
    credentials={"domain": "myshop.myshopify.com", "token": "shpat_test"},
)

OWNER_EMAIL = "cliente@example.com"

# Remitente verificado: el dueño de los pedidos de prueba escribe desde su email.
CTX = verified_context(email=OWNER_EMAIL, integration_ctx=_SHOPIFY_INTEGRATION_CTX)

# Otro remitente verificado: no es dueño de ningún pedido de prueba.
CTX_OTHER_SENDER = verified_context(email="ajeno@example.com", integration_ctx=_SHOPIFY_INTEGRATION_CTX)

# Sin remitente verificado (ticket de chat): no hay grants.
CTX_NO_SENDER = verified_context(channel="zendesk", integration_ctx=_SHOPIFY_INTEGRATION_CTX)

CTX_PHONE_SENDER = verified_context(
    phone="+34600111222", channel="whatsapp", integration_ctx=_SHOPIFY_INTEGRATION_CTX
)

CTX_NO_SHOPIFY = SkillContext(
    tenant_id="11111111-1111-1111-1111-111111111111",
    conversation_id="22222222-2222-2222-2222-222222222222",
)

_RAW_ORDER = {
    "id": 1001,
    "name": "#1001",
    "email": OWNER_EMAIL,
    "financial_status": "paid",
    "fulfillment_status": "fulfilled",
    "total_price": "29.99",
    "currency": "USD",
    "created_at": "2026-05-01T10:00:00Z",
    "fulfillments": [
        {
            "status": "success",
            "tracking_number": "TRACK123",
            "tracking_url": "https://track.example.com/TRACK123",
            "tracking_urls": ["https://track.example.com/TRACK123"],
            "tracking_company": "UPS",
        }
    ],
}

# Tienda en EUR, cliente de UK que paga en GBP (Shopify Markets): `total_price` y
# `price` planos vienen en la moneda de la tienda; los `_set` traen ambas.
_RAW_ORDER_EUR_SHOP_PAID_GBP = {
    "id": 1002,
    "name": "#1002",
    "email": OWNER_EMAIL,
    "financial_status": "paid",
    "fulfillment_status": None,
    "total_price": "52.00",
    "currency": "EUR",
    "presentment_currency": "GBP",
    "total_price_set": {
        "shop_money": {"amount": "52.00", "currency_code": "EUR"},
        "presentment_money": {"amount": "45.00", "currency_code": "GBP"},
    },
    "created_at": "2026-05-02T10:00:00Z",
    "fulfillments": [],
    "line_items": [
        {
            "id": 7001,
            "title": "Bolso Tote Piel",
            "quantity": 1,
            "price": "52.00",
            "price_set": {
                "shop_money": {"amount": "52.00", "currency_code": "EUR"},
                "presentment_money": {"amount": "45.00", "currency_code": "GBP"},
            },
        }
    ],
}

_RAW_PRODUCT = {
    "id": 2001,
    "title": "Camiseta Auyan",
    "body_html": "<p>Descripción <b>del</b> producto.</p>",
    "product_type": "Ropa",
    "status": "active",
    "variants": [
        {"title": "Small", "price": "19.99", "inventory_quantity": 5},
        {"title": "Large", "price": "19.99", "inventory_quantity": 0},
    ],
}

_RAW_ORDER_OTHER_CUSTOMER = {
    **_RAW_ORDER,
    "id": 1003,
    "name": "#1003",
    "email": "ajeno@example.com",
}

_RAW_CUSTOMER = {"id": 3001, "email": OWNER_EMAIL, "phone": "+34600111222"}

_RAW_POLICY = {
    "title": "Política de devolución",
    "body": "<p>Aceptamos devoluciones en 30 días.</p>",
    "url": "https://myshop.com/policies/refund-policy",
}


def _mock_shopify(**method_results: object) -> AsyncMock:
    """Crea un mock de ShopifyClient con los métodos dados."""
    mock = AsyncMock()
    for method, result in method_results.items():
        getattr(mock, method).return_value = result
    return mock


# ----------------------------------------------------------------
# list_my_orders
# ----------------------------------------------------------------


class TestListMyOrders:
    async def test_lists_the_verified_sender_orders(self) -> None:
        mock_client = _mock_shopify(get_orders_by_email=[_RAW_ORDER])
        with patch("apps.api.integrations.shopify.ShopifyClient", return_value=mock_client):
            result = await ListMyOrders().execute(CTX, ListMyOrdersInput())
        assert isinstance(result, ListMyOrdersOutput)
        assert result.verified_sender is True
        assert result.total_found == 1
        assert isinstance(result.orders[0], OrderSummary)
        assert result.orders[0].order_number == "#1001"
        assert result.orders[0].financial_status == "paid"
        mock_client.get_orders_by_email.assert_awaited_once_with(OWNER_EMAIL, limit=10)

    async def test_ignores_an_email_the_llm_sends(self) -> None:
        mock_client = _mock_shopify(get_orders_by_email=[_RAW_ORDER])
        with patch("apps.api.integrations.shopify.ShopifyClient", return_value=mock_client):
            await ListMyOrders().execute(
                CTX, ListMyOrdersInput.model_validate({"email": "ajeno@example.com"})
            )
        mock_client.get_orders_by_email.assert_awaited_once_with(OWNER_EMAIL, limit=10)

    async def test_drops_orders_of_another_customer(self) -> None:
        mock_client = _mock_shopify(get_orders_by_email=[_RAW_ORDER, _RAW_ORDER_OTHER_CUSTOMER])
        with patch("apps.api.integrations.shopify.ShopifyClient", return_value=mock_client):
            result = await ListMyOrders().execute(CTX, ListMyOrdersInput())
        assert [o.order_number for o in result.orders] == ["#1001"]
        assert result.total_found == 1

    async def test_chat_origin_gets_nothing(self) -> None:
        mock_client = _mock_shopify(get_orders_by_email=[_RAW_ORDER])
        with patch("apps.api.integrations.shopify.ShopifyClient", return_value=mock_client):
            result = await ListMyOrders().execute(CTX_NO_SENDER, ListMyOrdersInput())
        assert result == ListMyOrdersOutput(
            verified_sender=False, orders=[], total_found=0, note=NO_VERIFIED_SENDER_NOTE
        )
        mock_client.get_orders_by_email.assert_not_awaited()

    async def test_whatsapp_sender_lists_orders_by_phone(self) -> None:
        own = {**_RAW_ORDER, "email": None, "phone": "+34 600 11 12 22"}
        other = {**_RAW_ORDER_OTHER_CUSTOMER, "phone": "+34699999999"}
        mock_client = _mock_shopify(
            get_customer_by_phone=_RAW_CUSTOMER, get_orders_by_customer_id=[own, other]
        )
        with patch("apps.api.integrations.shopify.ShopifyClient", return_value=mock_client):
            result = await ListMyOrders().execute(CTX_PHONE_SENDER, ListMyOrdersInput())
        assert [o.order_number for o in result.orders] == ["#1001"]
        mock_client.get_customer_by_phone.assert_awaited_once_with("+34600111222")
        mock_client.get_orders_by_customer_id.assert_awaited_once_with(3001, limit=10)

    async def test_whatsapp_sender_without_shopify_customer_gets_empty_list(self) -> None:
        mock_client = _mock_shopify(get_customer_by_phone=None)
        with patch("apps.api.integrations.shopify.ShopifyClient", return_value=mock_client):
            result = await ListMyOrders().execute(CTX_PHONE_SENDER, ListMyOrdersInput())
        assert (result.verified_sender, result.orders) == (True, [])
        mock_client.get_orders_by_customer_id.assert_not_awaited()

    async def test_eur_shop_order_paid_in_gbp_exposes_gbp(self) -> None:
        mock_client = _mock_shopify(get_orders_by_email=[_RAW_ORDER_EUR_SHOP_PAID_GBP])
        with patch("apps.api.integrations.shopify.ShopifyClient", return_value=mock_client):
            result = await ListMyOrders().execute(CTX, ListMyOrdersInput())
        assert result.orders[0].total == Money(amount="45.00", currency="GBP")
        assert result.orders[0].total_in_shop_currency == Money(amount="52.00", currency="EUR")

    async def test_raises_when_shopify_not_configured(self) -> None:
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await ListMyOrders().execute(CTX_NO_SHOPIFY, ListMyOrdersInput())


# ----------------------------------------------------------------
# get_order_status
# ----------------------------------------------------------------


_NOT_FOUND_DUMP = {
    "found": False,
    "order_id": None,
    "order_number": None,
    "financial_status": None,
    "fulfillment_status": None,
    "total": None,
    "total_in_shop_currency": None,
    "created_at": None,
    "fulfilled_at": None,
    "delivered_at": None,
    "fulfillments": [],
    "line_items": [],
    "shipping_address": None,
    "note": NOT_FOUND_NOTE,
}


class TestGetOrderStatus:
    async def test_returns_order_detail_when_found(self) -> None:
        mock_client = _mock_shopify(get_order_by_name=_RAW_ORDER)
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetOrderStatus().execute(
                CTX, GetOrderStatusInput(order_identifier="#1001")
            )
        assert isinstance(result, OrderDetail)
        assert result.found is True
        assert result.order_number == "#1001"
        assert result.financial_status == "paid"
        assert len(result.fulfillments) == 1
        assert result.fulfillments[0].tracking_number == "TRACK123"

    async def test_order_in_shop_currency_exposes_total_with_its_currency(self) -> None:
        mock_client = _mock_shopify(get_order_by_name=_RAW_ORDER)
        with patch("apps.api.integrations.shopify.ShopifyClient", return_value=mock_client):
            result = await GetOrderStatus().execute(
                CTX, GetOrderStatusInput(order_identifier="#1001")
            )
        assert result.total == Money(amount="29.99", currency="USD")
        assert result.total_in_shop_currency is None

    async def test_eur_shop_order_paid_in_gbp_exposes_gbp(self) -> None:
        mock_client = _mock_shopify(get_order_by_name=_RAW_ORDER_EUR_SHOP_PAID_GBP)
        with patch("apps.api.integrations.shopify.ShopifyClient", return_value=mock_client):
            result = await GetOrderStatus().execute(
                CTX, GetOrderStatusInput(order_identifier="#1002")
            )
        assert result.total == Money(amount="45.00", currency="GBP")
        assert result.total_in_shop_currency == Money(amount="52.00", currency="EUR")
        assert result.line_items[0].price == Money(amount="45.00", currency="GBP")

    async def test_returns_not_found_when_order_missing(self) -> None:
        mock_client = _mock_shopify(get_order_by_name=None)
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetOrderStatus().execute(
                CTX, GetOrderStatusInput(order_identifier="#9999")
            )
        assert result.model_dump() == _NOT_FOUND_DUMP

    async def test_raises_when_shopify_not_configured(self) -> None:
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await GetOrderStatus().execute(
                CTX_NO_SHOPIFY, GetOrderStatusInput(order_identifier="#1")
            )

    async def test_order_without_fulfillments(self) -> None:
        raw = {**_RAW_ORDER, "fulfillments": []}
        mock_client = _mock_shopify(get_order_by_name=raw)
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetOrderStatus().execute(
                CTX, GetOrderStatusInput(order_identifier="#1001")
            )
        assert isinstance(result, OrderDetail)
        assert result.fulfillments == []
        assert result.fulfilled_at is None
        assert result.delivered_at is None

    async def test_exposes_fulfilled_and_delivered_dates(self) -> None:
        """fulfilled_at = envío del primer fulfillment; delivered_at = entrega
        cuando el carrier marca shipment_status='delivered'."""
        raw = {
            **_RAW_ORDER,
            "fulfillments": [
                {
                    "status": "success",
                    "tracking_number": "TRACK123",
                    "tracking_company": "UPS",
                    "shipment_status": "delivered",
                    "created_at": "2026-05-02T10:00:00Z",
                    "updated_at": "2026-05-05T14:00:00Z",
                }
            ],
        }
        mock_client = _mock_shopify(get_order_by_name=raw)
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetOrderStatus().execute(
                CTX, GetOrderStatusInput(order_identifier="#1001")
            )
        assert result.fulfilled_at == "2026-05-02T10:00:00Z"
        assert result.delivered_at == "2026-05-05T14:00:00Z"
        assert result.fulfillments[0].shipment_status == "delivered"

    async def test_fulfilled_without_delivery_signal(self) -> None:
        """Enviado pero sin shipment_status delivered → fulfilled_at sí, delivered_at no."""
        raw = {
            **_RAW_ORDER,
            "fulfillments": [
                {
                    "status": "success",
                    "tracking_number": "T1",
                    "created_at": "2026-05-02T10:00:00Z",
                    "updated_at": "2026-05-02T10:00:00Z",
                }
            ],
        }
        mock_client = _mock_shopify(get_order_by_name=raw)
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetOrderStatus().execute(
                CTX, GetOrderStatusInput(order_identifier="#1001")
            )
        assert result.fulfilled_at == "2026-05-02T10:00:00Z"
        assert result.delivered_at is None


# ----------------------------------------------------------------
# get_product_info
# ----------------------------------------------------------------


class TestGetProductInfo:
    async def test_returns_mapped_products(self) -> None:
        mock_client = _mock_shopify(search_products=[_RAW_PRODUCT], get_shop_currency="USD")
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetProductInfo().execute(
                CTX, GetProductInfoInput(query="camiseta")
            )
        assert isinstance(result, GetProductInfoOutput)
        assert result.total_found == 1
        p = result.products[0]
        assert p.title == "Camiseta Auyan"
        assert p.product_type == "Ropa"
        assert len(p.variants) == 2
        assert p.variants[0].available is True
        assert p.variants[1].available is False
        assert p.variants[0].price == Money(amount="19.99", currency="USD")
        assert "Descripción" in p.description_snippet
        assert "<p>" not in p.description_snippet  # HTML eliminado

    async def test_empty_result(self) -> None:
        mock_client = _mock_shopify(search_products=[])
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetProductInfo().execute(CTX, GetProductInfoInput(query="xyz"))
        assert isinstance(result, GetProductInfoOutput)
        assert result.total_found == 0
        mock_client.get_shop_currency.assert_not_awaited()

    async def test_fails_rather_than_return_prices_without_currency(self) -> None:
        mock_client = _mock_shopify(search_products=[_RAW_PRODUCT], get_shop_currency="")
        with (
            patch("apps.api.integrations.shopify.ShopifyClient", return_value=mock_client),
            pytest.raises(ValueError, match="shop_currency_unavailable"),
        ):
            await GetProductInfo().execute(CTX, GetProductInfoInput(query="camiseta"))

    async def test_raises_when_shopify_not_configured(self) -> None:
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await GetProductInfo().execute(CTX_NO_SHOPIFY, GetProductInfoInput(query="q"))


# ----------------------------------------------------------------
# get_shop_policies
# ----------------------------------------------------------------


class TestGetShopPolicies:
    async def test_returns_all_policies(self) -> None:
        mock_client = _mock_shopify(get_policies=[_RAW_POLICY])
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetShopPolicies().execute(CTX, GetShopPoliciesInput())
        assert isinstance(result, GetShopPoliciesOutput)
        assert len(result.policies) == 1
        assert result.policies[0].title == "Política de devolución"
        assert "<p>" not in result.policies[0].body  # HTML eliminado
        assert "devoluciones" in result.policies[0].body

    async def test_filters_by_policy_type(self) -> None:
        shipping_policy = {
            "title": "Política de envío",
            "body": "Envíos en 3-5 días.",
            "url": "https://myshop.com/policies/shipping-policy",
        }
        mock_client = _mock_shopify(get_policies=[_RAW_POLICY, shipping_policy])
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetShopPolicies().execute(
                CTX, GetShopPoliciesInput(policy_type="shipping-policy")
            )
        assert len(result.policies) == 1
        assert result.policies[0].title == "Política de envío"

    async def test_unknown_policy_type_returns_every_policy(self) -> None:
        # Un tipo que no está en ningún URL no deja al agente sin políticas (DE-01).
        mock_client = _mock_shopify(get_policies=[_RAW_POLICY])
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetShopPolicies().execute(
                CTX, GetShopPoliciesInput(policy_type="envios")
            )
        assert [p.title for p in result.policies] == [_RAW_POLICY["title"]]

    async def test_empty_policies(self) -> None:
        mock_client = _mock_shopify(get_policies=[])
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetShopPolicies().execute(CTX, GetShopPoliciesInput())
        assert result.policies == []

    async def test_raises_when_shopify_not_configured(self) -> None:
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await GetShopPolicies().execute(CTX_NO_SHOPIFY, GetShopPoliciesInput())


# ----------------------------------------------------------------
# Registro automático
# ----------------------------------------------------------------


class TestSkillsRegistered:
    """Verifica que las 5 skills tienen los slugs correctos y se pueden registrar.

    Nota: test_registry.py usa un fixture autouse que limpia el registry global
    después de cada test. Por eso re-registramos explícitamente aquí en vez de
    depender de la importación inicial del módulo.
    """

    @pytest.fixture(autouse=True)
    def _populate(self) -> None:
        from apps.api.skills.registry import SkillRegistry

        for cls in [
            ListMyOrders,
            GetOrderStatus,
            GetProductInfo,
            GetShopPolicies,
        ]:
            SkillRegistry.register(cls)

    def test_all_read_skills_registered(self) -> None:
        from apps.api.skills.registry import SkillRegistry

        slugs = {
            "shopify.list_my_orders",
            "shopify.get_order_status",
            "shopify.get_product_info",
            "shopify.get_shop_policies",
        }
        for slug in slugs:
            assert SkillRegistry.get(slug) is not None, f"Missing: {slug}"

    def test_correct_slugs(self) -> None:
        assert ListMyOrders.slug == "shopify.list_my_orders"
        assert GetOrderStatus.slug == "shopify.get_order_status"
        assert GetProductInfo.slug == "shopify.get_product_info"
        assert GetShopPolicies.slug == "shopify.get_shop_policies"

    def test_list_for_aop_with_shopify_skills(self) -> None:
        from apps.api.skills.registry import SkillRegistry

        skills = SkillRegistry.list_for_aop([
            "shopify.list_my_orders",
            "shopify.get_order_status",
        ])
        assert len(skills) == 2
