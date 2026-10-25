"""Modo del adaptador de comercio de un turno (ADR 0015 §2).

- `live`: el ShopifyAdapter real, con las credenciales de la integración del tenant.
- `mock`: el MockShopifyAdapter del simulador, con sus fixtures.
- `demo_catalog`: el catálogo público de una tienda sin credenciales, de solo lectura.

Sin `commerce_mode` en el state se deriva de `simulation_mode`, así que los llamadores
existentes no cambian de comportamiento.
"""

from __future__ import annotations

from typing import Literal, get_args

from apps.api.agents.state import AgentState

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
