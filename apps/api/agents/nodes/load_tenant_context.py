"""Nodo: load_tenant_context.

Carga `tenant_configurations` + prompt activo + integración commerce si está configurada.
Sin config o prompt, el grafo no puede procesar — setea error.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    get_active_system_prompt,
    get_tenant_by_id,
    get_tenant_configuration,
    get_tenant_facts,
    get_tenant_playbook,
    list_tool_permissions,
)
from apps.api.db.returns_policy import get_current_returns_policy
from apps.api.services.commerce_context import build_commerce_integration_ctx
from apps.api.services.returns_policy import ActivePolicy, parse_stored_policy


def make_load_tenant_context_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
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

            perm_rows = await list_tool_permissions(conn, tenant_id)
            playbook = await get_tenant_playbook(conn, tenant_id)
            facts = await get_tenant_facts(conn, tenant_id)
            stored_policy = await get_current_returns_policy(conn, tenant_id)

            config_dump = config.model_dump(mode="json")
            extra = config_dump.get("extra") or {}
            commerce_ctx = await build_commerce_integration_ctx(
                conn, tenant_id, extra=extra
            )

        # Construir mapa slug → {is_enabled, human_approval_required, threshold_override}
        tool_permissions: dict = {
            p.skill_slug: {
                "is_enabled": p.is_enabled,
                "human_approval_required": p.human_approval_required,
                "threshold_override": p.threshold_override,
                # Opt-out de aprobación humana para L3: solo cuenta si fue reconocido
                # explícitamente. El piso en execute_skill exige approval cuando es False.
                "l3_autonomy_acknowledged": p.l3_autonomy_acknowledged_at is not None,
            }
            for p in perm_rows
        }

        # `build_commerce_integration_ctx` resuelve las creds (descifrado + token
        # exchange Shopify) desde tenant_integrations, o cae a tenant_config.extra.
        # Aquí solo serializamos el IntegrationContext al state (JSON-safe).
        commerce_integration_ctx: dict | None = None
        if commerce_ctx is not None:
            commerce_integration_ctx = {
                "tenant_id": str(commerce_ctx.tenant_id),
                "credentials": commerce_ctx.credentials,
                "config": commerce_ctx.config,
            }

        policy = parse_stored_policy(stored_policy.policy) if stored_policy else None
        returns_policy = (
            ActivePolicy(version=stored_policy.version, policy=policy).to_state()
            if stored_policy and policy
            else None
        )
        # Un escenario del simulador fija su propia política (None = sin configurar), así
        # no depende de la que tenga el tenant.
        fixtures = state.get("simulation_fixtures") or {}
        if state.get("simulation_mode") and "returns_policy" in fixtures:
            raw = fixtures["returns_policy"]
            returns_policy = {"version": 0, "policy": raw} if raw else None

        out: dict = {
            "tenant_config": config_dump,
            "tenant_name": tenant.name,
            "system_prompt": system_prompt,
            "model_used": config.agent_model,
            "tool_permissions": tool_permissions,
            "commerce_integration_ctx": commerce_integration_ctx,
            "tenant_playbook": playbook.model_dump(mode="json") if playbook else None,
            "tenant_facts": facts.data if facts else None,
            "returns_policy": returns_policy,
        }
        # Fallback sin AOPs: el tenant puede opt-in a skills vía tenant_config.extra.
        # select_aop (Sprint 7+) sobreescribe estos si el tenant tiene AOPs configurados.
        if isinstance(extra.get("allowed_skills"), list):
            out["allowed_skills"] = list(extra["allowed_skills"])
        if isinstance(extra.get("max_tool_iterations"), int):
            out["max_tool_iterations"] = extra["max_tool_iterations"]

        if state.get("conversation_id"):
            deps.reasoning_tracker.emit(
                tenant_id=state["tenant_id"],
                conversation_id=state["conversation_id"],
                phase="supervisor",
                event_type="check",
                label="Load context",
                detail={"model": config.agent_model, "tenant": tenant.slug},
                status="done",
            )

        return out

    return _node
