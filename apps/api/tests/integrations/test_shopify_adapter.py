"""Tests del ShopifyAdapter: registry + multi-tenant stateless + protocol coverage.

El smoke test crítico: dos tenants con tiendas distintas pueden coexistir sin
que las credenciales de uno se filtren al otro. Esto valida la fix arquitectónica
del Bloque 0 (singleton ShopifyClient → ShopifyAdapter stateless por IntegrationContext).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.integrations.shopify import ShopifyAdapter

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_adapter_registered_under_commerce_shopify(self) -> None:
        cls = IntegrationRegistry.get("commerce", "shopify")
        assert cls is ShopifyAdapter

    def test_adapter_is_stateless(self) -> None:
        """No tiene credenciales en __init__."""
        a = ShopifyAdapter()
        b = ShopifyAdapter()
        # Ambas instancias son intercambiables — no llevan estado.
        assert a is not b
        # No tiene atributos privados de credenciales.
        assert not hasattr(a, "_domain")
        assert not hasattr(a, "_token")


# ---------------------------------------------------------------------------
# Multi-tenant smoke test — la razón de existir del refactor 0.3
# ---------------------------------------------------------------------------


class TestMultiTenantIsolation:
    @pytest.mark.asyncio
    async def test_two_tenants_use_their_own_credentials(self) -> None:
        """Dos tenants distintos llaman al adapter con sus propias creds.

        Verifica que el adapter NO comparte estado entre llamadas:
        cada `_client(ctx)` construye un ShopifyClient con las creds de ese ctx.
        """
        ctx_tenant_a = IntegrationContext(
            tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
            credentials={"domain": "shop-a.myshopify.com", "token": "shpat_aaa"},
        )
        ctx_tenant_b = IntegrationContext(
            tenant_id=UUID("22222222-2222-2222-2222-222222222222"),
            credentials={"domain": "shop-b.myshopify.com", "token": "shpat_bbb"},
        )

        adapter = ShopifyAdapter()

        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            instance = MockClient.return_value
            instance.get_order = AsyncMock(return_value={"id": 1})

            await adapter.get_order(ctx_tenant_a, "1")
            await adapter.get_order(ctx_tenant_b, "1")

            # ShopifyClient se instanció con las dos credenciales distintas.
            assert MockClient.call_count == 2
            assert MockClient.call_args_list[0].args == ("shop-a.myshopify.com", "shpat_aaa")
            assert MockClient.call_args_list[1].args == ("shop-b.myshopify.com", "shpat_bbb")


# ---------------------------------------------------------------------------
# Protocol coverage — todos los métodos delegan al ShopifyClient subyacente
# ---------------------------------------------------------------------------


_CTX = IntegrationContext(
    tenant_id=UUID("33333333-3333-3333-3333-333333333333"),
    credentials={"domain": "x.myshopify.com", "token": "shpat_x"},
)


class TestAdapterMethods:
    @pytest.mark.asyncio
    async def test_get_order(self) -> None:
        adapter = ShopifyAdapter()
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            inst = MockClient.return_value
            inst.get_order = AsyncMock(return_value={"id": 1001})
            result = await adapter.get_order(_CTX, "1001")
        assert result == {"id": 1001}
        inst.get_order.assert_awaited_once_with(1001)

    @pytest.mark.asyncio
    async def test_search_orders_by_email(self) -> None:
        adapter = ShopifyAdapter()
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            inst = MockClient.return_value
            inst.get_orders_by_email = AsyncMock(return_value=[])
            await adapter.search_orders_by_email(_CTX, "a@b.com", limit=5)
        inst.get_orders_by_email.assert_awaited_once_with("a@b.com", limit=5)

    @pytest.mark.asyncio
    async def test_search_orders_by_phone_reads_the_customer_orders(self) -> None:
        adapter = ShopifyAdapter()
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            inst = MockClient.return_value
            inst.get_customer_by_phone = AsyncMock(return_value={"id": 3001})
            inst.get_orders_by_customer_id = AsyncMock(return_value=[{"id": 1}])
            result = await adapter.search_orders_by_phone(_CTX, "+34600111222", limit=5)
        assert result == [{"id": 1}]
        inst.get_customer_by_phone.assert_awaited_once_with("+34600111222")
        inst.get_orders_by_customer_id.assert_awaited_once_with(3001, limit=5)

    @pytest.mark.asyncio
    async def test_search_orders_by_phone_without_customer_is_empty(self) -> None:
        adapter = ShopifyAdapter()
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            inst = MockClient.return_value
            inst.get_customer_by_phone = AsyncMock(return_value=None)
            inst.get_orders_by_customer_id = AsyncMock()
            result = await adapter.search_orders_by_phone(_CTX, "+34600111222")
        assert result == []
        inst.get_orders_by_customer_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_order_passes_kwargs(self) -> None:
        adapter = ShopifyAdapter()
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            inst = MockClient.return_value
            # Sin pedido por ese 'name' → 1 se trata como id interno (sin resolver).
            inst.get_order_by_name = AsyncMock(return_value=None)
            inst.cancel_order = AsyncMock(return_value={"id": 1})
            await adapter.cancel_order(_CTX, 1, reason="fraud", email=False, refund=True)
        inst.cancel_order.assert_awaited_once_with(1, reason="fraud", email=False, refund=True)

    @pytest.mark.asyncio
    async def test_mutation_resolves_visible_number_to_internal_id(self) -> None:
        """El número visible del pedido (1181) se resuelve al order_id interno
        (7133866033432) antes de mutar. Regresión del 404 del dogfood: las skills
        de mutación pegaban contra /orders/1181.json en vez del id interno."""
        adapter = ShopifyAdapter()
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            inst = MockClient.return_value
            inst.get_order_by_name = AsyncMock(return_value={"id": 7133866033432})
            inst.update_shipping_address = AsyncMock(return_value={"id": 7133866033432})
            await adapter.update_shipping_address(
                _CTX,
                1181,
                address1="Calle Jose Hierro 18",
                city="San Sebastián de los Reyes",
                province="Madrid",
                country="España",
                zip_code="28702",
            )
        inst.get_order_by_name.assert_awaited_once_with("1181")
        # El adapter muta usando el id interno resuelto, no el número visible.
        assert inst.update_shipping_address.await_args.args[0] == 7133866033432

    @pytest.mark.asyncio
    async def test_update_shipping_preserves_order_country_when_omitted(self) -> None:
        """Sin `country` explícito → se conserva el del pedido (no lo inventa el LLM)."""
        adapter = ShopifyAdapter()
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            inst = MockClient.return_value
            inst.get_order_by_name = AsyncMock(
                return_value={"id": 7133, "shipping_address": {"country_code": "PT"}}
            )
            inst.update_shipping_address = AsyncMock(return_value={"id": 7133})
            await adapter.update_shipping_address(
                _CTX,
                1181,
                address1="Rua X 1",
                city="Lisboa",
                province="Lisboa",
                zip_code="1000-001",
            )
        assert inst.update_shipping_address.await_args.kwargs["country"] == "PT"

    @pytest.mark.asyncio
    async def test_update_shipping_falls_back_to_tenant_default_country(self) -> None:
        """Pedido sin país y sin `country` → cae al default_country_code del tenant."""
        adapter = ShopifyAdapter()
        ctx = IntegrationContext(
            tenant_id=UUID("33333333-3333-3333-3333-333333333333"),
            credentials={"domain": "x.myshopify.com", "token": "shpat_x"},
            config={"default_country_code": "ES"},
        )
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            inst = MockClient.return_value
            inst.get_order_by_name = AsyncMock(return_value={"id": 7133})
            inst.update_shipping_address = AsyncMock(return_value={"id": 7133})
            await adapter.update_shipping_address(
                ctx,
                1181,
                address1="Calle X 1",
                city="Madrid",
                province="Madrid",
                zip_code="28001",
            )
        assert inst.update_shipping_address.await_args.kwargs["country"] == "ES"

    @pytest.mark.asyncio
    async def test_update_shipping_explicit_country_is_used(self) -> None:
        """Cambio internacional explícito → se respeta el `country` recibido."""
        adapter = ShopifyAdapter()
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            inst = MockClient.return_value
            inst.get_order_by_name = AsyncMock(return_value={"id": 7133})
            inst.update_shipping_address = AsyncMock(return_value={"id": 7133})
            await adapter.update_shipping_address(
                _CTX,
                1181,
                address1="Rue X 1",
                city="Paris",
                province="Île-de-France",
                zip_code="75001",
                country="Francia",
            )
        assert inst.update_shipping_address.await_args.kwargs["country"] == "Francia"

    @pytest.mark.asyncio
    async def test_update_shipping_reads_order_by_id_when_internal(self) -> None:
        """Si llega el id interno (no resuelve por name), se lee el pedido por id
        para conservar su país."""
        adapter = ShopifyAdapter()
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            inst = MockClient.return_value
            inst.get_order_by_name = AsyncMock(return_value=None)
            inst.get_order = AsyncMock(
                return_value={"id": 7133, "shipping_address": {"country": "Spain"}}
            )
            inst.update_shipping_address = AsyncMock(return_value={"id": 7133})
            await adapter.update_shipping_address(
                _CTX,
                7133,
                address1="Calle X 1",
                city="Madrid",
                province="Madrid",
                zip_code="28001",
            )
        inst.get_order.assert_awaited_once_with(7133)
        assert inst.update_shipping_address.await_args.kwargs["country"] == "Spain"

    @pytest.mark.asyncio
    async def test_resolve_order_id_passthrough_when_already_internal(self) -> None:
        """Si llega un id interno (ningún pedido tiene ese 'name'), se usa tal cual."""
        adapter = ShopifyAdapter()
        with patch("apps.api.integrations.shopify.ShopifyClient") as MockClient:
            inst = MockClient.return_value
            inst.get_order_by_name = AsyncMock(return_value=None)
            resolved = await adapter._resolve_order_id(_CTX, 7133866033432)
        assert resolved == 7133866033432

    @pytest.mark.asyncio
    async def test_missing_credentials_raises_error(self) -> None:
        """Si las creds están mal armadas, falla al construir el cliente — no en silencio.

        Sin access_token/token → ValueError; sin domain → KeyError. Ambos válidos,
        lo importante es que falle ruidosamente para que se vea en logs.
        """
        ctx_bad = IntegrationContext(
            tenant_id=UUID("44444444-4444-4444-4444-444444444444"),
            credentials={},
        )
        adapter = ShopifyAdapter()
        with pytest.raises((KeyError, ValueError)):
            await adapter.get_order(ctx_bad, "1")
