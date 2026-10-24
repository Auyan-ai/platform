"""Tests end-to-end del grafo compilado.

Construye el grafo real con `build_graph(deps)` y mockea TODAS las llamadas a
DB y LLM en cada módulo de nodo. Valida que las edges del grafo están bien
cableadas y que un mensaje fluye correctamente desde START hasta END por cada
uno de los tres caminos: respond, escalate, handle_error.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apps.api.agents.graph import build_graph

from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    ESCALATION_ID,
    INBOUND_MSG_ID,
    OUTBOUND_MSG_ID,
    TENANT_ID,
    FakeAnthropicResponse,
    make_conversation,
    make_end_customer,
    make_escalation,
    make_fake_tenant_scope,
    make_message,
    make_tenant,
    make_tenant_configuration,
)


def _patch_all_db_and_llm(
    monkeypatch,
    *,
    tenant_status: str = "active",
    tenant_present: bool = True,
    config_present: bool = True,
    prompt_present: bool = True,
    llm_response: FakeAnthropicResponse | None = None,
    llm_raises: Exception | None = None,
) -> None:
    """Parchea TODO lo externo a los nodos. El grafo opera puro in-memory."""
    fake_scope = make_fake_tenant_scope()

    # --- load_tenant_context ---
    monkeypatch.setattr("apps.api.agents.nodes.load_tenant_context.tenant_scope", fake_scope)
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.get_tenant_by_id",
        AsyncMock(return_value=make_tenant(status=tenant_status) if tenant_present else None),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.get_tenant_configuration",
        AsyncMock(return_value=make_tenant_configuration() if config_present else None),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.get_active_system_prompt",
        AsyncMock(return_value="Eres el agente de Acme." if prompt_present else None),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.list_tool_permissions",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.get_tenant_playbook",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.get_tenant_facts",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.load_current_returns_policy",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.build_commerce_integration_ctx",
        AsyncMock(return_value=None),
    )

    # --- resolve_identity ---
    monkeypatch.setattr("apps.api.agents.nodes.resolve_identity.tenant_scope", fake_scope)
    monkeypatch.setattr(
        "apps.api.agents.nodes.resolve_identity.get_tenant_pii_salt",
        AsyncMock(return_value="test-salt"),
    )

    # --- load_conversation ---
    monkeypatch.setattr("apps.api.agents.nodes.load_conversation.tenant_scope", fake_scope)
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_conversation.get_conversation",
        AsyncMock(return_value=make_conversation()),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_conversation.get_end_customer",
        AsyncMock(return_value=make_end_customer()),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_conversation.get_recent_messages",
        AsyncMock(return_value=[make_message(content="¿envíos a Argentina?")]),
    )

    # --- select_aop: no-op (tenant sin AOPs → degradación elegante al prompt legacy) ---
    monkeypatch.setattr("apps.api.agents.nodes.select_aop.tenant_scope", fake_scope)
    monkeypatch.setattr(
        "apps.api.agents.nodes.select_aop.load_active_aops",
        AsyncMock(return_value=[]),
    )

    # --- retrieve_knowledge ---
    monkeypatch.setattr("apps.api.agents.nodes.retrieve_knowledge.tenant_scope", fake_scope)
    monkeypatch.setattr(
        "apps.api.agents.nodes.retrieve_knowledge.get_query_embedding",
        AsyncMock(return_value=[0.0] * 1536),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.retrieve_knowledge.search_knowledge_chunks",
        AsyncMock(return_value=[]),
    )

    # --- reason ---
    if llm_raises is not None:
        monkeypatch.setattr(
            "apps.api.integrations.anthropic_client.call_claude_with_tools",
            AsyncMock(side_effect=llm_raises),
        )
    elif llm_response is not None:
        monkeypatch.setattr(
            "apps.api.integrations.anthropic_client.call_claude_with_tools",
            AsyncMock(return_value=llm_response),
        )

    # --- respond ---
    monkeypatch.setattr("apps.api.agents.nodes.respond.tenant_scope", fake_scope)
    monkeypatch.setattr(
        "apps.api.agents.nodes.respond.insert_message",
        AsyncMock(
            return_value=make_message(
                id=OUTBOUND_MSG_ID,
                role="agent_ai",
                direction="outbound",
            )
        ),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.respond.update_conversation_last_message", AsyncMock()
    )

    # --- escalate ---
    monkeypatch.setattr("apps.api.agents.nodes.escalate.tenant_scope", fake_scope)
    monkeypatch.setattr(
        "apps.api.agents.nodes.escalate.get_open_escalation_for_conversation",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.escalate.insert_escalation",
        AsyncMock(return_value=make_escalation()),
    )
    monkeypatch.setattr("apps.api.agents.nodes.escalate.update_conversation_status", AsyncMock())
    monkeypatch.setattr(
        "apps.api.agents.nodes.escalate.insert_message",
        AsyncMock(
            return_value=make_message(
                id=OUTBOUND_MSG_ID,
                role="agent_ai",
                direction="outbound",
            )
        ),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.escalate.update_conversation_last_message", AsyncMock()
    )

    # --- handle_error ---
    monkeypatch.setattr("apps.api.agents.nodes.handle_error.tenant_scope", fake_scope)
    monkeypatch.setattr(
        "apps.api.agents.nodes.handle_error.get_open_escalation_for_conversation",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.handle_error.insert_escalation",
        AsyncMock(return_value=make_escalation()),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.handle_error.update_conversation_status", AsyncMock()
    )


def _initial_state() -> dict:
    return {
        "tenant_id": str(TENANT_ID),
        "conversation_id": str(CONVERSATION_ID),
        "inbound_message_id": str(INBOUND_MSG_ID),
        "inbound_message_content": "¿envíos a Argentina?",
        "channel": "chat",
        "end_customer_id": str(CUSTOMER_ID),
        "langfuse_trace_id": "trace-e2e",
    }


@pytest.mark.asyncio
async def test_respond_path_end_to_end(fake_deps, monkeypatch) -> None:
    """Camino feliz: Claude decide respond con alta confianza → mensaje persistido."""
    _patch_all_db_and_llm(
        monkeypatch,
        llm_response=FakeAnthropicResponse(
            {
                "decision": "respond",
                "confidence": 0.92,
                "response_text": "Los envíos tardan 3-5 días.",
            }
        ),
    )
    graph = build_graph(fake_deps)

    final = await graph.ainvoke(_initial_state())

    assert final["decision"] == "respond"
    assert final["agent_response"] == "Los envíos tardan 3-5 días."
    assert final["output_message_id"] == str(OUTBOUND_MSG_ID)
    assert "escalation_id" not in final
    assert final.get("error") is None


@pytest.mark.asyncio
async def test_escalate_path_end_to_end(fake_deps, monkeypatch) -> None:
    """Claude decide escalate explícitamente → escalation persistida."""
    _patch_all_db_and_llm(
        monkeypatch,
        llm_response=FakeAnthropicResponse(
            {
                "decision": "escalate",
                "confidence": 0.95,
                "response_text": "Te paso con un agente humano que te ayudará.",
                "escalation_reason": "customer_requested_human",
            }
        ),
    )
    graph = build_graph(fake_deps)

    final = await graph.ainvoke(_initial_state())

    assert final["decision"] == "escalate"
    assert final["escalation_reason"] == "customer_requested_human"
    assert final["escalation_id"] == str(ESCALATION_ID)
    assert final.get("agent_response") == "Te paso con un agente humano que te ayudará."
    assert final.get("error") is None


@pytest.mark.asyncio
async def test_threshold_override_path(fake_deps, monkeypatch) -> None:
    """Claude dice respond pero confianza < threshold → grafo termina en escalate."""
    _patch_all_db_and_llm(
        monkeypatch,
        llm_response=FakeAnthropicResponse(
            {
                "decision": "respond",
                "confidence": 0.40,  # < threshold 0.70
                "response_text": "respuesta tentativa",
            }
        ),
    )
    graph = build_graph(fake_deps)

    final = await graph.ainvoke(_initial_state())

    assert final["decision"] == "escalate"
    assert "low_confidence" in final["escalation_reason"]
    assert final["escalation_id"] == str(ESCALATION_ID)


@pytest.mark.asyncio
async def test_reply_empty_after_normalizing_escalates_as_empty_reply(
    fake_deps, monkeypatch, caplog
) -> None:
    """#350: una respuesta que el normalizador deja vacía nunca sale; se escala y se loguea."""
    _patch_all_db_and_llm(
        monkeypatch,
        llm_response=FakeAnthropicResponse(
            {"decision": "respond", "confidence": 0.92, "response_text": "😊"}
        ),
    )
    graph = build_graph(fake_deps)

    with caplog.at_level("ERROR"):
        final = await graph.ainvoke(_initial_state())

    assert final["decision"] == "escalate"
    assert final["escalation_reason"] == "empty_reply"
    assert final["escalation_id"] == str(ESCALATION_ID)
    assert final.get("agent_response") is None
    assert final.get("error") is None
    assert "output_message_id" not in final
    assert [r.getMessage() for r in caplog.records if r.levelname == "ERROR"] == ["empty_reply"]


@pytest.mark.asyncio
async def test_escalation_text_empty_after_normalizing_is_not_delivered_raw(
    fake_deps, monkeypatch
) -> None:
    """El borrador crudo no sobrevive en el state si el normalizador lo vació."""
    _patch_all_db_and_llm(
        monkeypatch,
        llm_response=FakeAnthropicResponse(
            {
                "decision": "escalate",
                "confidence": 0.95,
                "response_text": "🙏",
                "escalation_reason": "customer_requested_human",
            }
        ),
    )
    graph = build_graph(fake_deps)

    final = await graph.ainvoke(_initial_state())

    assert final["decision"] == "escalate"
    assert final["escalation_reason"] == "customer_requested_human"
    assert final.get("agent_response") is None


@pytest.mark.asyncio
async def test_tenant_not_found_routes_to_handle_error(fake_deps, monkeypatch) -> None:
    """load_tenant_context falla → handle_error → escalation con prefijo agent_error."""
    _patch_all_db_and_llm(
        monkeypatch,
        tenant_present=False,
        # llm_response no se va a usar, pero igual lo seteamos para no romper si se llama
        llm_response=FakeAnthropicResponse(
            {"decision": "respond", "confidence": 0.9, "response_text": "x"}
        ),
    )
    graph = build_graph(fake_deps)

    final = await graph.ainvoke(_initial_state())

    assert final["error"] == "tenant_not_found"
    assert final["escalation_id"] == str(ESCALATION_ID)
    # Ni respond ni reason deberían haber producido datos
    assert "agent_response" not in final or final["agent_response"] is None


@pytest.mark.asyncio
async def test_llm_exception_routes_to_handle_error(fake_deps, monkeypatch) -> None:
    """Si Claude tira (después de retries), guard captura → handle_error."""
    _patch_all_db_and_llm(
        monkeypatch,
        llm_raises=RuntimeError("anthropic_unreachable"),
    )
    graph = build_graph(fake_deps)

    final = await graph.ainvoke(_initial_state())

    assert final.get("error") is not None
    assert "reason" in final["error"]
    assert "anthropic_unreachable" in final["error"]
    assert final["escalation_id"] == str(ESCALATION_ID)


@pytest.mark.asyncio
async def test_state_carries_through_all_nodes(fake_deps, monkeypatch) -> None:
    """Los campos del state inicial deben sobrevivir hasta el final."""
    _patch_all_db_and_llm(
        monkeypatch,
        llm_response=FakeAnthropicResponse(
            {"decision": "respond", "confidence": 0.9, "response_text": "ok"}
        ),
    )
    graph = build_graph(fake_deps)

    final = await graph.ainvoke(_initial_state())

    # Datos del input que pasaron por todos los nodos
    assert final["tenant_id"] == str(TENANT_ID)
    assert final["conversation_id"] == str(CONVERSATION_ID)
    assert final["langfuse_trace_id"] == "trace-e2e"
    # Datos producidos por la cadena
    assert "tenant_config" in final
    assert "system_prompt" in final
    assert "conversation_history" in final
    assert "end_customer" in final
    assert "retrieved_chunks" in final
    assert final["tokens_in"] > 0
    assert final["tokens_out"] > 0
    assert final["cost_usd"] >= 0


# ----------------------------------------------------------------
# Loop ReAct end-to-end
# ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_loop_two_iterations(fake_deps, monkeypatch) -> None:
    """E2E: 1ra iter de reason pide skill → execute_skill corre → 2da iter responde.

    Verifica que:
    - El loop reason ⇄ execute_skill funciona
    - tool_results acumula el output de la skill
    - tokens se acumulan entre iteraciones
    - El estado final es 'respond' con la respuesta de la segunda iter
    """
    from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
    from apps.api.skills.registry import SkillRegistry

    class PingInput(SkillInput):
        pass

    class PingOutput(SkillOutput):
        pong: bool

    class PingSkill(Skill):
        slug = "test.ping"
        description = "Pings."
        tier: SkillTier = "L1"
        input_schema = PingInput
        output_schema = PingOutput
        default_threshold = 0.70

        async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
            return PingOutput(pong=True)

    SkillRegistry._reset()
    SkillRegistry.register(PingSkill)

    from datetime import UTC, datetime

    from apps.api.db.models import TenantToolPermission

    config = make_tenant_configuration(extra={"allowed_skills": ["test.ping"]})
    _patch_all_db_and_llm(monkeypatch)
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.get_tenant_configuration",
        AsyncMock(return_value=config),
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

    responses = [
        FakeAnthropicResponse(
            {},
            tool_name="test_ping",
            tool_id="toolu_iter1",
            input_tokens=80,
            output_tokens=20,
        ),
        FakeAnthropicResponse(
            {
                "decision": "respond",
                "confidence": 0.95,
                "response_text": "El servicio está activo.",
            },
            tool_name="respond_or_escalate",
            tool_id="toolu_iter2",
            input_tokens=120,
            output_tokens=40,
        ),
    ]
    monkeypatch.setattr(
        "apps.api.integrations.anthropic_client.call_claude_with_tools",
        AsyncMock(side_effect=responses),
    )

    graph = build_graph(fake_deps)
    initial = _initial_state()
    initial["tool_results"] = []
    initial["tool_iterations"] = 0
    initial["max_tool_iterations"] = 5
    initial["allowed_skills"] = []
    initial["tool_permissions"] = {
        "test.ping": {
            "is_enabled": True,
            "human_approval_required": False,
            "threshold_override": None,
        }
    }

    final = await graph.ainvoke(initial)
    SkillRegistry._reset()

    assert final["decision"] == "respond"
    assert final["agent_response"] == "El servicio está activo."
    assert final["tool_iterations"] == 1
    assert len(final["tool_results"]) == 1
    entry = final["tool_results"][0]
    assert entry["slug"] == "test.ping"
    assert entry["is_error"] is False
    assert entry["output"] == {"pong": True}
    assert final["tokens_in"] == 200
    assert final["tokens_out"] == 60


@pytest.mark.asyncio
async def test_react_loop_max_iterations_escalates(fake_deps, monkeypatch) -> None:
    """E2E: si el LLM no para de pedir skill, se llega a max_tool_iterations y escala."""
    from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
    from apps.api.skills.registry import SkillRegistry

    class LoopInput(SkillInput):
        pass

    class LoopOutput(SkillOutput):
        n: int

    class LoopSkill(Skill):
        slug = "test.loop"
        description = "Loops."
        tier: SkillTier = "L1"
        input_schema = LoopInput
        output_schema = LoopOutput
        default_threshold = 0.70

        async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
            return LoopOutput(n=1)

    SkillRegistry._reset()
    SkillRegistry.register(LoopSkill)

    from datetime import UTC, datetime

    from apps.api.db.models import TenantToolPermission

    config = make_tenant_configuration(
        extra={"allowed_skills": ["test.loop"], "max_tool_iterations": 2}
    )
    _patch_all_db_and_llm(monkeypatch)
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.get_tenant_configuration",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.load_tenant_context.list_tool_permissions",
        AsyncMock(
            return_value=[
                TenantToolPermission(
                    id=TENANT_ID,
                    tenant_id=TENANT_ID,
                    skill_slug="test.loop",
                    is_enabled=True,
                    human_approval_required=False,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            ]
        ),
    )

    def _always_skill(**kwargs: object) -> FakeAnthropicResponse:
        return FakeAnthropicResponse(
            {},
            tool_name="test_loop",
            tool_id="toolu_loop",
            input_tokens=50,
            output_tokens=10,
        )

    monkeypatch.setattr(
        "apps.api.integrations.anthropic_client.call_claude_with_tools",
        AsyncMock(side_effect=_always_skill),
    )

    graph = build_graph(fake_deps)
    initial = _initial_state()
    initial["tool_results"] = []
    initial["tool_iterations"] = 0
    initial["max_tool_iterations"] = 5
    initial["tool_permissions"] = {
        "test.loop": {
            "is_enabled": True,
            "human_approval_required": False,
            "threshold_override": None,
        }
    }

    final = await graph.ainvoke(initial)
    SkillRegistry._reset()

    assert final["tool_iterations"] == 2
    assert "escalation_id" in final
    assert "max_tool_iterations_exceeded" in (final.get("escalation_reason") or "")


@pytest.mark.asyncio
async def test_respond_exception_escalates_with_reason(fake_deps, monkeypatch) -> None:
    """#362: si respond lanza, el turno escala con razón explícita (no termina en silencio)."""
    _patch_all_db_and_llm(
        monkeypatch,
        llm_response=FakeAnthropicResponse(
            {"decision": "respond", "confidence": 0.92, "response_text": "Envíos en 3-5 días."}
        ),
    )
    monkeypatch.setattr(
        "apps.api.agents.nodes.respond.insert_message",
        AsyncMock(side_effect=RuntimeError("db_write_failed")),
    )
    graph = build_graph(fake_deps)

    final = await graph.ainvoke(_initial_state())

    assert final["error"] == "respond: RuntimeError: db_write_failed"
    assert final["escalation_id"] == str(ESCALATION_ID)
    assert final["escalation_reason"] == "agent_error: respond: RuntimeError: db_write_failed"
