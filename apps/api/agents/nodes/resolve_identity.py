"""Nodo: resolve_identity (ADR 0013 §3). Código, sin LLM.

Calcula qué identidad tiene el turno antes de `select_aop` y `reason`:
1. Remitente: la evidencia que el intake guardó en el mensaje entrante
   (`messages.metadata.identity_evidence`) se convierte en grants `verified`. Nunca usa el
   perfil `end_customer`, que se enlaza por heurística.
2. Invitado: carga los grants `guest` vigentes de la conversación y, con los datos que el
   cliente aportó en sus mensajes (número de pedido + email o teléfono), comprueba en
   código los pares nuevos contra el pedido. Si ninguno coincide y no hay remitente
   verificado, el turno termina con un texto fijo y no corre `reason`.

Salidas al estado:
- `identity`: los grants, solo con hashes.
- `identity_summary`: nivel y métodos, para trazas (sin claims ni contactos).
- `identity_note`: la línea que `reason` ve en el bloque volátil del turno.
- `identity_missing`: qué falta para tocar pedidos.
- `claim_salt`: sal del tenant con la que se hashean los claims de los pedidos. No sale
  del estado: no está en la allowlist de LangSmith.
- Con un texto fijo: `decision="respond"`, `agent_response` y `awaiting_customer_reply`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.nodes.execute_skill import build_skill_context
from apps.api.agents.state import AgentState
from apps.api.db.client import tenant_scope
from apps.api.db.queries import get_tenant_pii_salt
from apps.api.services.identity import (
    IdentityContext,
    default_phone_region,
    evidence_from_state,
    identity_note,
    sender_identity,
)
from apps.api.services.identity_guest import (
    GuestRound,
    can_lookup_orders,
    candidate_pairs,
    guest_facts,
    load_guest_grants,
    missing_data,
    provided_from_history,
    run_guest_checks,
)
from apps.api.skills.shopify.get_order_status import map_order_detail


def make_resolve_identity_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    @guarded(name="resolve_identity")
    async def _node(state: AgentState) -> dict:
        tenant_id = UUID(state["tenant_id"])
        conversation_id = UUID(state["conversation_id"]) if state.get("conversation_id") else None
        region = default_phone_region(state.get("tenant_config"), state.get("tenant_facts"))

        provided = provided_from_history(
            state.get("conversation_history"),
            region=region,
            order_pattern=(state.get("tenant_facts") or {}).get("order_name_pattern"),
        )
        round_ = GuestRound()
        async with tenant_scope(tenant_id) as conn:
            salt = await get_tenant_pii_salt(conn, tenant_id)
            sender = sender_identity(evidence_from_state(state), salt=salt, region=region)
            guest_grants = (
                await load_guest_grants(conn, tenant_id, conversation_id)
                if conversation_id is not None and not state.get("simulation_mode")
                else ()
            )
            identity = IdentityContext((*sender.grants, *guest_grants))
            pairs = [] if state.get("simulation_mode") else candidate_pairs(provided)
            ctx = build_skill_context({**state, "claim_salt": salt})  # type: ignore[typeddict-item]
            if pairs and conversation_id is not None and can_lookup_orders(ctx):
                round_ = await run_guest_checks(
                    conn,
                    ctx,
                    pairs,
                    policy=ctx.guest_policy,
                    tenant_facts=ctx.tenant_facts,
                )

        identity = IdentityContext((*identity.grants, *round_.grants))
        missing = [] if identity.has_grant() else missing_data(provided)
        out: dict[str, Any] = {
            "identity": identity.to_state(),
            "claim_salt": salt,
            "identity_summary": identity.summary(),
            "identity_note": identity_note(identity, missing),
            "identity_missing": missing,
        }
        if round_.orders:
            details = [map_order_detail(o).model_dump(mode="json") for o in round_.orders]
            out["known_facts"] = guest_facts(state.get("known_facts"), details)
        if round_.reply is not None and not identity.has_grant("verified"):
            out.update(
                decision="respond",
                agent_response=round_.reply,
                awaiting_customer_reply=True,
            )
        return out

    return _node
