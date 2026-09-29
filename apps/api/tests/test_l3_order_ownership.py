"""Gate de ownership en código para skills L3 sobre pedidos (fail-closed).

Hueco visto en el E2E en vivo (ticket #3): el agente preparó un cambio de
dirección del pedido #1429 escrito desde un email que NO era el del pedido.
Ahora, antes de cualquier L3 con `order_id`, el código comprueba que el email
del cliente de la conversación == email del pedido. Si no, no hay aprobación.
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
from apps.api.integrations.base import IntegrationContext
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.tests.conftest import TENANT_ID

MODULE = "apps.api.agents.nodes.execute_skill"
_ORDER = {"id": 7404799197464, "name": "#1429", "email": "Kenny.Medina@ahoracrypto.com"}


def _state(customer_email: str | None, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tenant_id": str(TENANT_ID),
        "conversation_id": "22222222-2222-2222-2222-222222222222",
        "end_customer": {"email": customer_email},
    }
    base.update(overrides)
    return base


def _patch_commerce(monkeypatch: pytest.MonkeyPatch, adapter: Any) -> None:
    def _ctx(state: Any) -> SkillContext:
        return SkillContext(
            tenant_id=str(TENANT_ID),
            conversation_id="c",
            integration_ctx=IntegrationContext(tenant_id=TENANT_ID, credentials={}, config={}),
            commerce_mock=adapter,
            customer_email=(state.get("end_customer") or {}).get("email"),
        )

    monkeypatch.setattr(f"{MODULE}.build_skill_context", _ctx)


def _adapter(order: dict[str, Any] | None = _ORDER, *, fail: bool = False) -> Any:
    adapter = MagicMock()
    adapter.get_order_by_name = AsyncMock(
        side_effect=RuntimeError("shopify down") if fail else None, return_value=order
    )
    adapter.get_order = AsyncMock(return_value=None)
    return adapter


class TestOwnershipCheck:
    @pytest.mark.asyncio
    async def test_non_order_skill_is_not_checked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_commerce(monkeypatch, _adapter())
        assert await execute_skill._l3_ownership_error(_state(None), {"text": "x"}) is None

    @pytest.mark.asyncio
    async def test_owner_passes_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_commerce(monkeypatch, _adapter())
        err = await execute_skill._l3_ownership_error(
            _state(" kenny.medina@AHORACRYPTO.com "), {"order_id": 1429}
        )
        assert err is None

    @pytest.mark.asyncio
    async def test_other_email_is_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_commerce(monkeypatch, _adapter())
        err = await execute_skill._l3_ownership_error(
            _state("2023beginningof@gmail.com"), {"order_id": 1429}
        )
        assert err is not None and err.startswith("order_ownership_not_verified")

    @pytest.mark.asyncio
    async def test_missing_customer_email_is_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_commerce(monkeypatch, _adapter())
        err = await execute_skill._l3_ownership_error(_state(None), {"order_id": 1429})
        assert err is not None and err.startswith("order_ownership_not_verified")

    @pytest.mark.parametrize("adapter", [_adapter(order=None), _adapter(fail=True)])
    @pytest.mark.asyncio
    async def test_unresolvable_order_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, adapter: Any
    ) -> None:
        _patch_commerce(monkeypatch, adapter)
        err = await execute_skill._l3_ownership_error(
            _state("kenny.medina@ahoracrypto.com"), {"order_id": 1429}
        )
        assert err is not None and err.startswith("order_ownership_not_verified")


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
        _patch_commerce(monkeypatch, _adapter())
        create = AsyncMock()
        monkeypatch.setattr(f"{MODULE}.create_pending_approval", create)

        node = make_execute_skill_node(fake_deps)
        result = await node(
            _state(
                "2023beginningof@gmail.com",
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
        assert last["error"].startswith("order_ownership_not_verified")


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
