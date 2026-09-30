"""Tests unitarios para integrations/registry.py."""

from __future__ import annotations

import pytest
from apps.api.integrations.registry import IntegrationRegistry


@pytest.fixture(autouse=True)
def clean_registry():
    """Registry vacío durante el test y restaurado al terminar: los adapters reales
    (registrados al importar su módulo) no deben desaparecer para el resto de la suite."""
    saved = dict(IntegrationRegistry._registry)
    IntegrationRegistry._reset()
    yield
    IntegrationRegistry._reset()
    IntegrationRegistry._registry.update(saved)


class TestRegister:
    def test_register_y_get_ok(self) -> None:
        @IntegrationRegistry.register(kind="helpdesk", provider="acme")
        class AcmeAdapter:
            pass

        assert IntegrationRegistry.get("helpdesk", "acme") is AcmeAdapter

    def test_decorador_devuelve_la_clase_original(self) -> None:
        @IntegrationRegistry.register(kind="commerce", provider="shopify")
        class ShopifyAdapter:
            pass

        assert ShopifyAdapter.__name__ == "ShopifyAdapter"

    def test_registro_multiple_kinds(self) -> None:
        @IntegrationRegistry.register(kind="helpdesk", provider="zendesk")
        class ZendeskAdapter:
            pass

        @IntegrationRegistry.register(kind="commerce", provider="shopify")
        class ShopifyAdapter:
            pass

        assert IntegrationRegistry.get("helpdesk", "zendesk") is ZendeskAdapter
        assert IntegrationRegistry.get("commerce", "shopify") is ShopifyAdapter

    def test_sobreescritura_de_registro(self) -> None:
        @IntegrationRegistry.register(kind="helpdesk", provider="acme")
        class AcmeV1:
            pass

        @IntegrationRegistry.register(kind="helpdesk", provider="acme")
        class AcmeV2:
            pass

        assert IntegrationRegistry.get("helpdesk", "acme") is AcmeV2


class TestGet:
    def test_get_unknown_lanza_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown_integration"):
            IntegrationRegistry.get("helpdesk", "nonexistent")

    def test_get_wrong_kind_lanza_error(self) -> None:
        @IntegrationRegistry.register(kind="helpdesk", provider="gorgias")
        class GorgiasAdapter:
            pass

        with pytest.raises(ValueError, match="unknown_integration"):
            IntegrationRegistry.get("commerce", "gorgias")


class TestListForKind:
    def test_list_for_kind_vacio(self) -> None:
        assert IntegrationRegistry.list_for_kind("helpdesk") == []

    def test_list_for_kind_devuelve_solo_su_kind(self) -> None:
        @IntegrationRegistry.register(kind="helpdesk", provider="chatwoot")
        class ChatwootAdapter:
            pass

        @IntegrationRegistry.register(kind="helpdesk", provider="zendesk")
        class ZendeskAdapter:
            pass

        @IntegrationRegistry.register(kind="commerce", provider="shopify")
        class ShopifyAdapter:
            pass

        result = IntegrationRegistry.list_for_kind("helpdesk")
        providers = [p for p, _ in result]
        assert sorted(providers) == ["chatwoot", "zendesk"]
        assert ShopifyAdapter not in [c for _, c in result]

    def test_list_for_kind_ordenado_por_provider(self) -> None:
        @IntegrationRegistry.register(kind="helpdesk", provider="zendesk")
        class ZendeskAdapter:
            pass

        @IntegrationRegistry.register(kind="helpdesk", provider="chatwoot")
        class ChatwootAdapter:
            pass

        result = IntegrationRegistry.list_for_kind("helpdesk")
        providers = [p for p, _ in result]
        assert providers == sorted(providers)


class TestAllRegistered:
    def test_all_registered_vacio(self) -> None:
        assert IntegrationRegistry.all_registered() == []

    def test_all_registered_incluye_todos(self) -> None:
        @IntegrationRegistry.register(kind="helpdesk", provider="gorgias")
        class GorgiasAdapter:
            pass

        @IntegrationRegistry.register(kind="commerce", provider="shopify")
        class ShopifyAdapter:
            pass

        all_items = IntegrationRegistry.all_registered()
        kinds_providers = {(k, p) for k, p, _ in all_items}
        assert ("helpdesk", "gorgias") in kinds_providers
        assert ("commerce", "shopify") in kinds_providers


class TestReset:
    def test_reset_limpia_todos_los_registros(self) -> None:
        @IntegrationRegistry.register(kind="helpdesk", provider="acme")
        class AcmeAdapter:
            pass

        IntegrationRegistry._reset()

        with pytest.raises(ValueError):
            IntegrationRegistry.get("helpdesk", "acme")

    def test_reset_permite_registrar_de_nuevo(self) -> None:
        @IntegrationRegistry.register(kind="helpdesk", provider="acme")
        class AcmeV1:
            pass

        IntegrationRegistry._reset()

        @IntegrationRegistry.register(kind="helpdesk", provider="acme")
        class AcmeV2:
            pass

        assert IntegrationRegistry.get("helpdesk", "acme") is AcmeV2
