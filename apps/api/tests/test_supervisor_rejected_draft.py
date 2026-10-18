"""#380: un borrador que el supervisor no aprobó nunca llega al cliente.

Grafo real y SDK de Anthropic real con transporte HTTP falso (`tests/anthropic_http.py`);
la DB está mockeada como en `test_graph_e2e`. El turno usa una skill L1 y el tenant pide
supervisión, así que la respuesta pasa por el supervisor.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.graph import build_graph
from apps.api.agents.nodes.handle_error import make_handle_error_node
from apps.api.agents.service import AgentOutcome, AgentService
from apps.api.db.models import TenantToolPermission
from apps.api.services.inbound_media import chat_escalation_ack
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry

from tests.anthropic_http import RecordingAnthropic, message, refusal, tool_use
from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    INBOUND_MSG_ID,
    TENANT_ID,
    make_tenant_configuration,
)
from tests.test_graph_e2e import _patch_all_db_and_llm

DRAFT = "Tu pedido llega mañana sin falta."
RETRY_DRAFT = "Tu pedido sale hoy y llega mañana seguro."
STRUCTURAL = {
    "verdict": "reject",
    "reject_kind": "structural",
    "reason": "El plazo de entrega no aparece en la evidencia.",
}
TACTICAL = {
    "verdict": "reject",
    "reject_kind": "tactical",
    "reason": "Afirma un plazo sin respaldo: consulta el estado del pedido.",
}


class _PingInput(SkillInput):
    pass


class _PingOutput(SkillOutput):
    pong: bool


class _PingSkill(Skill):
    slug = "test.ping"
    description = "Pings."
    tier: SkillTier = "L1"
    input_schema = _PingInput
    output_schema = _PingOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        return _PingOutput(pong=True)


@pytest.fixture(autouse=True)
def _ping_skill() -> Iterator[None]:
    saved = dict(SkillRegistry._by_slug)
    SkillRegistry.register(_PingSkill)
    yield
    SkillRegistry._by_slug.clear()
    SkillRegistry._by_slug.update(saved)


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    _patch_all_db_and_llm(monkeypatch)
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.get_tenant_configuration",
        AsyncMock(
            return_value=make_tenant_configuration(
                extra={"allowed_skills": ["test.ping"], "require_supervision": True}
            )
        ),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.list_tool_permissions",
        AsyncMock(
            return_value=[
                TenantToolPermission(
                    id=TENANT_ID,
                    tenant_id=TENANT_ID,
                    skill_slug="test.ping",
                    is_enabled=True,
                    human_approval_required=False,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            ]
        ),
    )
    import apps.api.agents.nodes.escalate as escalate
    import apps.api.agents.nodes.respond as respond

    return {
        "escalate.insert_message": escalate.insert_message,  # type: ignore[dict-item]
        "escalate.insert_escalation": escalate.insert_escalation,  # type: ignore[dict-item]
        "respond.insert_message": respond.insert_message,  # type: ignore[dict-item]
    }


def _reason_ping() -> dict[str, Any]:
    return message(tool_use("test_ping", {}, id="toolu_ping"))


def _reason_respond(text: str) -> dict[str, Any]:
    return message(
        tool_use(
            "respond_or_escalate",
            {"decision": "respond", "confidence": 0.9, "response_text": text},
            id="toolu_decide",
        )
    )


def _verdict(payload: dict[str, Any]) -> dict[str, Any]:
    return message(tool_use("supervisor_verdict", payload, id="toolu_verdict"))


async def _run_turn(fake_deps: AgentDependencies, api: RecordingAnthropic) -> AgentOutcome:
    deps = AgentDependencies(
        anthropic=api.client,
        openai=fake_deps.openai,
        settings=fake_deps.settings,
        reasoning_tracker=fake_deps.reasoning_tracker,
        audit_logger=fake_deps.audit_logger,
    )
    obs = MagicMock()
    obs.trace_id.return_value = "trace-380"
    service = AgentService(
        graph=build_graph(deps), observability=obs, handle_error=make_handle_error_node(deps)
    )
    return await service.process_inbound(
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        inbound_message_id=INBOUND_MSG_ID,
        inbound_message_content="¿Cuándo llega mi pedido?",
        channel="chat",
        end_customer_id=CUSTOMER_ID,
    )


def _saved_contents(mock: AsyncMock) -> list[str]:
    return [call.kwargs["content"] for call in mock.await_args_list]


def _assert_customer_gets_only_the_ack(outcome: AgentOutcome, db: dict[str, AsyncMock]) -> None:
    assert outcome.decision == "escalate"
    assert outcome.response_text is None
    assert _saved_contents(db["escalate.insert_message"]) == []
    assert _saved_contents(db["respond.insert_message"]) == []
    ack = chat_escalation_ack(
        outcome.decision,
        outcome.response_text,
        outcome.escalation_reason,
        escalated=outcome.escalated,
        language="es",
    )
    assert ack is not None
    assert DRAFT not in ack


@pytest.mark.asyncio
async def test_structural_reject_never_reaches_the_customer(
    fake_deps: AgentDependencies, db: dict[str, AsyncMock]
) -> None:
    api = RecordingAnthropic(_reason_ping(), _reason_respond(DRAFT), _verdict(STRUCTURAL))

    outcome = await _run_turn(fake_deps, api)

    _assert_customer_gets_only_the_ack(outcome, db)
    assert outcome.escalation_reason == (
        "supervisor_rejected (structural): El plazo de entrega no aparece en la evidencia."
    )
    assert outcome.rejected_draft == DRAFT
    metadata = db["escalate.insert_escalation"].await_args.kwargs["metadata"]
    assert metadata["rejected_draft"] == DRAFT


@pytest.mark.asyncio
async def test_second_tactical_reject_never_reaches_the_customer(
    fake_deps: AgentDependencies, db: dict[str, AsyncMock]
) -> None:
    api = RecordingAnthropic(
        _reason_ping(),
        _reason_respond(DRAFT),
        _verdict(TACTICAL),
        _reason_respond(RETRY_DRAFT),
        _verdict(TACTICAL),
    )

    outcome = await _run_turn(fake_deps, api)

    _assert_customer_gets_only_the_ack(outcome, db)
    assert outcome.escalation_reason == f"supervisor_rejected (tactical): {TACTICAL['reason']}"
    assert outcome.rejected_draft == RETRY_DRAFT


@pytest.mark.asyncio
async def test_no_verdict_never_reaches_the_customer(
    fake_deps: AgentDependencies, db: dict[str, AsyncMock]
) -> None:
    api = RecordingAnthropic(_reason_ping(), _reason_respond(DRAFT), refusal())

    outcome = await _run_turn(fake_deps, api)

    _assert_customer_gets_only_the_ack(outcome, db)
    assert outcome.escalation_reason == "supervisor_rejected (structural): llm_refusal: cyber"
    assert outcome.rejected_draft == DRAFT


@pytest.mark.asyncio
async def test_supervisor_failure_never_reaches_the_customer(
    fake_deps: AgentDependencies, db: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "apps.api.agents.nodes.supervise.call_claude_for_decision",
        AsyncMock(side_effect=RuntimeError("supervisor_down")),
    )
    api = RecordingAnthropic(_reason_ping(), _reason_respond(DRAFT))

    outcome = await _run_turn(fake_deps, api)

    assert outcome.decision == "error"
    assert outcome.response_text is None
    assert outcome.escalation_reason == "agent_error: supervise: RuntimeError: supervisor_down"
    assert _saved_contents(db["escalate.insert_message"]) == []
    assert _saved_contents(db["respond.insert_message"]) == []
    assert chat_escalation_ack(
        outcome.decision,
        outcome.response_text,
        outcome.escalation_reason,
        escalated=outcome.escalated,
        language="es",
    )


@pytest.mark.asyncio
async def test_approved_draft_is_delivered(
    fake_deps: AgentDependencies, db: dict[str, AsyncMock]
) -> None:
    approve = {"verdict": "approve", "reject_kind": "n/a", "reason": "correcto"}
    api = RecordingAnthropic(_reason_ping(), _reason_respond(DRAFT), _verdict(approve))

    outcome = await _run_turn(fake_deps, api)

    assert outcome.decision == "respond"
    assert outcome.response_text == DRAFT
    assert outcome.rejected_draft is None
    assert _saved_contents(db["respond.insert_message"]) == [DRAFT]
