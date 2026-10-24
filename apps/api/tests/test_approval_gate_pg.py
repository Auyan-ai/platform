"""Gate L3 y escalaciones contra un Postgres REAL (#377, #390, #393).

Corren los nodos `execute_skill` y `escalate` (o `respond`) del turno inbound y los
endpoints del panel sobre la misma base, con la skill falsa de `test_approvals_pg`. Así
se ven las transacciones del gate, de `escalate` y de aprobar/rechazar intercaladas como
en producción. Sin `AUYAN_TEST_DATABASE_URL` se saltan.
"""

# Las fixtures `pool` y `fake_skill` vienen de `test_approvals_pg` (mismo harness).
# ruff: noqa: F811

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from apps.api.agents.graph import route_after_execute_skill
from apps.api.agents.nodes.escalate import make_escalate_node
from apps.api.agents.nodes.execute_skill import make_execute_skill_node
from apps.api.agents.nodes.respond import make_respond_node
from apps.api.db.inbound_jobs import inbound_already_answered
from apps.api.services.approval_reply import done_followup_message

from tests.test_approvals_pg import (  # noqa: F401
    DSN,
    FakeL3,
    Seeded,
    _client,
    fake_skill,
    pool,
)

if TYPE_CHECKING:
    import asyncpg
    from apps.api.agents.dependencies import AgentDependencies

pytestmark = pytest.mark.skipif(not DSN, reason="AUYAN_TEST_DATABASE_URL no configurada")


@pytest.fixture(autouse=True)
def _owner_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    # La identidad del cliente tiene sus propios tests; aquí solo importa el gate.
    monkeypatch.setattr(
        "apps.api.agents.nodes.execute_skill._identity_gate", AsyncMock(return_value=None)
    )


async def _seed_conversation(pool: asyncpg.Pool) -> Seeded:
    """Tenant, operador y una conversación abierta, sin aprobaciones."""
    s = Seeded()
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into tenants (id, slug, name) values ($1, $2, 'Tienda')",
            s.tenant_id,
            f"t-{s.tenant_id.hex[:8]}",
        )
        await conn.execute("insert into auth.users (id) values ($1)", s.user_id)
        await conn.execute(
            "insert into users (id, tenant_id, email, role)"
            " values ($1, $2, 'op@tienda.test', 'tenant_admin')",
            s.user_id,
            s.tenant_id,
        )
        customer_id = await conn.fetchval(
            "insert into end_customers (tenant_id) values ($1) returning id", s.tenant_id
        )
        await conn.execute(
            "insert into conversations (id, tenant_id, end_customer_id, channel, status)"
            " values ($1, $2, $3, 'chat', 'open')",
            s.conversation_id,
            s.tenant_id,
            customer_id,
        )
    return s


async def _inbound(pool: asyncpg.Pool, s: Seeded) -> uuid.UUID:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "insert into messages (tenant_id, conversation_id, role, direction, content)"
            " values ($1, $2, 'customer', 'inbound', 'cancela mi pedido') returning id",
            s.tenant_id,
            s.conversation_id,
        )


def _state(s: Seeded, inbound_id: uuid.UUID, order_id: int) -> dict[str, Any]:
    return {
        "tenant_id": str(s.tenant_id),
        "conversation_id": str(s.conversation_id),
        "inbound_message_id": str(inbound_id),
        "tenant_config": {"extra": {}},
        "channel": "chat",
        "response_language": "es",
        "aop_slug": "pruebas",
        "aop_version": 1,
        "allowed_skills": [FakeL3.slug],
        "tool_permissions": {FakeL3.slug: {"is_enabled": True, "human_approval_required": True}},
        "tool_iterations": 0,
        "max_tool_iterations": 5,
        "tool_results": [],
        "pending_tool_call": {
            "id": "toolu_1",
            "slug": FakeL3.slug,
            "input": {"order_id": order_id},
        },
    }


async def _gate(deps: AgentDependencies, state: dict[str, Any]) -> dict[str, Any]:
    """`execute_skill` del turno: el gate L3 hace COMMIT de lo suyo y devuelve."""
    return {**state, **await make_execute_skill_node(deps)(state)}


async def _finish(deps: AgentDependencies, state: dict[str, Any]) -> dict[str, Any]:
    """El resto del turno tras `execute_skill`: `escalate` o `respond`."""
    route = route_after_execute_skill(state)
    node = make_escalate_node(deps) if route == "escalate" else make_respond_node(deps)
    assert route in ("escalate", "respond"), route
    return {**state, **await node(state), "route": route}


async def _turn(
    pool: asyncpg.Pool, deps: AgentDependencies, s: Seeded, order_id: int = 1001
) -> dict[str, Any]:
    inbound_id = await _inbound(pool, s)
    return await _finish(deps, await _gate(deps, _state(s, inbound_id, order_id)))


async def _open_escalations(pool: asyncpg.Pool, s: Seeded) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select reason from escalations where conversation_id = $1"
            " and status in ('pending', 'claimed') order by created_at",
            s.conversation_id,
        )
    return [r["reason"] for r in rows]


async def _conversation_status(pool: asyncpg.Pool, s: Seeded) -> str:
    async with pool.acquire() as conn:
        return str(
            await conn.fetchval("select status from conversations where id = $1", s.conversation_id)
        )


async def _approvals(pool: asyncpg.Pool, s: Seeded) -> list[tuple[uuid.UUID, str]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select id, status from pending_approvals where conversation_id = $1"
            " order by created_at",
            s.conversation_id,
        )
    return [(r["id"], r["status"]) for r in rows]


# ----------------------------------------------------------------
# #377
# ----------------------------------------------------------------


async def test_repeating_an_approved_l3_answers_without_an_orphan_escalation(
    pool: asyncpg.Pool, fake_skill: type[FakeL3], fake_deps: AgentDependencies
) -> None:
    """#377.1: el cliente vuelve a pedir la L3 ya aprobada y ejecutada. El gate no abre
    `awaiting_human_approval:<id>` (nadie podría cerrarla): contesta que ya está hecho."""
    s = await _seed_conversation(pool)
    first = await _turn(pool, fake_deps, s)
    approval_id = uuid.UUID(first["pending_approval_id"])
    fake_skill.gate.set()
    async with _client(s) as c:
        approved = await c.post(f"/approvals/{approval_id}/approve", json={})
    assert approved.json()["approval_status"] == "approved"
    assert await _open_escalations(pool, s) == []

    second = await _turn(pool, fake_deps, s)

    assert second["route"] == "respond"
    assert second["agent_response"] == done_followup_message(FakeL3.slug, "es")
    assert await _open_escalations(pool, s) == [], "escalación huérfana del gate"
    assert await _approvals(pool, s) == [(approval_id, "approved")]
    assert fake_skill.mutations == 1


async def test_a_turn_that_escalated_counts_as_answered_on_retry(
    pool: asyncpg.Pool, fake_skill: type[FakeL3], fake_deps: AgentDependencies
) -> None:
    """#377.2: el acuse de `escalate` lleva `inbound_message_id`, así que el reintento del
    job no repite el turno ni el acuse."""
    s = await _seed_conversation(pool)
    inbound_id = await _inbound(pool, s)

    out = await _finish(fake_deps, await _gate(fake_deps, _state(s, inbound_id, 1001)))

    assert out["route"] == "escalate"
    async with pool.acquire() as conn:
        assert await inbound_already_answered(
            conn,
            tenant_id=s.tenant_id,
            conversation_id=s.conversation_id,
            inbound_message_id=inbound_id,
        )


# ----------------------------------------------------------------
# #390
# ----------------------------------------------------------------


async def test_the_panel_never_sees_an_approval_without_its_escalation(
    pool: asyncpg.Pool, fake_skill: type[FakeL3], fake_deps: AgentDependencies
) -> None:
    """#390: la aprobación y su escalación nacen en la misma transacción del gate. En
    cuanto el panel puede ver la aprobación, su escalación ya existe."""
    s = await _seed_conversation(pool)

    gated = await _gate(fake_deps, _state(s, await _inbound(pool, s), 1001))

    approval_id = gated["pending_approval_id"]
    assert await _open_escalations(pool, s) == [f"awaiting_human_approval:{approval_id}"]
    assert await _conversation_status(pool, s) == "escalated"
    assert gated["escalation_created"] is True


@pytest.mark.parametrize("reused", [False, True], ids=["nueva", "reusada"])
@pytest.mark.parametrize(
    ("decision", "body", "conversation"),
    [("reject", {"comment": "no procede"}, "open"), ("approve", {}, "resolved")],
)
async def test_a_decision_between_the_gate_and_escalate_leaves_no_orphan_escalation(
    pool: asyncpg.Pool,
    fake_skill: type[FakeL3],
    fake_deps: AgentDependencies,
    reused: bool,
    decision: str,
    body: dict[str, Any],
    conversation: str,
) -> None:
    """#390 (traza de TLC de `NoOrphanEscalation`): el gate hace COMMIT, el operador
    decide y después el turno corre `escalate`. Ninguna escalación queda abierta sobre
    la aprobación resuelta. `reusada`: el gate reutiliza una aprobación pendiente."""
    s = await _seed_conversation(pool)
    if reused:
        await _turn(pool, fake_deps, s)
    fake_skill.gate.set()

    gated = await _gate(fake_deps, _state(s, await _inbound(pool, s), 1001))
    assert gated.get("pending_approval_is_repeat") is reused
    async with _client(s) as c:
        decided = await c.post(f"/approvals/{gated['pending_approval_id']}/{decision}", json=body)
    assert decided.status_code == 200
    await _finish(fake_deps, gated)

    assert await _open_escalations(pool, s) == [], "escalación del gate huérfana"
    assert await _conversation_status(pool, s) == conversation
