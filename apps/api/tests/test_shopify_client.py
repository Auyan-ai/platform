"""Tests unitarios para ShopifyClient — httpx mockeado con AsyncMock."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apps.api.integrations.commerce import country_to_iso2
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
    mock_client.put = AsyncMock(return_value=resp)

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


class TestGetCustomerByPhone:
    async def test_returns_customer_when_found(self) -> None:
        mock_cm, _ = _mock_httpx({"customers": [_CUSTOMER]})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_customer_by_phone("+34600111222")
        assert result is not None
        assert result["id"] == 3001

    async def test_returns_none_when_not_found(self) -> None:
        mock_cm, _ = _mock_httpx({"customers": []})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            result = await ShopifyClient(DOMAIN, TOKEN).get_customer_by_phone("+34699999999")
        assert result is None

    async def test_query_uses_phone_prefix(self) -> None:
        mock_cm, mock_client = _mock_httpx({"customers": []})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            await ShopifyClient(DOMAIN, TOKEN).get_customer_by_phone("+34600111222")
        params = mock_client.get.call_args.kwargs.get("params", {})
        assert params["query"] == "phone:+34600111222"


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


# ----------------------------------------------------------------
# Validación de credenciales
# ----------------------------------------------------------------


class TestGetShopCurrency:
    async def test_returns_shop_currency(self) -> None:
        mock_cm, mock_client = _mock_httpx({"shop": {"currency": "USD"}})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            currency = await ShopifyClient(DOMAIN, TOKEN).get_shop_currency()
        assert currency == "USD"
        assert mock_client.get.call_args.kwargs["params"] == {"fields": "currency"}


class TestValidate:
    async def test_returns_shop_on_success(self) -> None:
        mock_cm, mock_client = _mock_httpx({"shop": {"name": "Marea", "email": "ops@marea.io"}})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            shop = await ShopifyClient(DOMAIN, TOKEN).validate()
        assert shop["name"] == "Marea"
        url = mock_client.get.call_args[0][0]
        assert "/shop.json" in url

    async def test_raises_on_invalid_credentials(self) -> None:
        import httpx

        resp = MagicMock()
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=MagicMock())
        )
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            with pytest.raises(httpx.HTTPStatusError):
                await ShopifyClient(DOMAIN, "bad").validate()


class TestEnsureShopifyAccessToken:
    """Cache EN MEMORIA del access_token corto — nunca se persiste en DB."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):  # type: ignore[no-untyped-def]
        from apps.api.integrations import shopify

        shopify._token_cache.clear()
        yield
        shopify._token_cache.clear()

    async def test_exchanges_and_caches_in_memory(self) -> None:
        from uuid import uuid4

        from apps.api.integrations.shopify import ensure_shopify_access_token

        tid = uuid4()
        exch = AsyncMock(return_value=("shpat_abc", 86400))
        with patch("apps.api.integrations.shopify.exchange_client_credentials", exch):
            t1, _ = await ensure_shopify_access_token(
                tenant_id=tid, domain="x.myshopify.com", client_id="c", client_secret="s"
            )
            t2, _ = await ensure_shopify_access_token(
                tenant_id=tid, domain="x.myshopify.com", client_id="c", client_secret="s"
            )

        # La segunda llamada sale del cache en memoria, sin re-exchange.
        assert t1 == t2 == "shpat_abc"
        exch.assert_awaited_once()

    async def test_refreshes_when_cached_token_expired(self) -> None:
        import datetime as dt
        from uuid import uuid4

        from apps.api.integrations import shopify
        from apps.api.integrations.shopify import ensure_shopify_access_token

        tid = uuid4()
        past = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
        shopify._token_cache_set(tid, "shpat_old", past)

        exch = AsyncMock(return_value=("shpat_new", 86400))
        with patch("apps.api.integrations.shopify.exchange_client_credentials", exch):
            token, _ = await ensure_shopify_access_token(
                tenant_id=tid, domain="x.myshopify.com", client_id="c", client_secret="s"
            )

        assert token == "shpat_new"
        exch.assert_awaited_once()

    def test_cache_is_bounded_by_maxsize(self) -> None:
        import datetime as dt
        from uuid import uuid4

        from apps.api.integrations import shopify

        future = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
        for _ in range(shopify._TOKEN_CACHE_MAXSIZE + 50):
            shopify._token_cache_set(uuid4(), "shpat_x", future)

        assert len(shopify._token_cache) == shopify._TOKEN_CACHE_MAXSIZE


# ----------------------------------------------------------------
# Normalización de país (Shopify rechaza country en texto libre)
# ----------------------------------------------------------------


class TestCountryToIso2:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("España", "ES"),
            ("españa", "ES"),
            ("espana", "ES"),
            ("Spain", "ES"),
            ("  spain  ", "ES"),
            ("ES", "ES"),
            ("es", "ES"),
            ("Francia", "FR"),
            ("Portugal", "PT"),
            ("Marte", None),
            ("", None),
        ],
    )
    def test_resolves_or_none(self, raw: str, expected: str | None) -> None:
        assert country_to_iso2(raw) == expected


class TestUpdateShippingAddress:
    async def test_sends_country_code_when_resolvable(self) -> None:
        mock_cm, mock_client = _mock_httpx({"order": _ORDER})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            await ShopifyClient(DOMAIN, TOKEN).update_shipping_address(
                1001,
                address1="Calle Dogfood 42",
                city="Madrid",
                province="Madrid",
                country="España",
                zip_code="28001",
            )
        sent = mock_client.put.call_args.kwargs["json"]["order"]["shipping_address"]
        assert sent["country_code"] == "ES"
        assert "country" not in sent  # no se manda el texto libre que Shopify rechaza

    async def test_falls_back_to_country_when_unknown(self) -> None:
        mock_cm, mock_client = _mock_httpx({"order": _ORDER})
        with patch("apps.api.integrations.shopify.httpx.AsyncClient", return_value=mock_cm):
            await ShopifyClient(DOMAIN, TOKEN).update_shipping_address(
                1001,
                address1="X",
                city="Y",
                province="Z",
                country="Narnia",
                zip_code="00000",
            )
        sent = mock_client.put.call_args.kwargs["json"]["order"]["shipping_address"]
        assert sent["country"] == "Narnia"
        assert "country_code" not in sent
