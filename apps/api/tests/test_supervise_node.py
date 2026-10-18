"""Tests para el nodo supervise y las funciones de routing del supervisor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic.types import Usage

# ──────────────────────────────────────────────────────────
# needs_supervision
# ──────────────────────────────────────────────────────────


class TestNeedsSupervision:
    def _fn(self, state: dict) -> bool:
        from apps.api.agents.nodes.supervise import needs_supervision

        return needs_supervision(state)

    def test_false_without_pending_tool_or_flag(self):
        assert not self._fn({"tenant_config": {"extra": {}}})

    def test_aop_require_supervision_supervises_response_after_tools(self):
        # require_supervision + el turno usó herramientas → supervisa la respuesta.
        assert self._fn({
            "tenant_config": {"extra": {}},
            "aop_require_supervision": True,
            "tool_results": [{"slug": "shopify.get_order_status", "is_error": False}],
        })

    def test_aop_require_supervision_skips_plain_response(self):
        # require_supervision PERO respuesta de cortesía sin herramientas → no supervisa.
        assert not self._fn({
            "tenant_config": {"extra": {}},
            "aop_require_supervision": True,
            "tool_results": [],
        })

    def test_aop_require_supervision_false_does_not_force(self):
        assert not self._fn({"tenant_config": {"extra": {}}, "aop_require_supervision": False})

    def test_false_for_l1_tool(self):
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L1Skill(Skill):
            slug = "test.l1_supervise"
            description = "test"
            tier = "L1"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.7

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l1_supervise"] = _L1Skill
        try:
            assert not self._fn({
                "tenant_config": {"extra": {}},
                "pending_tool_call": {"slug": "test.l1_supervise", "input": {}},
            })
            # P3: una lectura L1 pendiente NO se supervisa aunque el AOP pida
            # require_supervision y ya haya tool_results. Supervisar la intención
            # de leer es un hop sin valor; el respond que use el dato sí se supervisa.
            assert not self._fn({
                "tenant_config": {"extra": {"require_supervision": True}},
                "aop_require_supervision": True,
                "tool_results": [{"slug": "shopify.get_order_status", "is_error": False}],
                "pending_tool_call": {"slug": "test.l1_supervise", "input": {}},
            })
        finally:
            del SkillRegistry._by_slug["test.l1_supervise"]

    def test_true_for_l2_tool(self):
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L2Skill(Skill):
            slug = "test.l2_supervise"
            description = "test"
            tier = "L2"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.85

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l2_supervise"] = _L2Skill
        try:
            assert self._fn({
                "tenant_config": {"extra": {}},
                "pending_tool_call": {"slug": "test.l2_supervise", "input": {}},
            })
        finally:
            del SkillRegistry._by_slug["test.l2_supervise"]

    def test_true_for_l3_tool(self):
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L3Skill(Skill):
            slug = "test.l3_supervise"
            description = "test"
            tier = "L3"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.95

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l3_supervise"] = _L3Skill
        try:
            assert self._fn({
                "tenant_config": {"extra": {}},
                "pending_tool_call": {"slug": "test.l3_supervise", "input": {}},
            })
        finally:
            del SkillRegistry._by_slug["test.l3_supervise"]

    def test_require_supervision_flag_supervises_after_tools(self):
        assert self._fn({
            "tenant_config": {"extra": {"require_supervision": True}},
            "tool_results": [{"slug": "x", "is_error": False}],
        })

    def test_require_supervision_flag_skips_plain_response(self):
        assert not self._fn({
            "tenant_config": {"extra": {"require_supervision": True}},
            "tool_results": [],
        })

    def test_l3_pending_supervised_even_without_tool_results(self):
        """Una acción L3 pendiente se supervisa siempre, aunque no haya tool_results."""
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L3Skill(Skill):
            slug = "test.l3_always"
            description = "test"
            tier = "L3"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.95

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l3_always"] = _L3Skill
        try:
            assert self._fn({
                "tenant_config": {"extra": {}},
                "pending_tool_call": {"slug": "test.l3_always", "input": {}},
                "tool_results": [],
            })
        finally:
            del SkillRegistry._by_slug["test.l3_always"]

    def test_still_supervises_response_after_retry(self):
        """supervisor_retried NO apaga la supervisión del turno: la respuesta
        corregida tras un reject tactical se re-supervisa (el anti-loop vive en
        el nodo supervise: segundo reject → escalation_reason → escalate)."""
        assert self._fn({
            "tenant_config": {"extra": {"require_supervision": True}},
            "supervisor_retried": True,
            "tool_results": [{"slug": "x", "is_error": False}],
        })

    def test_still_supervises_l2_tool_after_retry(self):
        """Una L2 nueva pedida DESPUÉS de un retry del supervisor se supervisa
        igual — supervisor_retried es por-turno y no debe ser un kill-switch."""
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L2Skill(Skill):
            slug = "test.l2_after_retry"
            description = "test"
            tier = "L2"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.85

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l2_after_retry"] = _L2Skill
        try:
            assert self._fn({
                "tenant_config": {"extra": {}},
                "pending_tool_call": {"slug": "test.l2_after_retry", "input": {}},
                "supervisor_retried": True,
            })
        finally:
            del SkillRegistry._by_slug["test.l2_after_retry"]


# ──────────────────────────────────────────────────────────
# Nodo supervise
# ──────────────────────────────────────────────────────────


def _make_supervisor_response(verdict: str, reject_kind: str = "n/a", reason: str = "ok"):
    response = MagicMock()
    response.content = [
        MagicMock(
            type="tool_use",
            name="supervisor_verdict",
            id="sup_001",
            input={
                "verdict": verdict,
                "reject_kind": reject_kind,
                "reason": reason,
                "guardrails_violated": [],
            },
        )
    ]
    response.usage = MagicMock(input_tokens=200, output_tokens=80)
    return response


class TestSuperviseNode:
    def _base_state(self) -> dict:
        return {
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "conversation_id": "22222222-2222-2222-2222-222222222222",
            "system_prompt": "eres un agente de soporte\n## Reglas NO negociables\n- no inventes",
            "tenant_config": {"extra": {}, "escalation_threshold": 0.70},
            "conversation_history": [{"role": "user", "content": "quiero cancelar"}],
            "decision": "respond",
            "agent_response": "ok, te ayudo",
            "tool_results": [],
            "cost_usd": 0.01,
            "aop_slug": "cancelacion",
        }

    @pytest.mark.asyncio
    async def test_approve_sets_verdict(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response("approve", reason="todo correcto")
        )

        node = make_supervise_node(fake_deps)
        result = await node(self._base_state())

        assert result["supervisor_verdict"] == "approve"
        assert result["supervisor_reject_kind"] == "n/a"
        assert result["supervisor_reason"] == "todo correcto"

    @pytest.mark.asyncio
    async def test_reject_tactical_sets_retried_and_injects_feedback(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response(
                "reject", reject_kind="tactical", reason="no verificaste el estado"
            )
        )

        state = {**self._base_state(), "supervisor_retried": False}
        node = make_supervise_node(fake_deps)
        result = await node(state)

        assert result["supervisor_verdict"] == "reject"
        assert result["supervisor_reject_kind"] == "tactical"
        assert result.get("supervisor_retried") is True
        # El feedback va en su campo propio (reason lo inyecta como bloque dinámico),
        # NO concatenado al system_prompt: pegarlo al prefijo cacheado rompía el
        # cache hit del retry (#211).
        assert result.get("supervisor_feedback") == "no verificaste el estado"
        assert "system_prompt" not in result

    @pytest.mark.asyncio
    async def test_reject_tactical_after_retry_escalates(self, fake_deps: Any) -> None:
        """Segundo rechazo (tactical con supervisor_retried=True ya seteado) →
        no hay segundo retry: el nodo pone escalation_reason y el grafo escala."""
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response(
                "reject", reject_kind="tactical", reason="sigue mal"
            )
        )

        state = {**self._base_state(), "supervisor_retried": True}
        node = make_supervise_node(fake_deps)
        result = await node(state)

        assert "supervisor_rejected" in result.get("escalation_reason", "")
        assert "supervisor_retried" not in result  # no re-arma otro retry

    @pytest.mark.asyncio
    async def test_reject_structural_sets_escalation_reason(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response(
                "reject", reject_kind="structural", reason="AOP incorrecto"
            )
        )

        node = make_supervise_node(fake_deps)
        result = await node(self._base_state())

        assert result["supervisor_verdict"] == "reject"
        assert "supervisor_rejected" in result.get("escalation_reason", "")

    @pytest.mark.asyncio
    async def test_uses_opus_for_l3_tool(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node
        from apps.api.skills.base import Skill, SkillInput, SkillOutput
        from apps.api.skills.registry import SkillRegistry

        class _FakeInput(SkillInput):
            pass

        class _FakeOutput(SkillOutput):
            pass

        class _L3Skill(Skill):
            slug = "test.l3_supervisor_model"
            description = "test"
            tier = "L3"
            input_schema = _FakeInput
            output_schema = _FakeOutput
            default_threshold = 0.95

            async def execute(self, ctx, inputs):
                return _FakeOutput()

        SkillRegistry._by_slug["test.l3_supervisor_model"] = _L3Skill
        try:
            fake_deps.anthropic.messages.create = AsyncMock(
                return_value=_make_supervisor_response("approve")
            )
            state = {
                **self._base_state(),
                "pending_tool_call": {"slug": "test.l3_supervisor_model", "input": {}},
            }
            node = make_supervise_node(fake_deps)
            await node(state)

            call_args = fake_deps.anthropic.messages.create.call_args
            assert call_args.kwargs["model"] == "claude-opus-4-7"
        finally:
            del SkillRegistry._by_slug["test.l3_supervisor_model"]

    @pytest.mark.asyncio
    async def test_uses_sonnet_for_l1_l2(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response("approve")
        )

        node = make_supervise_node(fake_deps)
        await node(self._base_state())

        call_args = fake_deps.anthropic.messages.create.call_args
        assert call_args.kwargs["model"] == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_accumulates_tokens(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response("approve")
        )

        state = {**self._base_state(), "supervisor_tokens_in": 100, "supervisor_tokens_out": 40}
        node = make_supervise_node(fake_deps)
        result = await node(state)

        assert result["supervisor_tokens_in"] == 300   # 100 prev + 200 mock
        assert result["supervisor_tokens_out"] == 120  # 40 prev + 80 mock

    @pytest.mark.asyncio
    async def test_cached_prefix_counts_in_tokens_and_cost(self, fake_deps: Any) -> None:
        """Caso medido en #331: el prefijo leído de caché entra en tokens y coste."""
        from apps.api.agents.nodes.supervise import make_supervise_node

        response = _make_supervisor_response("approve")
        response.usage = Usage.model_validate(
            {
                "input_tokens": 1684,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 3426,
                "output_tokens": 166,
            }
        )
        fake_deps.anthropic.messages.create = AsyncMock(return_value=response)

        result = await make_supervise_node(fake_deps)(self._base_state())

        assert result["supervisor_model_used"] == "claude-sonnet-4-6"
        assert result["supervisor_tokens_in"] == 1684 + 3426
        # 0.01 previo + 1684 @ $3 + 3426 @ $0.30 + 166 @ $15 = $0.0185698
        assert result["cost_usd"] == pytest.approx(0.0185698)

    @pytest.mark.asyncio
    async def test_emits_reasoning_events(self, fake_deps: Any) -> None:
        from apps.api.agents.nodes.supervise import make_supervise_node

        fake_deps.anthropic.messages.create = AsyncMock(
            return_value=_make_supervisor_response("approve")
        )

        node = make_supervise_node(fake_deps)
        await node(self._base_state())

        events = fake_deps.reasoning_tracker.events
        supervisor_events = [e for e in events if e["phase"] == "supervisor"]
        assert len(supervisor_events) >= 2  # pending + done


# ──────────────────────────────────────────────────────────
# route_after_supervise
# ──────────────────────────────────────────────────────────


class TestRouteAfterSupervise:
    def _route(self, state: dict) -> str:
        from apps.api.agents.graph import route_after_supervise

        return route_after_supervise(state)

    def test_approve_with_pending_tool_goes_to_execute_skill(self):
        assert self._route({
            "supervisor_verdict": "approve",
            "pending_tool_call": {"slug": "s", "input": {}},
        }) == "execute_skill"

    def test_approve_respond_goes_to_respond(self):
        assert self._route({
            "supervisor_verdict": "approve",
            "decision": "respond",
        }) == "respond"

    def test_approve_escalate_goes_to_escalate(self):
        assert self._route({
            "supervisor_verdict": "approve",
            "decision": "escalate",
        }) == "escalate"

    def test_reject_tactical_first_time_goes_to_reason(self):
        # Primer rechazo tactical: nodo setó supervisor_retried=True pero NO escalation_reason
        assert self._route({
            "supervisor_verdict": "reject",
            "supervisor_reject_kind": "tactical",
            "supervisor_retried": True,
            # sin escalation_reason → va a reason
        }) == "reason"

    def test_reject_tactical_second_time_goes_to_escalate(self):
        # Segundo rechazo: el nodo ve supervisor_retried=True y pone
        # escalation_reason (aunque el reject sea tactical) → ruta a escalate.
        assert self._route({
            "supervisor_verdict": "reject",
            "supervisor_reject_kind": "tactical",
            "supervisor_retried": True,
            "escalation_reason": "supervisor_rejected (tactical): sigue mal",
        }) == "escalate"

    def test_reject_structural_goes_to_escalate(self):
        # Rechazo structural: el nodo pone escalation_reason → ruta a escalate
        assert self._route({
            "supervisor_verdict": "reject",
            "supervisor_reject_kind": "structural",
            "escalation_reason": "supervisor_rejected (structural): AOP incorrecto",
        }) == "escalate"

# ──────────────────────────────────────────────────────────
# El supervisor ve la misma evidencia que reason (#261, #327)
# ──────────────────────────────────────────────────────────

_STORE_FACTS = {
    "support_email": "soporte@tienda-ejemplo.es",
    "support_phone": "612 345 678",
    "business_hours": "lunes a viernes de 8 a 16h",
}

_DELIVERED_ORDER = {
    "id": "toolu_1",
    "slug": "shopify.get_order_status",
    "input": {"order_identifier": "#1431"},
    "is_error": False,
    "error": None,
    "output": {"found": True, "order_number": "#1431", "fulfillment_status": "fulfilled"},
}


def _store_state(agent_response: str) -> dict:
    from apps.api.aops.compiler import compile_aop
    from apps.api.db.models import AopWithContent
    from apps.api.tests.conftest import TENANT_ID, make_tenant_configuration

    aop = AopWithContent(
        id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        tenant_id=TENANT_ID,
        slug="order_change",
        workspace="production",
        current_version=1,
        yaml_frontmatter={
            "name": "Cambios de pedido",
            "guardrails": ["No canceles pedidos enviados."],
        },
        body_markdown="Consulta el pedido antes de responder.",
        raw_source="",
    )
    compiled = compile_aop(aop, make_tenant_configuration(), tenant_facts=_STORE_FACTS)
    return {
        "tenant_id": str(TENANT_ID),
        "conversation_id": "22222222-2222-2222-2222-222222222222",
        "aop_slug": "order_change",
        "system_prompt": compiled.system_prompt,
        "tenant_facts": _STORE_FACTS,
        "tenant_config": {"extra": {}, "escalation_threshold": 0.7},
        "conversation_history": [
            {"role": "customer", "content": "Quiero cancelar el pedido #1431."}
        ],
        "tool_results": [_DELIVERED_ORDER],
        "decision": "respond",
        "agent_response": agent_response,
    }


def _sent_to_supervisor(fake_deps: Any) -> str:
    kwargs = fake_deps.anthropic.messages.create.call_args.kwargs
    system = "\n".join(b["text"] for b in kwargs["system"])
    user = "\n".join(m["content"] for m in kwargs["messages"])
    return f"{system}\n{user}"


@pytest.mark.asyncio
async def test_supervisor_sees_tenant_facts(fake_deps: Any) -> None:
    """#327: el supervisor rechazaba como inventados el plazo y los contactos de la tienda
    porque no recibía los datos de la tienda que el agente sí tenía."""
    from apps.api.agents.nodes.supervise import make_supervise_node

    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_supervisor_response("approve")
    )
    await make_supervise_node(fake_deps)(
        _store_state("Tienes 30 días desde la entrega para devolverlo.")
    )

    sent = _sent_to_supervisor(fake_deps)
    assert "Teléfono de soporte: 612 345 678" in sent
    assert "Horario de atención: lunes a viernes de 8 a 16h" in sent


@pytest.mark.asyncio
async def test_store_contacts_are_left_to_the_llm(fake_deps: Any) -> None:
    from apps.api.agents.nodes.supervise import make_supervise_node

    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_supervisor_response("approve", reason="respaldado")
    )
    result = await make_supervise_node(fake_deps)(
        _store_state(
            "No podemos cancelarlo: ya se entregó. Para devolverlo tienes 30 días; "
            "escríbenos a soporte@tienda-ejemplo.es o llámanos al +34 612 34 56 78."
        )
    )

    assert result["supervisor_verdict"] == "approve"
    assert fake_deps.anthropic.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_invented_phone_is_rejected_in_code(fake_deps: Any) -> None:
    from apps.api.agents.nodes.supervise import make_supervise_node

    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_supervisor_response("approve")
    )
    result = await make_supervise_node(fake_deps)(
        _store_state("Para devolverlo llámanos al 911 222 333.")
    )

    assert result["supervisor_verdict"] == "reject"
    assert result["supervisor_reject_kind"] == "tactical"
    assert result["supervisor_retried"] is True
    assert "teléfono acabado en 2333" in result["supervisor_feedback"]
    assert fake_deps.anthropic.messages.create.await_count == 0


@pytest.mark.asyncio
async def test_customer_contact_from_history_is_backed(fake_deps: Any) -> None:
    from apps.api.agents.nodes.supervise import make_supervise_node

    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_supervisor_response("approve")
    )
    state = _store_state("Te escribiremos a carmen.ruiz@correo-ejemplo.com.")
    state["conversation_history"] = [
        {"role": "customer", "content": "Mi email es carmen.ruiz@correo-ejemplo.com"}
    ]
    result = await make_supervise_node(fake_deps)(state)

    assert result["supervisor_verdict"] == "approve"


@pytest.mark.asyncio
async def test_contact_said_only_by_the_ai_earlier_is_not_evidence(fake_deps: Any) -> None:
    from apps.api.agents.nodes.supervise import make_supervise_node

    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_supervisor_response("approve")
    )
    state = _store_state("Como te dije, llama al 911 222 333.")
    state["conversation_history"] = [
        {"role": "customer", "content": "¿Teléfono?"},
        {"role": "agent_ai", "content": "Llama al 911 222 333."},
        {"role": "customer", "content": "¿Cuál era?"},
    ]
    result = await make_supervise_node(fake_deps)(state)

    assert result["supervisor_verdict"] == "reject"


@pytest.mark.asyncio
async def test_contact_quoted_in_supervisor_feedback_is_not_evidence(fake_deps: Any) -> None:
    from apps.api.agents.nodes.supervise import make_supervise_node

    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_supervisor_response("approve")
    )
    state = _store_state("Llámanos al 911 222 333.")
    state["supervisor_feedback"] = "El teléfono 911 222 333 no tiene respaldo."
    state["supervisor_retried"] = True
    result = await make_supervise_node(fake_deps)(state)

    assert result["supervisor_verdict"] == "reject"
    assert result["escalation_reason"].startswith("supervisor_rejected (tactical)")


@pytest.mark.asyncio
async def test_supervisor_sees_whole_history_and_every_tool_output(fake_deps: Any) -> None:
    """Antes veía 3 mensajes (300 caracteres) y 3 herramientas (1500 caracteres)."""
    from apps.api.agents.nodes.supervise import make_supervise_node

    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_supervisor_response("approve")
    )
    state = _store_state("Listo.")
    state["conversation_history"] = [
        {"role": "customer", "content": "Hola, es sobre el pedido #1001."},
        *[{"role": "customer", "content": f"mensaje {i}"} for i in range(5)],
    ]
    long_policy = "Plazo de reembolso: " + "x" * 3000 + " 3-5 días laborables."
    state["tool_results"] = [
        {**_DELIVERED_ORDER, "id": "t0", "output": {"body": long_policy}},
        *[{**_DELIVERED_ORDER, "id": f"t{i}"} for i in range(1, 4)],
    ]
    await make_supervise_node(fake_deps)(state)

    sent = _sent_to_supervisor(fake_deps)
    assert "pedido #1001" in sent
    assert "3-5 días laborables" in sent


@pytest.mark.asyncio
async def test_agent_prompt_is_in_the_cached_prefix(fake_deps: Any) -> None:
    """El system prompt del agente es estable por tenant y AOP: va antes del breakpoint
    de cache; la respuesta y la salida de las herramientas, después."""
    from apps.api.agents.nodes.supervise import make_supervise_node

    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_supervisor_response("approve")
    )
    await make_supervise_node(fake_deps)(_store_state("Ya se entregó, no puedo cancelarlo."))

    kwargs = fake_deps.anthropic.messages.create.call_args.kwargs
    cached = [b["text"] for b in kwargs["system"] if "cache_control" in b]
    assert len(cached) == 1
    assert "Teléfono de soporte: 612 345 678" in cached[0]
    assert "Ya se entregó, no puedo cancelarlo." not in cached[0]
    assert "Ya se entregó, no puedo cancelarlo." in kwargs["messages"][0]["content"]


# ──────────────────────────────────────────────────────────
# Importes con su moneda, comprobados en código (#332)
# ──────────────────────────────────────────────────────────

# get_order_status del trace c7b32bac: pedido en USD.
_USD_ORDER = {
    **_DELIVERED_ORDER,
    "output": {
        "found": True,
        "order_number": "#1431",
        "currency": "USD",
        "line_items": [
            {"line_item_id": 17463441162520, "price": "68.95", "title": "Blusa Satinada"},
            {"line_item_id": 17463441195288, "price": "76.95", "title": "Bolso Bandolera"},
        ],
        "total_price": "145.90",
    },
}


def _usd_order_state(agent_response: str) -> dict:
    state = _store_state(agent_response)
    state["tool_results"] = [_USD_ORDER]
    return state


@pytest.mark.asyncio
async def test_euros_for_a_usd_order_are_rejected_in_code(fake_deps: Any) -> None:
    from apps.api.agents.nodes.supervise import make_supervise_node

    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_supervisor_response("approve")
    )
    result = await make_supervise_node(fake_deps)(
        _usd_order_state("El pedido incluye:\n- Blusa Satinada (68,95 €)\n- Bolso (76,95 €)")
    )

    assert result["supervisor_verdict"] == "reject"
    assert result["supervisor_reject_kind"] == "tactical"
    assert result["supervisor_model_used"] == "code"
    assert "68,95 € (la evidencia lo da en USD); 76,95 € (la evidencia lo da en USD)" in (
        result["supervisor_feedback"]
    )
    assert fake_deps.anthropic.messages.create.await_count == 0


@pytest.mark.asyncio
async def test_amounts_in_the_tool_currency_go_to_the_llm(fake_deps: Any) -> None:
    from apps.api.agents.nodes.supervise import make_supervise_node

    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_supervisor_response("approve")
    )
    result = await make_supervise_node(fake_deps)(
        _usd_order_state("Blusa (68,95 USD) y bolso (76,95 $): total US$145.90. Talla 38.")
    )

    assert result["supervisor_verdict"] == "approve"
    assert fake_deps.anthropic.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_amount_quoted_in_supervisor_feedback_is_not_evidence(fake_deps: Any) -> None:
    from apps.api.agents.nodes.supervise import make_supervise_node

    fake_deps.anthropic.messages.create = AsyncMock(
        return_value=_make_supervisor_response("approve")
    )
    state = _usd_order_state("La blusa costó 68,95 €.")
    state["supervisor_feedback"] = "68,95 € (la evidencia lo da en USD)"
    state["supervisor_retried"] = True
    result = await make_supervise_node(fake_deps)(state)

    assert result["escalation_reason"].startswith("supervisor_rejected (tactical)")
    assert "68,95 €" in result["escalation_reason"]
