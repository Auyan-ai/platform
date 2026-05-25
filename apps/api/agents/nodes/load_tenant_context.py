"""Nodo: load_tenant_context.

Carga `tenant_configurations` + prompt activo + integración commerce si está configurada.
Sin config o prompt, el grafo no puede procesar — setea error.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import (
    get_active_system_prompt,
    get_integration_credentials_encrypted,
    get_primary_integration_for_kind,
    get_tenant_by_id,
    get_tenant_configuration,
    get_tenant_facts,
    get_tenant_playbook,
    list_tool_permissions,
)
from apps.api.services.integrations_crypto import decrypt_credentials, get_integration_crypto_key

logger = logging.getLogger(__name__)


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

            perm_rows = await list_tool_permissions(conn, tenant_id)
            playbook = await get_tenant_playbook(conn, tenant_id)
            facts = await get_tenant_facts(conn, tenant_id)
            commerce_integration = await get_primary_integration_for_kind(
                conn, tenant_id=tenant_id, kind="commerce"
            )
            commerce_encrypted: bytes | None = None
            if commerce_integration:
                commerce_encrypted = await get_integration_credentials_encrypted(
                    conn,
                    tenant_id=tenant_id,
                    integration_id=commerce_integration.id,
                )

        config_dump = config.model_dump(mode="json")
        extra = config_dump.get("extra") or {}

        # Construir mapa slug → {is_enabled, human_approval_required, threshold_override}
        tool_permissions: dict = {
            p.skill_slug: {
                "is_enabled": p.is_enabled,
                "human_approval_required": p.human_approval_required,
                "threshold_override": p.threshold_override,
            }
            for p in perm_rows
        }

        # Construir commerce_integration_ctx: primero desde tenant_integrations,
        # fallback a tenant_config.extra para tenants no migrados aún.
        commerce_integration_ctx: dict | None = None
        if commerce_integration and commerce_encrypted:
            try:
                from apps.api.core.config import get_settings
                key = get_integration_crypto_key(get_settings())
                creds = json.loads(decrypt_credentials(commerce_encrypted, key).decode())
                commerce_integration_ctx = {
                    "tenant_id": str(tenant_id),
                    "credentials": creds,
                    "config": commerce_integration.config or {},
                }
            except Exception:
                logger.warning(
                    "commerce_integration_decrypt_failed tenant_id=%s", tenant_id
                )
        if commerce_integration_ctx is None:
            shopify_domain = extra.get("shopify_domain")
            shopify_token = extra.get("shopify_token")
            if shopify_domain and shopify_token:
                commerce_integration_ctx = {
                    "tenant_id": str(tenant_id),
                    "credentials": {"domain": shopify_domain, "token": shopify_token},
                    "config": {},
                }

        out: dict = {
            "tenant_config": config_dump,
            "system_prompt": system_prompt,
            "model_used": config.agent_model,
            "tool_permissions": tool_permissions,
            "commerce_integration_ctx": commerce_integration_ctx,
            "tenant_playbook": playbook.model_dump(mode="json") if playbook else None,
            "tenant_facts": facts.data if facts else None,
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
