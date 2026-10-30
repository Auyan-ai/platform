"""Modo y adapter de comercio de un turno (ADR 0015 §2, ADR 0016 §2).

- `live`: el adapter que el `IntegrationRegistry` tiene para el proveedor de la integración
  del tenant, con sus credenciales.
- `mock`: el MockShopifyAdapter del simulador, con sus fixtures.
- `demo_catalog`: el catálogo público de una tienda sin credenciales, de solo lectura.

Sin `commerce_mode` en el state se deriva de `simulation_mode`, así que los llamadores
existentes no cambian de comportamiento.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, get_args
from uuid import UUID

from apps.api.agents.state import AgentState
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.commerce import CommerceAdapter
from apps.api.services.commerce_context import commerce_adapter

logger = logging.getLogger(__name__)

CommerceMode = Literal["live", "mock", "demo_catalog"]


def commerce_mode(state: AgentState) -> CommerceMode:
    explicit = state.get("commerce_mode")
    if explicit is None:
        return "mock" if state.get("simulation_mode") else "live"
    if explicit not in get_args(CommerceMode):
        raise ValueError(f"invalid_commerce_mode: {explicit!r}")
    return explicit


def demo_catalog_domain(state: AgentState) -> str:
    domain = state.get("demo_catalog_domain")
    if not domain:
        raise ValueError("demo_catalog_domain_missing")
    return domain


def _integration_from_state(state: AgentState) -> IntegrationContext | None:
    """El `IntegrationContext` que `load_tenant_context` serializó al state."""
    data: dict[str, Any] | None = state.get("commerce_integration_ctx")
    if not data:
        return None
    return IntegrationContext(
        tenant_id=UUID(data["tenant_id"]),
        credentials=data["credentials"],
        config=data.get("config", {}),
        provider=data.get("provider"),
    )


def resolve_commerce(
    state: AgentState,
) -> tuple[IntegrationContext | None, CommerceAdapter | None]:
    """La integración y el adapter de comercio del turno. `(None, None)` en `live` sin
    integración: las skills de comercio fallan con `commerce_not_configured`.

    Un proveedor sin adapter registrado es un error de configuración del tenant: se loguea
    como error y el turno sigue sin comercio, para que las preguntas que no tocan pedidos
    no escalen todas."""
    integration = _integration_from_state(state)
    mode = commerce_mode(state)
    if mode == "mock":
        from apps.api.simulator.mocks import MockShopifyAdapter

        fixtures = (state.get("simulation_fixtures") or {}).get("shopify", {})
        return integration, MockShopifyAdapter(fixtures)
    if mode == "demo_catalog":
        from apps.api.integrations.demo_catalog_registry import demo_catalog_for

        domain = demo_catalog_domain(state)
        # Nunca las credenciales del tenant: la demo solo trae el dominio público.
        demo = IntegrationContext(
            tenant_id=UUID(state["tenant_id"]),
            credentials={},
            config={"store_domain": domain},
        )
        return demo, demo_catalog_for(domain, state.get("demo_catalog_platform"))
    if integration is None:
        return None, None
    try:
        return integration, commerce_adapter(integration)
    except ValueError as exc:
        logger.error(
            "commerce_adapter_unresolved tenant_id=%s provider=%r: %s",
            integration.tenant_id,
            integration.provider,
            exc,
        )
        return None, None
