"""Nodo: reason — núcleo del agente con loop ReAct.

1. Compone system prompt = base_tenant + bloque RAG.
2. Construye historial en formato Anthropic + ciclos tool_use/tool_result de
   iteraciones previas (loop ReAct multi-turn).
3. Construye la lista de tools: decide tool + skills permitidas por el AOP.
4. Llama a Claude con `tool_choice={"type":"any"}` — fuerza el uso de alguna
   tool pero deja al LLM elegir cuál.
5. Si eligió el decide tool: valida output, aplica threshold override, setea
   `decision`/`agent_response`/`escalation_reason`.
6. Si eligió una skill tool: setea `pending_tool_call` para que `execute_skill`
   la corra. NO setea decision (eso vendrá en la próxima vuelta del loop).
7. Acumula tokens y costo entre iteraciones.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes._guard import guarded
from apps.api.agents.prompts.builder import (
    build_message_history,
    build_system_prompt,
)
from apps.api.agents.schemas import RESPOND_OR_ESCALATE_TOOL, AgentDecisionTool
from apps.api.agents.state import AgentState
from apps.api.integrations.anthropic_client import call_claude_with_tools
from apps.api.integrations.pricing import compute_llm_cost
from apps.api.skills.registry import SkillRegistry
from pydantic import ValidationError

logger = logging.getLogger(__name__)

DECIDE_TOOL_NAME: str = RESPOND_OR_ESCALATE_TOOL["name"]


def _append_tool_result_blocks(
    messages: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Appendea los ciclos tool_use/tool_result de iteraciones previas al historial.

    Anthropic espera, después del último mensaje user del cliente:
        [{role: assistant, content: [tool_use block]},
         {role: user,      content: [tool_result block]},
         ...]
    """
    for result in tool_results:
        anthropic_name = result["slug"].replace(".", "_")
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": result["id"],
                        "name": anthropic_name,
                        "input": result["input"],
                    }
                ],
            }
        )
        if result["is_error"]:
            tool_result_text = result.get("error") or "unknown_error"
        else:
            tool_result_text = json.dumps(result["output"], ensure_ascii=False)
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": result["id"],
                        "content": tool_result_text,
                        "is_error": result["is_error"],
                    }
                ],
            }
        )
    return messages


def _build_tools(allowed_skills: list[str]) -> list[dict[str, Any]]:
    """Construye la lista de tools que ve el LLM: decide tool + skills permitidas."""
    tools: list[dict[str, Any]] = [RESPOND_OR_ESCALATE_TOOL]
    for slug in allowed_skills:
        try:
            skill_cls = SkillRegistry.get(slug)
        except ValueError:
            logger.warning("allowed_skill_not_in_registry: %s", slug)
            continue
        tools.append(skill_cls().to_anthropic_tool())
    return tools


def _slug_from_anthropic_name(tool_name: str, allowed_skills: list[str]) -> str | None:
    """Mapea nombre Anthropic ('shopify_get_order_by_email') → slug interno.

    El mapeo `slug.replace('.', '_')` no es bijectivo, así que buscamos en
    `allowed_skills` cuál coincide.
    """
    for slug in allowed_skills:
        if slug.replace(".", "_") == tool_name:
            return slug
    return None


def _handle_decide_tool(
    tool_input: dict[str, Any],
    state: AgentState,
    tokens_update: dict[str, Any],
) -> dict[str, Any]:
    """Procesa el output del decide tool: respond/escalate + threshold override."""
    try:
        parsed = AgentDecisionTool.model_validate(tool_input)
    except ValidationError as exc:
        return {"error": f"invalid_tool_output: {exc.errors()}", **tokens_update}

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

    return {
        "decision": decision,
        "confidence": parsed.confidence,
        "agent_response": agent_response,
        "escalation_reason": escalation_reason,
        **tokens_update,
    }


def make_reason_node(
    deps: AgentDependencies,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    @guarded(name="reason")
    async def _node(state: AgentState) -> dict[str, Any]:
        system_prompt = build_system_prompt(
            state["system_prompt"],
            state.get("retrieved_chunks", []),
        )
        messages = build_message_history(state["conversation_history"])
        messages = _append_tool_result_blocks(messages, state.get("tool_results", []))

        allowed_skills: list[str] = state.get("allowed_skills") or []
        tools = _build_tools(allowed_skills)

        model = state["model_used"]

        response = await call_claude_with_tools(
            client=deps.anthropic,
            model=model,
            system=system_prompt,
            messages=messages,
            tools=tools,
            tool_choice={"type": "any"},
            max_retries=deps.settings.llm_max_retries,
            timeout_seconds=deps.settings.llm_timeout_seconds,
        )

        # Extraer el primer tool_use block. tool_choice=any garantiza que exista.
        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block is None:
            return {"error": "claude_did_not_use_tool"}

        # Acumular tokens/costo con lo que ya hubiera de iteraciones previas.
        prev_in: int = state.get("tokens_in", 0)
        prev_out: int = state.get("tokens_out", 0)
        prev_cost: float = state.get("cost_usd", 0.0)

        this_in = response.usage.input_tokens
        this_out = response.usage.output_tokens
        this_cost = compute_llm_cost(model, this_in, this_out)

        tokens_update: dict[str, Any] = {
            "tokens_in": prev_in + this_in,
            "tokens_out": prev_out + this_out,
            "cost_usd": prev_cost + this_cost,
            "model_used": model,
        }

        tool_name: str = tool_block.name

        # ¿Decide tool o skill tool?
        if tool_name == DECIDE_TOOL_NAME:
            return _handle_decide_tool(tool_block.input, state, tokens_update)

        # Skill tool — mapear name → slug y emitir pending_tool_call.
        slug = _slug_from_anthropic_name(tool_name, allowed_skills)
        if slug is None:
            return {
                "error": f"llm_chose_unknown_tool: {tool_name}",
                **tokens_update,
            }

        return {
            "pending_tool_call": {
                "id": tool_block.id,
                "slug": slug,
                "input": tool_block.input,
            },
            **tokens_update,
        }

    return _node
