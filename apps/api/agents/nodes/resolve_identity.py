"""Nodo: resolve_identity (ADR 0013 §3). Código, sin LLM.

Calcula qué identidad tiene el turno antes de `select_aop` y `reason`: lee la evidencia
que el intake guardó en el mensaje entrante (`messages.metadata.identity_evidence`) y la
convierte en grants `verified`. Nunca usa el perfil `end_customer`, que se enlaza por
heurística.

Salidas al estado:
- `identity`: los grants, solo con hashes.
- `identity_summary`: nivel y métodos, para trazas (sin claims ni contactos).
- `identity_note`: la línea que `reason` ve en el bloque volátil del turno.
- `claim_salt`: sal del tenant con la que se hashean los claims de los pedidos. No sale
  del estado: no está en la allowlist de LangSmith.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import get_tenant_pii_salt
from apps.api.services.identity import (
    default_phone_region,
    evidence_from_state,
    identity_note,
    sender_identity,
)


def make_resolve_identity_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    @guarded(name="resolve_identity")
    async def _node(state: AgentState) -> dict:
        tenant_id = UUID(state["tenant_id"])
        async with tenant_scope(tenant_id) as conn:
            salt = await get_tenant_pii_salt(conn, tenant_id)

        region = default_phone_region(state.get("tenant_config"), state.get("tenant_facts"))
        identity = sender_identity(evidence_from_state(state), salt=salt, region=region)
        return {
            "identity": identity.to_state(),
            "claim_salt": salt,
            "identity_summary": identity.summary(),
            "identity_note": identity_note(identity),
        }

    return _node
