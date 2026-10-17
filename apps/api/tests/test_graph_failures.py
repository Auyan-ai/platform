"""#362: un nodo del turno que lanza SIEMPRE termina en escalación con razón explícita.

Recorre el grafo real (`build_graph` + `AgentService`) y, para cada nodo de
`TURN_NODES`, fuerza una excepción en ese nodo. El turno debe acabar escalado por
`handle_error` con la razón `agent_error: <nodo>: RuntimeError: …`, un log ERROR, el
acuse fijo del chat y la traza con el error (span del nodo y cierre del trace).

Estructura, no disciplina: si alguien añade un nodo al grafo sin pasar por
`TURN_NODES`, o a `TURN_NODES` sin escenario que lo alcance aquí, estos tests fallan.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.agents import graph as graph_module
from apps.api.agents.graph import GRAPH_RECURSION_LIMIT, TURN_NODES, build_graph
from apps.api.agents.nodes.handle_error import make_handle_error_node
from apps.api.agents.service import AgentService
from apps.api.db.models import TenantToolPermission
from apps.api.services.fixed_texts import fixed_text
from apps.api.services.inbound_media import chat_escalation_ack
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry

from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    ESCALATION_ID,
    INBOUND_MSG_ID,
    TENANT_ID,
    FakeAnthropicResponse,
    make_escalation,
    make_tenant_configuration,
)
from tests.test_graph_e2e import _patch_all_db_and_llm

_RESPOND = FakeAnthropicResponse(
    {"decision": "respond", "confidence": 0.92, "response_text": "Envíos en 3-5 días."}
)
_ESCALATE = FakeAnthropicResponse(
    {
        "decision": "escalate",
        "confidence": 0.95,
        "response_text": "Te paso con el equipo.",
        "escalation_reason": "customer_requested_human",
    }
)
_ASK_READ = FakeAnthropicResponse({}, tool_name="test_read", tool_id="toolu_read")
_ASK_WRITE = FakeAnthropicResponse({}, tool_name="test_write", tool_id="toolu_write")

# Respuesta del LLM que hace que el turno pase por cada nodo.
_SCENARIOS: dict[str, FakeAnthropicResponse] = {
    "load_tenant_context": _RESPOND,
    "load_conversation": _RESPOND,
    "resolve_identity": _RESPOND,
    "select_aop": _RESPOND,
    "retrieve_knowledge": _RESPOND,
    "reason": _RESPOND,
    "respond": _RESPOND,
    "escalate": _ESCALATE,
    "execute_skill": _ASK_READ,
    "supervise": _ASK_WRITE,
}


class _NoInput(SkillInput):
    pass


class _Done(SkillOutput):
    ok: bool


def _skill(slug: str, tier: SkillTier) -> type[Skill]:
    class _TestSkill(Skill):
        description = "Test."
        input_schema = _NoInput
        output_schema = _Done
        default_threshold = 0.70

        async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
            return _Done(ok=True)

    _TestSkill.slug = slug
    _TestSkill.tier = tier
    return _TestSkill


def _permission(slug: str) -> TenantToolPermission:
    return TenantToolPermission(
        id=TENANT_ID,
        tenant_id=TENANT_ID,
        skill_slug=slug,
        is_enabled=True,
        human_approval_required=False,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _raising_factory(name: str) -> Callable[[Any], Callable[[dict], Any]]:
    def factory(deps: Any) -> Callable[[dict], Any]:
        async def node(state: dict) -> dict:
            raise RuntimeError(f"forced_{name}")

        return node

    return factory


def _observability() -> MagicMock:
    obs = MagicMock()
    trace = MagicMock()
    trace.primary.run_id = "11111111-1111-1111-1111-111111111111"
    trace.primary.dotted_order = "20260101T000000000000Z" + "1" * 32
    obs.start_conversation_trace.return_value = trace
    obs.trace_id.return_value = "trace-failures"
    return obs


@pytest.fixture
def turn(fake_deps, monkeypatch) -> dict[str, Any]:
    """Grafo real con DB/LLM mockeados y dos skills de test (L1 lectura, L2 escritura)."""
    _patch_all_db_and_llm(monkeypatch)
    monkeypatch.setattr(SkillRegistry, "_by_slug", {})
    SkillRegistry.register(_skill("test.read", "L1"))
    SkillRegistry.register(_skill("test.write", "L2"))
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.get_tenant_configuration",
        AsyncMock(
            return_value=make_tenant_configuration(
                extra={"allowed_skills": ["test.read", "test.write"]}
            )
        ),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.list_tool_permissions",
        AsyncMock(return_value=[_permission("test.read"), _permission("test.write")]),
    )
    insert_escalation = AsyncMock(return_value=make_escalation())
    monkeypatch.setattr("apps.api.agents.nodes.handle_error.insert_escalation", insert_escalation)
    obs = _observability()
    return {
        "deps": dataclasses.replace(fake_deps, observability=obs),
        "obs": obs,
        "insert_escalation": insert_escalation,
    }


async def _run_turn(deps: Any, obs: MagicMock) -> Any:
    service = AgentService(
        graph=build_graph(deps), observability=obs, handle_error=make_handle_error_node(deps)
    )
    return await service.process_inbound(
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        inbound_message_id=INBOUND_MSG_ID,
        inbound_message_content="¿envíos a Argentina?",
        channel="chat",
        end_customer_id=CUSTOMER_ID,
    )


def test_every_graph_node_is_a_turn_node_or_the_failure_tail(fake_deps) -> None:
    nodes = set(build_graph(fake_deps).get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == set(TURN_NODES) | {"handle_error", "finalize_trace"}


def test_graph_runs_with_room_for_a_full_supervised_turn(fake_deps) -> None:
    # 5 tools L2 supervisadas + supervisión final + rechazo táctico ≈ 26 pasos: el 25
    # por defecto de LangGraph cortaría un turno legítimo.
    assert build_graph(fake_deps).config["recursion_limit"] == GRAPH_RECURSION_LIMIT >= 50


def test_every_turn_node_has_a_failure_scenario() -> None:
    assert set(_SCENARIOS) == set(TURN_NODES)


@pytest.mark.asyncio
@pytest.mark.parametrize("node", sorted(TURN_NODES))
async def test_node_exception_escalates_acks_logs_and_traces(
    node: str, turn: dict[str, Any], monkeypatch, caplog
) -> None:
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason.call_claude_with_tools",
        AsyncMock(return_value=_SCENARIOS[node]),
    )
    _, route = TURN_NODES[node]
    monkeypatch.setitem(graph_module.TURN_NODES, node, (_raising_factory(node), route))
    reason = f"agent_error: {node}: RuntimeError: forced_{node}"

    with caplog.at_level(logging.ERROR):
        outcome = await _run_turn(turn["deps"], turn["obs"])

    assert outcome.decision == "error"
    assert outcome.error == f"{node}: RuntimeError: forced_{node}"
    assert outcome.escalation_id == str(ESCALATION_ID)
    assert outcome.escalation_created is True
    assert outcome.escalation_reason == reason
    assert outcome.response_text is None
    assert turn["insert_escalation"].await_args.kwargs["reason"] == reason
    assert turn["deps"].reasoning_tracker.events[-1] == {
        "tenant_id": str(TENANT_ID),
        "conversation_id": str(CONVERSATION_ID),
        "phase": "response",
        "event_type": "choice",
        "label": "Escalated to human",
        "detail": {"reason": reason, "escalation_id": str(ESCALATION_ID)},
        "status": "error",
    }
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [
        f"node {node} raised RuntimeError"
    ]
    ack = chat_escalation_ack(
        outcome.decision,
        outcome.response_text,
        outcome.escalation_reason,
        escalated=outcome.escalated,
    )
    assert ack == fixed_text("escalation_ack", "es")
    spans = {c.kwargs["node_name"]: c.kwargs for c in turn["obs"].record_node_run.call_args_list}
    assert spans[node]["error"] == f"forced_{node}"
    assert spans["handle_error"]["error"] is None
    assert turn["obs"].finalize_trace.call_args.kwargs["error"] == outcome.error
