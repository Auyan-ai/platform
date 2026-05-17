"""Tests unitarios para ShopifyClient — httpx mockeado con AsyncMock."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from apps.api.integrations.shopify import ShopifyClient

DOMAIN = "myshop.myshopify.com"
TOKEN = "shpat_test_token"


def _mock_httpx(json_data: dict) -> tuple[MagicMock, AsyncMock]:
    """Devuelve (mock_cm, mock_http_client) con response.json() → json_data."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client.post = AsyncMock(return_value=resp)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm, mock_client


# ----------------------------------------------------------------
# Datos de fixtures
# ----------------------------------------------------------------

_ORDER = {
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

_PRODUCT = {
    "id": 2001,
    "title": "Camiseta Auyan",
    "body_html": "<p>Descripción del producto.</p>",
    "product_type": "Ropa",
    "status": "active",
    "variants": [
        {"title": "Small", "price": "19.99", "inventory_quantity": 5},
        {"title": "Large", "price": "19.99", "inventory_quantity": 0},
    ],
}

_CUSTOMER = {
    "id": 3001,
    "email": "cliente@example.com",
    "first_name": "Ana",
    "last_name": "García",
    "orders_count": 3,
    "total_spent": "89.97",
}

_POLICY = {
    "title": "Política de devolución",
    "body": "<p>Aceptamos devoluciones en 30 días.</p>",
    "url": "https://myshop.com/policies/refund-policy",
}


# ----------------------------------------------------------------
# Tests de Orders
# ----------------------------------------------------------------


class TestGetOrder:
    async def test_returns_order_dict(self) -> None:
        mock_cm, mock_client = _mock_httpx({"order": _ORDER})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_order(1001)
        assert result["id"] == 1001
        mock_client.get.assert_awaited_once()
        url = mock_client.get.call_args[0][0]
        assert "/orders/1001.json" in url


class TestGetOrderByName:
    async def test_returns_order_when_found(self) -> None:
        mock_cm, mock_client = _mock_httpx({"orders": [_ORDER]})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_order_by_name("#1001")
        assert result is not None
        assert result["id"] == 1001

    async def test_returns_none_when_not_found(self) -> None:
        mock_cm, _ = _mock_httpx({"orders": []})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_order_by_name("#9999")
        assert result is None

    async def test_normalizes_name_without_hash(self) -> None:
        mock_cm, mock_client = _mock_httpx({"orders": [_ORDER]})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_order_by_name("1001")
        assert result is not None
        params = mock_client.get.call_args.kwargs.get("params", {})
        assert params["name"] == "#1001"


class TestGetOrdersByEmail:
    async def test_returns_orders_list(self) -> None:
        mock_cm, mock_client = _mock_httpx({"orders": [_ORDER]})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_orders_by_email("test@example.com")
        assert len(result) == 1
        assert result[0]["id"] == 1001

    async def test_passes_email_and_limit_params(self) -> None:
        mock_cm, mock_client = _mock_httpx({"orders": []})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            await ShopifyClient(DOMAIN, TOKEN).get_orders_by_email("x@y.com", limit=5)
        params = mock_client.get.call_args.kwargs.get("params", {})
        assert params["email"] == "x@y.com"
        assert params["limit"] == 5

    async def test_empty_result(self) -> None:
        mock_cm, _ = _mock_httpx({"orders": []})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_orders_by_email("noone@x.com")
        assert result == []


# ----------------------------------------------------------------
# Tests de Products
# ----------------------------------------------------------------


class TestSearchProducts:
    async def test_returns_products_list(self) -> None:
        mock_cm, mock_client = _mock_httpx({"products": [_PRODUCT]})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).search_products("camiseta")
        assert len(result) == 1
        assert result[0]["title"] == "Camiseta Auyan"

    async def test_passes_query_and_active_status(self) -> None:
        mock_cm, mock_client = _mock_httpx({"products": []})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            await ShopifyClient(DOMAIN, TOKEN).search_products("zapato")
        params = mock_client.get.call_args.kwargs.get("params", {})
        assert params["title"] == "zapato"
        assert params["status"] == "active"


# ----------------------------------------------------------------
# Tests de Customers
# ----------------------------------------------------------------


class TestGetCustomerByEmail:
    async def test_returns_customer_when_found(self) -> None:
        mock_cm, _ = _mock_httpx({"customers": [_CUSTOMER]})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_customer_by_email("cliente@example.com")
        assert result is not None
        assert result["id"] == 3001

    async def test_returns_none_when_not_found(self) -> None:
        mock_cm, _ = _mock_httpx({"customers": []})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_customer_by_email("ghost@example.com")
        assert result is None

    async def test_query_uses_email_prefix(self) -> None:
        mock_cm, mock_client = _mock_httpx({"customers": []})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            await ShopifyClient(DOMAIN, TOKEN).get_customer_by_email("test@example.com")
        params = mock_client.get.call_args.kwargs.get("params", {})
        assert params["query"] == "email:test@example.com"


class TestGetOrdersByCustomerId:
    async def test_returns_orders(self) -> None:
        mock_cm, mock_client = _mock_httpx({"orders": [_ORDER]})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_orders_by_customer_id(3001)
        assert len(result) == 1
        url = mock_client.get.call_args[0][0]
        assert "/customers/3001/orders.json" in url


# ----------------------------------------------------------------
# Tests de Policies
# ----------------------------------------------------------------


class TestGetPolicies:
    async def test_returns_policies_list(self) -> None:
        mock_cm, _ = _mock_httpx({"policies": [_POLICY]})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_policies()
        assert len(result) == 1
        assert result[0]["title"] == "Política de devolución"

    async def test_empty_policies(self) -> None:
        mock_cm, _ = _mock_httpx({"policies": []})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_policies()
        assert result == []


# ----------------------------------------------------------------
# Tests de autenticación
# ----------------------------------------------------------------


class TestAuth:
    async def test_token_in_headers(self) -> None:
        mock_cm, mock_client = _mock_httpx({"orders": []})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            await ShopifyClient(DOMAIN, "mytoken").get_orders_by_email("x@x.com")
        headers = mock_client.get.call_args.kwargs.get("headers", {})
        assert headers.get("X-Shopify-Access-Token") == "mytoken"

    async def test_domain_strips_trailing_slash(self) -> None:
        mock_cm, mock_client = _mock_httpx({"orders": []})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            await ShopifyClient("myshop.myshopify.com/", TOKEN).get_orders_by_email("x@x.com")
        url = mock_client.get.call_args[0][0]
        assert "myshop.myshopify.com//" not in url
