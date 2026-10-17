"""La petición HTTP que cada nodo manda a Anthropic, por modelo (#345).

Cliente real del SDK con transporte falso (`tests/anthropic_http.py`). Con los modelos de
hoy (Haiku 4.5, Sonnet 4.6, Opus 4.7) la petición es la misma que antes de #345: los JSON
de `golden_requests/` se capturaron con el código anterior. Con los 5.5, la petición no
fuerza tool ni apaga el thinking, y la respuesta se lee igual con thinking, sin tool o con
`stop_reason: refusal`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes.reason import make_reason_node
from apps.api.agents.nodes.select_aop import make_select_aop_node
from apps.api.agents.nodes.supervise import make_supervise_node
from apps.api.core.config import ModelRegistry, get_models
from apps.api.tests.anthropic_http import (
    RecordingAnthropic,
    message,
    tool_use,
)
from apps.api.tests.test_select_aop_node import (
    BASE_STATE as SELECT_AOP_STATE,
)
from apps.api.tests.test_select_aop_node import (
    CONSULTA_ENVIO,
    DEFAULT_AOP,
    _make_fake_tenant_scope,
)

GOLDEN = Path(__file__).parent / "golden_requests"
FROZEN_NOW = "2026-10-17 10:00 (Europe/Madrid)"
POLICIES = "shopify.get_shop_policies"
CANCEL = "shopify.cancel_order"

RESPOND = {"decision": "respond", "confidence": 0.9, "response_text": "Tardan 3 días."}
CLASSIFIED = {
    "primary": {"slug": "consulta_envio", "confidence": 0.92},
    "reasoning": "pregunta por su pedido",
    "ambiguity_detected": False,
}
APPROVE = {"verdict": "approve", "reject_kind": "n/a", "reason": "correcto"}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    monkeypatch.setattr(
        "apps.api.agents.nodes.reason._tenant_now_str", lambda _facts: FROZEN_NOW
    )
    for name in ModelRegistry.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    get_models.cache_clear()
    yield monkeypatch
    get_models.cache_clear()


def _deps(api: RecordingAnthropic, fake_deps: AgentDependencies) -> AgentDependencies:
    return AgentDependencies(
        anthropic=api.client,
        openai=fake_deps.openai,
        settings=fake_deps.settings,
        reasoning_tracker=fake_deps.reasoning_tracker,
        audit_logger=fake_deps.audit_logger,
    )


def _reason_state(model: str, **extra: Any) -> dict[str, Any]:
    return {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "system_prompt": "Eres el agente de Acme.",
        "retrieved_chunks": [],
        "conversation_history": [{"role": "customer", "content": "¿Cuánto tarda el envío?"}],
        "model_used": model,
        "tenant_config": {"escalation_threshold": 0.70},
        "allowed_skills": [],
        "tool_results": [],
        **extra,
    }


def _with_policies(state: dict[str, Any], *, hops: int) -> dict[str, Any]:
    state["allowed_skills"] = [POLICIES]
    state["tool_permissions"] = {POLICIES: {"is_enabled": True}}
    state["tool_iterations"] = hops
    state["max_tool_iterations"] = 3
    state["tool_results"] = [
        {
            "id": f"toolu_hop{i}",
            "slug": POLICIES,
            "input": {},
            "output": {"shipping": "3 días"},
            "is_error": False,
            "error": None,
        }
        for i in range(hops)
    ]
    return state


def _supervise_state(**extra: Any) -> dict[str, Any]:
    return {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "conversation_id": "22222222-2222-2222-2222-222222222222",
        "system_prompt": "eres un agente de soporte\n## Reglas NO negociables\n- no inventes",
        "tenant_config": {"extra": {}, "escalation_threshold": 0.70},
        "conversation_history": [{"role": "customer", "content": "quiero cancelar"}],
        "decision": "respond",
        "agent_response": "ok, te ayudo",
        "tool_results": [],
        "cost_usd": 0.01,
        "aop_slug": "cancelacion",
        **extra,
    }


async def run_reason(
    fake_deps: AgentDependencies, state: dict[str, Any], *responses: dict[str, Any]
) -> tuple[RecordingAnthropic, dict[str, Any]]:
    api = RecordingAnthropic(*responses)
    out = await make_reason_node(_deps(api, fake_deps))(state)  # type: ignore[arg-type]
    return api, out


async def run_select_aop(
    fake_deps: AgentDependencies, *responses: dict[str, Any]
) -> tuple[RecordingAnthropic, dict[str, Any]]:
    api = RecordingAnthropic(*responses)
    node = make_select_aop_node(_deps(api, fake_deps))
    module = "apps.api.agents.nodes.select_aop"
    with (
        patch(f"{module}.tenant_scope", _make_fake_tenant_scope(AsyncMock())),
        patch(f"{module}.get_last_intent_for_conversation", AsyncMock(return_value=None)),
        patch(f"{module}.load_active_aops", AsyncMock(return_value=[CONSULTA_ENVIO, DEFAULT_AOP])),
        patch(
            f"{module}.load_aop",
            AsyncMock(side_effect=lambda _c, _t, slug: {"consulta_envio": CONSULTA_ENVIO}.get(
                slug, DEFAULT_AOP
            )),
        ),
        patch(f"{module}.insert_intent_classifier_run", AsyncMock()),
    ):
        out = await node(SELECT_AOP_STATE)  # type: ignore[arg-type]
    return api, out


async def run_supervise(
    fake_deps: AgentDependencies, state: dict[str, Any], *responses: dict[str, Any]
) -> tuple[RecordingAnthropic, dict[str, Any]]:
    api = RecordingAnthropic(*responses)
    out = await make_supervise_node(_deps(api, fake_deps))(state)  # type: ignore[arg-type]
    return api, out


async def current_model_scenarios(
    fake_deps: AgentDependencies,
) -> dict[str, RecordingAnthropic]:
    """Un escenario por forma de petición de hoy. Genera y comprueba los golden."""
    simple, _ = await run_reason(
        fake_deps,
        _reason_state("claude-sonnet-4-6"),
        message(tool_use("respond_or_escalate", RESPOND), model="claude-haiku-4-5-20251001"),
    )
    loop, _ = await run_reason(
        fake_deps,
        _with_policies(_reason_state("claude-sonnet-4-6"), hops=1),
        message(tool_use("respond_or_escalate", RESPOND)),
    )
    exhausted, _ = await run_reason(
        fake_deps,
        _with_policies(_reason_state("claude-sonnet-4-6"), hops=3),
        message(tool_use("respond_or_escalate", RESPOND)),
    )
    classifier, _ = await run_select_aop(
        fake_deps, message(tool_use("select_aop", CLASSIFIED), model="claude-haiku-4-5-20251001")
    )
    supervisor_l1_l2, _ = await run_supervise(
        fake_deps,
        _supervise_state(),
        message(tool_use("supervisor_verdict", APPROVE)),
    )
    supervisor_l3, _ = await run_supervise(
        fake_deps,
        _supervise_state(
            decision=None,
            agent_response=None,
            pending_tool_call={"id": "toolu_c", "slug": CANCEL, "input": {"order_id": 1}},
        ),
        message(tool_use("supervisor_verdict", APPROVE), model="claude-opus-4-7"),
    )
    return {
        "reason_simple_haiku": simple,
        "reason_loop_sonnet_4_6": loop,
        "reason_exhausted_sonnet_4_6": exhausted,
        "select_aop_haiku": classifier,
        "supervise_l1_l2_sonnet_4_6": supervisor_l1_l2,
        "supervise_l3_opus_4_7": supervisor_l3,
    }


@pytest.mark.asyncio
async def test_current_models_send_the_same_request_as_before(
    fake_deps: AgentDependencies,
) -> None:
    scenarios = await current_model_scenarios(fake_deps)
    for name, api in scenarios.items():
        golden = json.loads((GOLDEN / f"{name}.json").read_text())
        assert {"body": api.requests, "beta": api.beta_headers} == golden, name
