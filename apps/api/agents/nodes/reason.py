"""Nodo: reason — núcleo del agente.

1. Compone system prompt = base_tenant + bloque RAG.
2. Construye historial en formato Anthropic.
3. Llama a Claude con tool use forzado (`respond_or_escalate`).
4. Valida tool output con Pydantic.
5. Aplica override por umbral de confianza (regla del tenant).
6. Acumula tokens y costo.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.prompts.builder import (
    build_message_history,
    build_system_prompt,
)
from apps.api.agents.schemas import RESPOND_OR_ESCALATE_TOOL, AgentDecisionTool
from apps.api.agents.state import AgentState
from apps.api.integrations.anthropic_client import call_claude_with_tool
from apps.api.integrations.pricing import compute_llm_cost


def make_reason_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict]]:
    @guarded(name="reason")
    async def _node(state: AgentState) -> dict:
        system_prompt = build_system_prompt(
            state["system_prompt"],
            state.get("retrieved_chunks", []),
        )
        messages = build_message_history(state["conversation_history"])

        model = state["model_used"]

        response = await call_claude_with_tool(
            client=deps.anthropic,
            model=model,
            system=system_prompt,
            messages=messages,
            tool=RESPOND_OR_ESCALATE_TOOL,
            max_retries=deps.settings.llm_max_retries,
            timeout_seconds=deps.settings.llm_timeout_seconds,
        )

        # Extraer el tool_use block. tool_choice=forced garantiza que exista,
        # pero validamos por defensa.
        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block is None:
            return {"error": "claude_did_not_use_tool"}

        try:
            parsed = AgentDecisionTool.model_validate(tool_block.input)
        except ValidationError as exc:
            return {"error": f"invalid_tool_output: {exc.errors()}"}

        # Override por umbral de confianza del tenant.
        decision = parsed.decision
        escalation_reason: str | None = parsed.escalation_reason
        agent_response: str | None = parsed.response_text
        threshold = float(state["tenant_config"]["escalation_threshold"])

        if decision == "respond" and parsed.confidence < threshold:
            decision = "escalate"
            escalation_reason = (
                f"low_confidence: {parsed.confidence:.2f} < threshold {threshold:.2f}"
            )
            agent_response = None

        cost = compute_llm_cost(
            model,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        return {
            "decision": decision,
            "confidence": parsed.confidence,
            "agent_response": agent_response,
            "escalation_reason": escalation_reason,
            "tokens_in": response.usage.input_tokens,
            "tokens_out": response.usage.output_tokens,
            "cost_usd": cost,
            "model_used": model,
        }

    return _node
