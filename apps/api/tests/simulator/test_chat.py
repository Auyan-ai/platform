"""Probar agente: sesión, turno, tope diario y permisos. Sin base de datos ni LLM."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from apps.api.core.errors import NotFoundError, register_exception_handlers
from apps.api.core.security import AuthContext, get_auth_context
from apps.api.db.models import SimulationRun
from apps.api.routers.simulations import router
from apps.api.simulator import chat
from apps.api.simulator.cost_guard import SimulationBudgetExceeded
from apps.api.tests.conftest import TENANT_ID, make_fake_tenant_scope
from fastapi import FastAPI
from fastapi.testclient import TestClient

USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
HEADERS = {"X-Tenant-Id": str(TENANT_ID)}


class FakeStore:
    """Una fila de `simulation_runs` y las conversaciones creadas, en memoria."""

    def __init__(self) -> None:
        self.conversations: list[dict[str, Any]] = []
        self.run: SimulationRun | None = None
        self.customer_messages: list[str] = []
        self.states: list[dict[str, Any]] = []

    async def create_end_customer(self, conn: Any, **kw: Any) -> Any:
        return SimpleNamespace(id=uuid4())

    async def create_conversation(self, conn: Any, **kw: Any) -> Any:
        self.conversations.append(kw)
        return SimpleNamespace(id=uuid4())

    async def insert_interactive_run(self, conn: Any, **kw: Any) -> SimulationRun:
        self.run = SimulationRun(
            id=uuid4(),
            tenant_id=kw["tenant_id"],
            aop_slug=kw["aop_slug"],
            conversation_id=kw["conversation_id"],
            status="running",
            termination_reason="interactive",
            turns_count=0,
            transcript=[],
            cost_cents=0,
            triggered_by=kw["triggered_by"],
        )
        return self.run

    async def get_simulation_run(self, conn: Any, tenant_id: UUID, run_id: UUID) -> Any:
        return self.run if self.run and self.run.id == run_id else None

    async def append_interactive_turn(
        self,
        conn: Any,
        run_id: UUID,
        tenant_id: UUID,
        *,
        entries: list,
        cost_cents: float,
        tokens_agent: int,
    ) -> SimulationRun:
        run = self.run
        assert run is not None
        self.run = run.model_copy(
            update={
                "transcript": (run.transcript or []) + entries,
                "turns_count": (run.turns_count or 0) + 1,
                "cost_cents": (run.cost_cents or 0) + cost_cents,
            }
        )
        return self.run


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    s = FakeStore()
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(chat, "tenant_scope", make_fake_tenant_scope(conn))
    for name in (
        "create_end_customer",
        "create_conversation",
        "insert_interactive_run",
        "get_simulation_run",
        "append_interactive_turn",
    ):
        monkeypatch.setattr(chat, name, getattr(s, name))

    async def persist(tenant_id: UUID, conversation_id: UUID, content: str) -> None:
        s.customer_messages.append(content)

    monkeypatch.setattr(chat, "_persist_customer_message", persist)
    monkeypatch.setattr(chat, "_persist_escalation_ack", AsyncMock())
    monkeypatch.setattr(chat, "list_skill_audit_log", AsyncMock(return_value=[]))
    monkeypatch.setattr(chat, "ensure_simulation_budget", AsyncMock())

    @contextmanager
    def fake_ledger():
        yield SimpleNamespace(overlay=lambda st: st, cost_usd=0.0, calls=[])

    monkeypatch.setattr(chat, "open_ledger", fake_ledger)
    return s


def graph_returning(store: FakeStore, final: dict[str, Any]) -> Any:
    async def ainvoke(state: dict[str, Any]) -> dict[str, Any]:
        store.states.append(state)
        return {**state, **final}

    return SimpleNamespace(ainvoke=ainvoke)


async def test_create_chat_makes_simulation_conversation_and_interactive_run(store: FakeStore):
    run = await chat.create_chat(TENANT_ID, triggered_by=USER_ID)

    assert store.conversations[0]["is_simulation"] is True
    assert store.conversations[0]["channel"] == "chat"
    assert run.status == "running"
    assert run.termination_reason == "interactive"
    assert run.triggered_by == USER_ID


async def test_message_turn_returns_decision_and_accumulates_cost(store: FakeStore):
    run = await chat.create_chat(TENANT_ID, triggered_by=USER_ID)
    answer = graph_returning(
        store,
        {"decision": "respond", "agent_response": "19,90 €", "cost_usd": 0.02, "tokens_in": 10},
    )
    escalate = graph_returning(
        store,
        {
            "decision": "escalate",
            "agent_response": "",
            "escalation_reason": "order_lookup_not_available",
            "cost_usd": 0.01,
        },
    )

    turn = await chat.send_message(
        TENANT_ID, run.id, "¿Envío a Canarias?", graph=answer, observability=None
    )
    turn2 = await chat.send_message(
        TENANT_ID, run.id, "¿Dónde está mi pedido?", graph=escalate, observability=None
    )

    assert (turn.decision, turn.response_text, turn.cost_cents) == ("respond", "19,90 €", 2.0)
    assert turn2.decision == "escalate"
    assert turn2.escalation_reason == "order_lookup_not_available"
    assert turn2.session_cost_cents == pytest.approx(3.0)
    assert store.run is not None and store.run.cost_cents == pytest.approx(3.0)
    agent_entries = [e for e in store.run.transcript or [] if e["role"] == "agent"]
    assert [e["decision"] for e in agent_entries] == ["respond", "escalate"]
    assert store.customer_messages == ["¿Envío a Canarias?", "¿Dónde está mi pedido?"]


async def test_turn_runs_in_simulation_mode_so_nothing_is_delivered(store: FakeStore):
    run = await chat.create_chat(TENANT_ID, triggered_by=None)
    graph = graph_returning(store, {"decision": "respond", "agent_response": "hola"})

    await chat.send_message(TENANT_ID, run.id, "hola", graph=graph, observability=None)

    state = store.states[0]
    assert state["simulation_mode"] is True
    assert state["channel"] == "chat"
    assert state["simulation_identity"] == "chat"
    assert "commerce_mode" not in state


async def test_budget_exhausted_stops_before_running_graph(
    store: FakeStore, monkeypatch: pytest.MonkeyPatch
):
    run = await chat.create_chat(TENANT_ID, triggered_by=None)
    monkeypatch.setattr(
        chat,
        "ensure_simulation_budget",
        AsyncMock(side_effect=SimulationBudgetExceeded("tope", retry_after=60)),
    )
    graph = graph_returning(store, {"decision": "respond", "agent_response": "x"})

    with pytest.raises(SimulationBudgetExceeded):
        await chat.send_message(TENANT_ID, run.id, "hola", graph=graph, observability=None)

    assert store.states == []
    assert store.customer_messages == []


async def test_graph_failure_is_recorded_as_error_turn(store: FakeStore):
    run = await chat.create_chat(TENANT_ID, triggered_by=None)

    async def boom(state: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("fallo")

    turn = await chat.send_message(
        TENANT_ID, run.id, "hola", graph=SimpleNamespace(ainvoke=boom), observability=None
    )

    assert turn.decision == "error"
    assert turn.error == "graph_invoke_failed"
    assert store.run is not None and store.run.turns_count == 1


async def test_unknown_chat_is_not_found(store: FakeStore):
    with pytest.raises(NotFoundError):
        await chat.get_chat(TENANT_ID, uuid4())


# ─── Router ───────────────────────────────────────────────────────────────────


def make_client(role: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=USER_ID,
        tenant_id=None if role == "super_admin" else TENANT_ID,
        role=role,  # type: ignore[arg-type]
        email="k@auyan.ai",
    )
    monkeypatch.setattr(
        "apps.api.routers.simulations._get_deps",
        lambda: SimpleNamespace(observability=None),
    )
    monkeypatch.setattr("apps.api.routers.simulations._get_graph", lambda: None)
    return TestClient(app)


def test_tenant_admin_gets_403_on_every_chat_endpoint(
    store: FakeStore, monkeypatch: pytest.MonkeyPatch
):
    client = make_client("tenant_admin", monkeypatch)
    cid = uuid4()

    assert client.post("/simulations/chats", headers=HEADERS).status_code == 403
    posted = client.post(
        f"/simulations/chats/{cid}/messages", json={"text": "hola"}, headers=HEADERS
    )
    assert posted.status_code == 403
    assert client.get(f"/simulations/chats/{cid}", headers=HEADERS).status_code == 403


def test_super_admin_full_flow_and_cap_returns_429(
    store: FakeStore, monkeypatch: pytest.MonkeyPatch
):
    client = make_client("super_admin", monkeypatch)
    graph = graph_returning(
        store, {"decision": "respond", "agent_response": "30 días", "cost_usd": 0.01}
    )
    monkeypatch.setattr("apps.api.routers.simulations._get_graph", lambda: graph)

    created = client.post("/simulations/chats", headers=HEADERS)
    assert created.status_code == 200
    chat_id = created.json()["id"]

    reply = client.post(
        f"/simulations/chats/{chat_id}/messages", json={"text": "¿Cuántos días?"}, headers=HEADERS
    )
    assert reply.status_code == 200
    assert reply.json()["response_text"] == "30 días"
    assert reply.json()["decision"] == "respond"

    transcript = client.get(f"/simulations/chats/{chat_id}", headers=HEADERS).json()
    assert [t["role"] for t in transcript["turns"]] == ["customer", "agent"]
    assert transcript["cost_cents"] == pytest.approx(1.0)

    monkeypatch.setattr(
        chat,
        "ensure_simulation_budget",
        AsyncMock(side_effect=SimulationBudgetExceeded("tope", retry_after=60)),
    )
    capped = client.post(
        f"/simulations/chats/{chat_id}/messages", json={"text": "otra"}, headers=HEADERS
    )
    assert capped.status_code == 429
    assert len(store.states) == 1
