"""Nodo: load_tenant_context.

Carga `tenant_configurations` + prompt activo (`tenant_prompts.is_active=true`).
Sin ambos, el grafo no puede procesar — setea error.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    get_active_system_prompt,
    get_tenant_by_id,
    get_tenant_configuration,
)


def make_load_tenant_context_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    @guarded(name="load_tenant_context")
    async def _node(state: AgentState) -> dict:
        tenant_id = UUID(state["tenant_id"])
        async with tenant_scope(tenant_id) as conn:
            tenant = await get_tenant_by_id(conn, tenant_id)
            if tenant is None:
                return {"error": "tenant_not_found"}
            if tenant.status != "active":
                return {"error": f"tenant_not_active: status={tenant.status}"}

            config = await get_tenant_configuration(conn, tenant_id)
            if config is None:
                return {"error": "tenant_config_missing"}

            system_prompt = await get_active_system_prompt(conn, tenant_id, name="system")
            if not system_prompt:
                return {"error": "no_active_system_prompt"}

        config_dump = config.model_dump(mode="json")
        extra = config_dump.get("extra") or {}

        out: dict = {
            "tenant_config": config_dump,
            "system_prompt": system_prompt,
            "model_used": config.agent_model,
        }
        # Fallback sin AOPs: el tenant puede opt-in a skills vía tenant_config.extra.
        # select_aop (Sprint 7+) sobreescribe estos si el tenant tiene AOPs configurados.
        if isinstance(extra.get("allowed_skills"), list):
            out["allowed_skills"] = list(extra["allowed_skills"])
        if isinstance(extra.get("max_tool_iterations"), int):
            out["max_tool_iterations"] = extra["max_tool_iterations"]
        return out

    return _node
