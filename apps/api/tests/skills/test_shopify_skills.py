"""Tests unitarios para las 5 skills L1 de Shopify.

Como ShopifyAdapter._client() crea un ShopifyClient internamente, el patch
de ShopifyClient sigue capturando la llamada HTTP — sin cambios al mock setup.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.skills.base import SkillContext
from apps.api.skills.shopify._models import OrderSummary
from apps.api.skills.shopify.get_customer_history import (
    GetCustomerHistory,
    GetCustomerHistoryInput,
    GetCustomerHistoryOutput,
)
from apps.api.skills.shopify.get_order_by_email import (
    GetOrderByEmail,
    GetOrderByEmailInput,
    GetOrderByEmailOutput,
)
from apps.api.skills.shopify.get_order_status import (
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

_RAW_ORDER = {
    "id": 1001,
    "name": "#1001",
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

_RAW_CUSTOMER = {
    "id": 3001,
    "email": "cliente@example.com",
    "first_name": "Ana",
    "last_name": "García",
    "orders_count": 3,
    "total_spent": "89.97",
}

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
# get_order_by_email
# ----------------------------------------------------------------


class TestGetOrderByEmail:
    async def test_returns_mapped_orders(self) -> None:
        mock_client = _mock_shopify(get_orders_by_email=[_RAW_ORDER])
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetOrderByEmail().execute(CTX, GetOrderByEmailInput(email="a@b.com"))
        assert isinstance(result, GetOrderByEmailOutput)
        assert result.total_found == 1
        assert isinstance(result.orders[0], OrderSummary)
        assert result.orders[0].order_number == "#1001"
        assert result.orders[0].financial_status == "paid"

    async def test_empty_result(self) -> None:
        mock_client = _mock_shopify(get_orders_by_email=[])
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetOrderByEmail().execute(CTX, GetOrderByEmailInput(email="new@x.com"))
        assert isinstance(result, GetOrderByEmailOutput)
        assert result.total_found == 0
        assert result.orders == []

    async def test_raises_when_shopify_not_configured(self) -> None:
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await GetOrderByEmail().execute(CTX_NO_SHOPIFY, GetOrderByEmailInput(email="a@b.com"))

    async def test_passes_email_to_client(self) -> None:
        mock_client = _mock_shopify(get_orders_by_email=[])
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            await GetOrderByEmail().execute(CTX, GetOrderByEmailInput(email="test@example.com"))
        mock_client.get_orders_by_email.assert_awaited_once_with("test@example.com", limit=10)


# ----------------------------------------------------------------
# get_order_status
# ----------------------------------------------------------------


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

    async def test_returns_not_found_when_order_missing(self) -> None:
        mock_client = _mock_shopify(get_order_by_name=None)
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetOrderStatus().execute(
                CTX, GetOrderStatusInput(order_identifier="#9999")
            )
        assert isinstance(result, OrderDetail)
        assert result.found is False
        assert result.order_id is None
        assert result.fulfillments == []

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


# ----------------------------------------------------------------
# get_product_info
# ----------------------------------------------------------------


class TestGetProductInfo:
    async def test_returns_mapped_products(self) -> None:
        mock_client = _mock_shopify(search_products=[_RAW_PRODUCT])
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

    async def test_raises_when_shopify_not_configured(self) -> None:
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await GetProductInfo().execute(CTX_NO_SHOPIFY, GetProductInfoInput(query="q"))


# ----------------------------------------------------------------
# get_customer_history
# ----------------------------------------------------------------


class TestGetCustomerHistory:
    async def test_returns_customer_and_orders(self) -> None:
        mock_client = _mock_shopify(
            get_customer_by_email=_RAW_CUSTOMER,
            get_orders_by_customer_id=[_RAW_ORDER],
        )
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetCustomerHistory().execute(
                CTX, GetCustomerHistoryInput(email="cliente@example.com")
            )
        assert isinstance(result, GetCustomerHistoryOutput)
        assert result.customer is not None
        assert result.customer.first_name == "Ana"
        assert result.customer.orders_count == 3
        assert result.customer.total_spent == "89.97"
        assert len(result.orders) == 1

    async def test_customer_not_found_returns_empty(self) -> None:
        mock_client = _mock_shopify(get_customer_by_email=None)
        with patch(
            "apps.api.integrations.shopify.ShopifyClient",
            return_value=mock_client,
        ):
            result = await GetCustomerHistory().execute(
                CTX, GetCustomerHistoryInput(email="ghost@x.com")
            )
        assert isinstance(result, GetCustomerHistoryOutput)
        assert result.customer is None
        assert result.orders == []
        # No se llama a get_orders_by_customer_id si el customer no existe
        mock_client.get_orders_by_customer_id.assert_not_awaited()

    async def test_raises_when_shopify_not_configured(self) -> None:
        with pytest.raises(ValueError, match="shopify_not_configured"):
            await GetCustomerHistory().execute(
                CTX_NO_SHOPIFY, GetCustomerHistoryInput(email="x@y.com")
            )


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
            GetOrderByEmail,
            GetOrderStatus,
            GetProductInfo,
            GetCustomerHistory,
            GetShopPolicies,
        ]:
            SkillRegistry.register(cls)

    def test_all_five_skills_registered(self) -> None:
        from apps.api.skills.registry import SkillRegistry

        slugs = {
            "shopify.get_order_by_email",
            "shopify.get_order_status",
            "shopify.get_product_info",
            "shopify.get_customer_history",
            "shopify.get_shop_policies",
        }
        for slug in slugs:
            assert SkillRegistry.get(slug) is not None, f"Missing: {slug}"

    def test_correct_slugs(self) -> None:
        assert GetOrderByEmail.slug == "shopify.get_order_by_email"
        assert GetOrderStatus.slug == "shopify.get_order_status"
        assert GetProductInfo.slug == "shopify.get_product_info"
        assert GetCustomerHistory.slug == "shopify.get_customer_history"
        assert GetShopPolicies.slug == "shopify.get_shop_policies"

    def test_list_for_aop_with_shopify_skills(self) -> None:
        from apps.api.skills.registry import SkillRegistry

        skills = SkillRegistry.list_for_aop([
            "shopify.get_order_by_email",
            "shopify.get_order_status",
        ])
        assert len(skills) == 2
