"""Gate de identidad en código para skills sobre pedidos (fail-closed).

Hueco visto en el E2E en vivo (ticket #3): el agente preparó un cambio de
dirección del pedido #1429 escrito desde un email que NO era el del pedido.
Ahora, antes de cualquier skill con pedido, el código comprueba que la identidad
verificada del mensaje toca el pedido. Si no, no hay aprobación.
Principio (Decagon): la validación sensible la hace el código, no el LLM.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes import execute_skill
from apps.api.agents.nodes.execute_skill import make_execute_skill_node
from apps.api.services.identity_messages import DEFAULT_MESSAGES
from apps.api.skills.base import (
    Skill,
    SkillContext,
    SkillInput,
    SkillOutput,
    SkillRefusal,
    SkillTier,
)
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify.cancel_order import CancelOrder
from apps.api.tests.identity_support import identity_state, patch_commerce

MODULE = "apps.api.agents.nodes.execute_skill"
_ORDER = {"id": 7404799197464, "name": "#1429", "email": "Kenny.Medina@ahoracrypto.com"}


def _adapter(order: dict[str, Any] | None = _ORDER, *, fail: bool = False) -> Any:
    adapter = MagicMock()
    adapter.get_order_by_name = AsyncMock(
        side_effect=RuntimeError("shopify down") if fail else None, return_value=order
    )
    adapter.get_order = AsyncMock(return_value=None)
    return adapter


async def _error(email: str | None, raw_input: dict[str, Any]) -> str | None:
    blocked = await execute_skill._identity_gate(
        identity_state(email=email), CancelOrder, raw_input
    )
    return None if blocked is None else blocked[1]


class TestOwnershipCheck:
    @pytest.mark.asyncio
    async def test_non_order_skill_is_not_checked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api.skills.shopify.get_product_info import GetProductInfo

        patch_commerce(monkeypatch, _adapter())
        blocked = await execute_skill._identity_gate(
            identity_state(), GetProductInfo, {"query": "x"}
        )
        assert blocked is None

    @pytest.mark.asyncio
    async def test_owner_passes_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        patch_commerce(monkeypatch, _adapter())
        assert await _error(" kenny.medina@AHORACRYPTO.com ", {"order_id": 1429}) is None

    @pytest.mark.asyncio
    async def test_other_email_is_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        patch_commerce(monkeypatch, _adapter())
        err = await _error("2023beginningof@gmail.com", {"order_id": 1429})
        assert err is not None and err.startswith("identity_required")

    @pytest.mark.asyncio
    async def test_missing_customer_email_is_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        patch_commerce(monkeypatch, _adapter())
        err = await _error(None, {"order_id": 1429})
        assert err is not None and err.startswith("identity_required")

    @pytest.mark.asyncio
    async def test_input_without_order_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        patch_commerce(monkeypatch, _adapter())
        err = await _error("kenny.medina@ahoracrypto.com", {"text": "x"})
        assert err is not None and err.startswith("identity_required")

    @pytest.mark.asyncio
    async def test_missing_order_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        patch_commerce(monkeypatch, _adapter(order=None))
        err = await _error("kenny.medina@ahoracrypto.com", {"order_id": 1429})
        assert err is not None and err.startswith("identity_required")

    @pytest.mark.asyncio
    async def test_store_down_is_not_an_identity_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pedirle al cliente más datos no arregla una tienda caída (EX-01): se escala.
        patch_commerce(monkeypatch, _adapter(fail=True))
        with pytest.raises(SkillRefusal) as refusal:
            await _error("kenny.medina@ahoracrypto.com", {"order_id": 1429})
        assert refusal.value.code == "commerce_unavailable"
        assert refusal.value.team_reason.startswith("commerce_unavailable:")
        assert refusal.value.customer_message == DEFAULT_MESSAGES["commerce_unavailable"]


class _OrderInput(SkillInput):
    order_id: int


class _Out(SkillOutput):
    ok: bool = True


class _L3OrderSkill(Skill):
    slug = "test.cancel"
    description = "L3 sobre pedido."
    tier: SkillTier = "L3"
    input_schema = _OrderInput
    output_schema = _Out
    default_threshold = 0.95
    identity_scope = "order"
    min_level = "guest"

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        return _Out()


class TestNodeGate:
    @pytest.fixture(autouse=True)
    def _register(self) -> Generator[None, None, None]:
        SkillRegistry._reset()
        SkillRegistry.register(_L3OrderSkill)
        yield
        SkillRegistry._reset()

    @pytest.mark.asyncio
    async def test_mismatch_creates_no_approval_and_returns_error(
        self, fake_deps: AgentDependencies, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch_commerce(monkeypatch, _adapter())
        create = AsyncMock()
        monkeypatch.setattr(f"{MODULE}.create_pending_approval", create)

        node = make_execute_skill_node(fake_deps)
        result = await node(
            identity_state(
                email="2023beginningof@gmail.com",
                pending_tool_call={"id": "t1", "slug": "test.cancel", "input": {"order_id": 1429}},
                allowed_skills=["test.cancel"],
                tool_permissions={
                    "test.cancel": {
                        "is_enabled": True,
                        "human_approval_required": True,
                        "threshold_override": None,
                    }
                },
                tool_results=[],
                tool_iterations=0,
                max_tool_iterations=5,
            )
        )

        create.assert_not_awaited()
        assert result.get("pending_approval_id") is None
        last = result["tool_results"][-1]
        assert last["is_error"] is True
        assert last["error"].startswith("identity_required")

    @pytest.mark.asyncio
    async def test_store_down_escalates_with_fixed_text_and_no_approval(
        self, fake_deps: AgentDependencies, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch_commerce(monkeypatch, _adapter(fail=True))
        create = AsyncMock()
        monkeypatch.setattr(f"{MODULE}.create_pending_approval", create)

        node = make_execute_skill_node(fake_deps)
        result = await node(
            identity_state(
                email="kenny.medina@ahoracrypto.com",
                pending_tool_call={"id": "t1", "slug": "test.cancel", "input": {"order_id": 1429}},
                allowed_skills=["test.cancel"],
                tool_permissions={
                    "test.cancel": {
                        "is_enabled": True,
                        "human_approval_required": True,
                        "threshold_override": None,
                    }
                },
                tool_results=[],
                tool_iterations=0,
                max_tool_iterations=5,
            )
        )

        create.assert_not_awaited()
        assert result["decision"] == "escalate"
        assert result["escalation_reason"].startswith("commerce_unavailable:")
        assert result["agent_response"] == DEFAULT_MESSAGES["commerce_unavailable"]


class TestSimulatorOrdersBelongToSimCustomer:
    def test_assigns_email_to_order_fixtures(self) -> None:
        from apps.api.simulator.runner import assign_mock_orders_to_customer

        fixtures = {"shopify": {"get_order_by_name": {"id": 1, "name": "#1234"}}}
        out = assign_mock_orders_to_customer(fixtures, "sim-1@simulator.auyan.internal")
        assert out["shopify"]["get_order_by_name"]["email"] == "sim-1@simulator.auyan.internal"
        assert "email" not in fixtures["shopify"]["get_order_by_name"]  # no muta

    def test_respects_explicit_email_and_errors(self) -> None:
        from apps.api.simulator.runner import assign_mock_orders_to_customer

        fixtures = {
            "shopify": {
                "get_order_by_name": {"id": 1, "email": "otro@x.com"},
                "get_order": {"_error": "NOT_FOUND"},
            }
        }
        out = assign_mock_orders_to_customer(fixtures, "sim@x")
        assert out["shopify"]["get_order_by_name"]["email"] == "otro@x.com"
        assert out["shopify"]["get_order"] == {"_error": "NOT_FOUND"}
