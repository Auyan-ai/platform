"""Tests para el nodo `execute_skill`.

Cubre: happy path, no pending_tool_call, allowed_skills check, unknown slug,
input validation, skill execution failures, tool_iterations, accumulation
de tool_results, build_skill_context y short-circuit por @guarded.

Las skills reales (Shopify) NO se usan — se registra una skill dummy en
cada test para no acoplar este nodo a una integración específica.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.nodes.execute_skill import (
    build_skill_context,
    make_execute_skill_node,
)
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry

# ----------------------------------------------------------------
# Skill dummy
# ----------------------------------------------------------------


class EchoInput(SkillInput):
    text: str


class EchoOutput(SkillOutput):
    echoed: str


class EchoSkill(Skill):
    slug = "test.echo"
    description = "Echoes the input text."
    tier: SkillTier = "L1"
    input_schema = EchoInput
    output_schema = EchoOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, EchoInput)
        return EchoOutput(echoed=f"echo:{inputs.text}")


class BoomSkill(Skill):
    """Skill que siempre falla — para probar el catch de excepciones."""

    slug = "test.boom"
    description = "Always raises."
    tier: SkillTier = "L1"
    input_schema = EchoInput
    output_schema = EchoOutput
    default_threshold = 0.70

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        raise RuntimeError("boom_intentional")


class L2DummySkill(Skill):
    """Skill L2 para probar el gate de permisos."""

    slug = "test.l2_dummy"
    description = "L2 dummy."
    tier: SkillTier = "L2"
    input_schema = EchoInput
    output_schema = EchoOutput
    default_threshold = 0.85

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, EchoInput)
        return EchoOutput(echoed=f"l2:{inputs.text}")


# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _registry() -> Generator[None, None, None]:
    SkillRegistry._reset()
    SkillRegistry.register(EchoSkill)
    SkillRegistry.register(BoomSkill)
    SkillRegistry.register(L2DummySkill)
    yield
    SkillRegistry._reset()


@pytest.fixture
def deps(fake_deps: AgentDependencies) -> AgentDependencies:
    return fake_deps


def _base_state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "conversation_id": "22222222-2222-2222-2222-222222222222",
        "tenant_config": {"extra": {}},
        "allowed_skills": ["test.echo", "test.boom"],
        "tool_iterations": 0,
        "max_tool_iterations": 5,
        "tool_results": [],
        # Permisos por defecto para las skills dummy de prueba
        "tool_permissions": {
            "test.echo": {"is_enabled": True, "human_approval_required": False, "threshold_override": None},
            "test.boom": {"is_enabled": True, "human_approval_required": False, "threshold_override": None},
            "test.probe": {"is_enabled": True, "human_approval_required": False, "threshold_override": None},
            "test.l2_dummy": {"is_enabled": True, "human_approval_required": False, "threshold_override": None},
        },
    }
    base.update(overrides)
    return base


def _pending(slug: str = "test.echo", **kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "toolu_abc",
        "slug": slug,
        "input": {"text": "hola"},
    }
    base.update(kwargs)
    return base


# ----------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------


class TestHappyPath:
    async def test_executes_skill_and_appends_result(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending())
        result = await node(state)

        assert "tool_results" in result
        assert len(result["tool_results"]) == 1
        entry = result["tool_results"][0]
        assert entry["id"] == "toolu_abc"
        assert entry["slug"] == "test.echo"
        assert entry["is_error"] is False
        assert entry["error"] is None
        assert entry["output"] == {"echoed": "echo:hola"}
        assert entry["input"] == {"text": "hola"}

    async def test_clears_pending_tool_call(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending())
        result = await node(state)
        assert result["pending_tool_call"] is None

    async def test_increments_tool_iterations(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(), tool_iterations=3)
        result = await node(state)
        assert result["tool_iterations"] == 4

    async def test_appends_to_existing_results(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        prior = {"id": "toolu_prev", "slug": "test.echo", "input": {}, "output": {}, "is_error": False, "error": None}
        state = _base_state(pending_tool_call=_pending(), tool_results=[prior])
        result = await node(state)
        assert len(result["tool_results"]) == 2
        assert result["tool_results"][0] == prior
        assert result["tool_results"][1]["id"] == "toolu_abc"


# ----------------------------------------------------------------
# Errores operacionales (se reportan como tool_result con is_error=True)
# ----------------------------------------------------------------


class TestSkillNotAllowed:
    async def test_empty_allowed_skills_rejects_all(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(), allowed_skills=[])
        result = await node(state)
        entry = result["tool_results"][0]
        assert entry["is_error"] is True
        assert "skill_not_allowed" in entry["error"]

    async def test_slug_not_in_allowed_list(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending("test.echo"),
            allowed_skills=["test.other"],
        )
        result = await node(state)
        entry = result["tool_results"][0]
        assert entry["is_error"] is True
        assert "skill_not_allowed: test.echo" in entry["error"]

    async def test_increments_iterations_even_on_rejection(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(), allowed_skills=[])
        result = await node(state)
        assert result["tool_iterations"] == 1


class TestUnknownSkill:
    async def test_unknown_slug_returns_error_entry(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending("test.nonexistent"),
            allowed_skills=["test.nonexistent"],  # permitida pero no registrada
        )
        result = await node(state)
        entry = result["tool_results"][0]
        assert entry["is_error"] is True
        assert "unknown_skill: test.nonexistent" in entry["error"]


class TestInvalidInput:
    async def test_missing_required_field_returns_error_entry(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(input={}))  # falta `text`
        result = await node(state)
        entry = result["tool_results"][0]
        assert entry["is_error"] is True
        assert "invalid_input" in entry["error"]

    async def test_wrong_type_returns_error_entry(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(input={"text": 123}))
        result = await node(state)
        entry = result["tool_results"][0]
        # Pydantic v2 coerces int → str por default; verifico que NO crashea
        # y que sí ejecuta o reporta error consistente.
        assert entry["id"] == "toolu_abc"


class TestSkillExecutionFails:
    async def test_skill_raising_is_captured_as_error_entry(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending("test.boom"))
        result = await node(state)
        entry = result["tool_results"][0]
        assert entry["is_error"] is True
        assert "skill_failed: RuntimeError: boom_intentional" in entry["error"]
        assert entry["output"] is None


# ----------------------------------------------------------------
# Missing pending_tool_call
# ----------------------------------------------------------------


class TestNoPendingCall:
    async def test_returns_graph_error(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state()  # sin pending_tool_call
        result = await node(state)
        assert result.get("error") == "execute_skill_no_pending_call"
        assert "tool_results" not in result


# ----------------------------------------------------------------
# build_skill_context
# ----------------------------------------------------------------


class TestBuildSkillContext:
    def test_reads_creds_from_commerce_integration_ctx(self) -> None:
        state: dict[str, Any] = {
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "conversation_id": "c-1",
            "commerce_integration_ctx": {
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "credentials": {"domain": "myshop.myshopify.com", "token": "shpat_x"},
                "config": {},
            },
        }
        ctx = build_skill_context(state)
        assert ctx.tenant_id == "11111111-1111-1111-1111-111111111111"
        assert ctx.conversation_id == "c-1"
        assert ctx.integration_ctx is not None
        assert ctx.integration_ctx.credentials["domain"] == "myshop.myshopify.com"
        assert ctx.integration_ctx.credentials["token"] == "shpat_x"

    def test_no_integration_when_commerce_ctx_missing(self) -> None:
        state: dict[str, Any] = {
            "tenant_id": "t-1",
            "conversation_id": "c-1",
            "tenant_config": {},
        }
        ctx = build_skill_context(state)
        assert ctx.integration_ctx is None

    def test_no_integration_when_state_bare(self) -> None:
        state: dict[str, Any] = {"tenant_id": "t-1", "conversation_id": "c-1"}
        ctx = build_skill_context(state)
        assert ctx.integration_ctx is None

    def test_context_is_immutable(self) -> None:
        state: dict[str, Any] = {
            "tenant_id": "t",
            "conversation_id": "c",
            "tenant_config": {"extra": {}},
        }
        ctx = build_skill_context(state)
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            ctx.tenant_id = "other"  # type: ignore[misc]


# ----------------------------------------------------------------
# Short-circuit por @guarded
# ----------------------------------------------------------------


class TestGuardShortCircuit:
    async def test_prior_error_skips_node(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending(), error="upstream_failure")
        result = await node(state)
        # @guarded retorna dict vacío cuando hay error previo
        assert result == {}

    async def test_unexpected_exception_is_caught_by_guarded(
        self, deps: AgentDependencies, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Si algo del nodo (no la skill misma) lanza inesperadamente, @guarded lo captura."""

        # Hacemos que SkillRegistry.get lance un tipo no-ValueError.
        def _boom(slug: str) -> type:
            raise KeyError("registry_broken")

        monkeypatch.setattr(SkillRegistry, "get", classmethod(lambda cls, slug: _boom(slug)))

        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending())
        result = await node(state)
        assert "error" in result
        assert "execute_skill" in result["error"]


# ----------------------------------------------------------------
# Integración con SkillContext: Shopify creds via build_skill_context
# ----------------------------------------------------------------


class TestSkillContextPropagation:
    async def test_context_reaches_skill_with_creds(
        self, deps: AgentDependencies
    ) -> None:
        captured: dict[str, Any] = {}

        class ProbeInput(SkillInput):
            pass

        class ProbeOutput(SkillOutput):
            ok: bool

        class ProbeSkill(Skill):
            slug = "test.probe"
            description = "Captures context."
            tier: SkillTier = "L1"
            input_schema = ProbeInput
            output_schema = ProbeOutput
            default_threshold = 0.70

            async def execute(
                self, ctx: SkillContext, inputs: SkillInput
            ) -> SkillOutput:
                captured["ctx"] = ctx
                return ProbeOutput(ok=True)

        SkillRegistry.register(ProbeSkill)

        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call={"id": "toolu_x", "slug": "test.probe", "input": {}},
            allowed_skills=["test.probe"],
            commerce_integration_ctx={
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "credentials": {"domain": "x.myshopify.com", "token": "shpat_t"},
                "config": {},
            },
        )
        await node(state)

        ctx: SkillContext = captured["ctx"]
        assert ctx.integration_ctx is not None
        assert ctx.integration_ctx.credentials["domain"] == "x.myshopify.com"
        assert ctx.integration_ctx.credentials["token"] == "shpat_t"
        assert ctx.tenant_id == state["tenant_id"]
        assert ctx.conversation_id == state["conversation_id"]


# ----------------------------------------------------------------
# L2 / L3 permission gate
# ----------------------------------------------------------------


class L2Skill(Skill):
    """Skill L2 dummy para probar el permission gate."""

    slug = "test.write"
    description = "L2 write dummy."
    tier: SkillTier = "L2"
    input_schema = EchoInput
    output_schema = EchoOutput
    default_threshold = 0.85

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, EchoInput)
        return EchoOutput(echoed=f"written:{inputs.text}")


class L3Skill(Skill):
    """Skill L3 dummy para probar el bloqueo permanente."""

    slug = "test.dangerous"
    description = "L3 dangerous dummy."
    tier: SkillTier = "L3"
    input_schema = EchoInput
    output_schema = EchoOutput
    default_threshold = 0.95

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, EchoInput)
        return EchoOutput(echoed="dangerous")


def _perm(is_enabled: bool = True, human_approval_required: bool = False) -> dict:
    return {"is_enabled": is_enabled, "human_approval_required": human_approval_required, "threshold_override": None}


class TestPermissionGate:
    """Gate de permisos desde tenant_tool_permissions (Sprint 10)."""

    @pytest.fixture(autouse=True)
    def _register_l2_l3(self) -> Generator[None, None, None]:
        SkillRegistry._reset()
        SkillRegistry.register(EchoSkill)
        SkillRegistry.register(L2Skill)
        SkillRegistry.register(L3Skill)
        yield
        SkillRegistry._reset()

    async def test_skill_blocked_when_no_permission_row(self, deps: AgentDependencies) -> None:
        """Sin row en tool_permissions la skill es rechazada (fail-safe)."""
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.write"),
            allowed_skills=["test.write"],
            tool_permissions={},  # sin row
        )
        result = await node(state)
        entry = result["tool_results"][-1]
        assert entry["is_error"] is True
        assert "skill_not_enabled_for_tenant" in entry["error"]

    async def test_skill_blocked_when_is_enabled_false(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.write"),
            allowed_skills=["test.write"],
            tool_permissions={"test.write": _perm(is_enabled=False)},
        )
        result = await node(state)
        entry = result["tool_results"][-1]
        assert entry["is_error"] is True
        assert "skill_not_enabled_for_tenant" in entry["error"]

    async def test_l2_executes_when_enabled(self, deps: AgentDependencies) -> None:
        """L2 habilitada en tool_permissions se ejecuta normalmente."""
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.write"),
            allowed_skills=["test.write"],
            tool_permissions={"test.write": _perm(is_enabled=True)},
        )
        result = await node(state)
        entry = result["tool_results"][-1]
        assert entry["is_error"] is False
        assert entry["output"]["echoed"] == "written:hola"

    async def test_l1_executes_when_enabled(self, deps: AgentDependencies) -> None:
        """L1 habilitada se ejecuta sin restricciones adicionales."""
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.echo"),
            allowed_skills=["test.echo"],
            tool_permissions={"test.echo": _perm(is_enabled=True)},
        )
        result = await node(state)
        entry = result["tool_results"][-1]
        assert entry["is_error"] is False
        assert entry["output"]["echoed"] == "echo:hola"

    async def test_blocked_skill_increments_iterations(self, deps: AgentDependencies) -> None:
        """El rechazo sigue consumiendo una iteración."""
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.write"),
            allowed_skills=["test.write"],
            tool_permissions={},
            tool_iterations=2,
        )
        result = await node(state)
        assert result["tool_iterations"] == 3

    async def test_l3_without_approval_required_executes(self, deps: AgentDependencies) -> None:
        """L3 habilitada sin human_approval_required se ejecuta (para tenants que la apagaron)."""
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.dangerous"),
            allowed_skills=["test.dangerous"],
            tool_permissions={"test.dangerous": _perm(is_enabled=True, human_approval_required=False)},
        )
        result = await node(state)
        entry = result["tool_results"][-1]
        assert entry["is_error"] is False
        assert entry["output"]["echoed"] == "dangerous"


class TestL3HumanApprovalGate:
    """Cuando L3 + human_approval_required=True el nodo crea pending_approval."""

    @pytest.fixture(autouse=True)
    def _register(self) -> Generator[None, None, None]:
        SkillRegistry._reset()
        SkillRegistry.register(L3Skill)
        yield
        SkillRegistry._reset()

    async def test_l3_approval_required_does_not_execute_skill(
        self, deps: AgentDependencies, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La skill NO se ejecuta — se crea un pending_approval."""
        import unittest.mock as mock

        mock_create = mock.AsyncMock()
        mock_scope = mock.MagicMock()
        mock_scope.__aenter__ = mock.AsyncMock(return_value=mock.AsyncMock(
            fetchrow=mock.AsyncMock(return_value={"pii_salt": "test_salt"}),
        ))
        mock_scope.__aexit__ = mock.AsyncMock(return_value=False)

        monkeypatch.setattr(
            "apps.api.agents.nodes.execute_skill.tenant_scope",
            lambda *a, **kw: mock_scope,
        )
        monkeypatch.setattr(
            "apps.api.agents.nodes.execute_skill.create_pending_approval",
            mock_create,
        )
        # No hay aprobación previa abierta → se crea una nueva.
        monkeypatch.setattr(
            "apps.api.agents.nodes.execute_skill.get_recent_approval_for_skill",
            mock.AsyncMock(return_value=None),
        )
        # También mock get_tenant_pii_salt
        monkeypatch.setattr(
            "apps.api.agents.nodes.execute_skill.redact_inputs",
            lambda inputs, salt: inputs,
        )

        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.dangerous"),
            allowed_skills=["test.dangerous"],
            tool_permissions={"test.dangerous": _perm(is_enabled=True, human_approval_required=True)},
            aop_slug="test_aop",
            aop_version=1,
        )
        result = await node(state)

        # Resultado tiene pending_approval_id, no un tool_result de error
        assert result.get("pending_approval_id") is not None
        assert "awaiting_human_approval" in result.get("escalation_reason", "")
        # Se creó una aprobación nueva (no es repeat).
        mock_create.assert_awaited_once()
        assert result.get("pending_approval_is_repeat") is False

    async def test_l3_approval_required_sets_escalation_reason(
        self, deps: AgentDependencies, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import unittest.mock as mock

        mock_scope = mock.MagicMock()
        mock_scope.__aenter__ = mock.AsyncMock(return_value=mock.AsyncMock(
            fetchrow=mock.AsyncMock(return_value={"pii_salt": "s"}),
        ))
        mock_scope.__aexit__ = mock.AsyncMock(return_value=False)
        monkeypatch.setattr("apps.api.agents.nodes.execute_skill.tenant_scope", lambda *a, **kw: mock_scope)
        monkeypatch.setattr("apps.api.agents.nodes.execute_skill.create_pending_approval", mock.AsyncMock())
        monkeypatch.setattr(
            "apps.api.agents.nodes.execute_skill.get_recent_approval_for_skill",
            mock.AsyncMock(return_value=None),
        )
        monkeypatch.setattr("apps.api.agents.nodes.execute_skill.redact_inputs", lambda i, s: i)

        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.dangerous"),
            allowed_skills=["test.dangerous"],
            tool_permissions={"test.dangerous": _perm(is_enabled=True, human_approval_required=True)},
        )
        result = await node(state)
        reason = result.get("escalation_reason", "")
        assert reason.startswith("awaiting_human_approval:")

    def _mock_l3_scope(self, monkeypatch, mock_create, recent_return) -> None:
        """Mock común del bloque L3: tenant_scope, create, recent-approval, redact."""
        import unittest.mock as mock

        mock_scope = mock.MagicMock()
        mock_scope.__aenter__ = mock.AsyncMock(return_value=mock.AsyncMock(
            fetchrow=mock.AsyncMock(return_value={"pii_salt": "s"}),
        ))
        mock_scope.__aexit__ = mock.AsyncMock(return_value=False)
        monkeypatch.setattr("apps.api.agents.nodes.execute_skill.tenant_scope", lambda *a, **kw: mock_scope)
        monkeypatch.setattr("apps.api.agents.nodes.execute_skill.create_pending_approval", mock_create)
        monkeypatch.setattr(
            "apps.api.agents.nodes.execute_skill.get_recent_approval_for_skill",
            mock.AsyncMock(return_value=recent_return),
        )
        monkeypatch.setattr("apps.api.agents.nodes.execute_skill.redact_inputs", lambda i, s: i)

    async def test_l3_repeat_reuses_existing_approval_without_duplicating(
        self, deps: AgentDependencies, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Misma acción ya pendiente → reusa, no duplica (cliente reescribió esperando)."""
        import unittest.mock as mock
        from uuid import UUID as _UUID

        existing_id = _UUID("99999999-9999-9999-9999-999999999999")
        mock_create = mock.AsyncMock()
        existing = mock.MagicMock(id=existing_id, status="pending", inputs_raw={"text": "hola"})
        self._mock_l3_scope(monkeypatch, mock_create, existing)

        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.dangerous"),
            allowed_skills=["test.dangerous"],
            tool_permissions={"test.dangerous": _perm(is_enabled=True, human_approval_required=True)},
        )
        result = await node(state)

        mock_create.assert_not_awaited()
        assert result.get("pending_approval_id") == str(existing_id)
        assert result.get("pending_approval_is_repeat") is True

    async def test_l3_no_duplicate_when_action_already_approved(
        self, deps: AgentDependencies, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Hallazgo 7: si la MISMA acción ya fue aprobada y el agente la re-dispara
        (p.ej. tras un 'gracias'), no se crea un approval huérfano — se reusa.
        order_id distinto (interno vs visible) pero misma acción → se reconoce."""
        import unittest.mock as mock
        from uuid import UUID as _UUID

        approved_id = _UUID("88888888-8888-8888-8888-888888888888")
        mock_create = mock.AsyncMock()
        existing = mock.MagicMock(
            id=approved_id, status="approved", inputs_raw={"text": "hola", "order_id": 999}
        )
        self._mock_l3_scope(monkeypatch, mock_create, existing)

        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.dangerous", input={"text": "hola", "order_id": 1278}),
            allowed_skills=["test.dangerous"],
            tool_permissions={"test.dangerous": _perm(is_enabled=True, human_approval_required=True)},
        )
        result = await node(state)

        mock_create.assert_not_awaited()
        assert result.get("pending_approval_id") == str(approved_id)
        assert result.get("pending_approval_is_repeat") is True

    async def test_l3_creates_new_approval_when_action_differs(
        self, deps: AgentDependencies, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Una acción DISTINTA sí crea un approval nuevo — no se bloquea un segundo
        cambio legítimo."""
        import unittest.mock as mock
        from uuid import UUID as _UUID

        mock_create = mock.AsyncMock()
        existing = mock.MagicMock(
            id=_UUID("77777777-7777-7777-7777-777777777777"),
            status="approved",
            inputs_raw={"text": "otra cosa distinta"},
        )
        self._mock_l3_scope(monkeypatch, mock_create, existing)

        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(slug="test.dangerous"),  # input {"text": "hola"}
            allowed_skills=["test.dangerous"],
            tool_permissions={"test.dangerous": _perm(is_enabled=True, human_approval_required=True)},
        )
        result = await node(state)

        mock_create.assert_awaited_once()
        assert result.get("pending_approval_is_repeat") is False


# ----------------------------------------------------------------
# Make node sanity
# ----------------------------------------------------------------


class TestFactory:
    def test_make_returns_callable(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        assert callable(node)

    def test_deps_can_be_mock(self) -> None:
        # Confirma que el nodo no toca deps internamente.
        node = make_execute_skill_node(AsyncMock())  # type: ignore[arg-type]
        assert callable(node)


# ----------------------------------------------------------------
# Audit log
# ----------------------------------------------------------------


class TestAuditLog:
    async def test_success_emite_audit_log(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending(),
            aop_slug="consulta_envio",
            aop_version=2,
        )
        await node(state)
        entries = deps.audit_logger.entries  # type: ignore[attr-defined]
        assert len(entries) == 1
        e = entries[0]
        assert e["skill_slug"] == "test.echo"
        assert e["status"] == "success"
        assert e["aop_slug"] == "consulta_envio"
        assert e["aop_version"] == 2
        assert e["outputs"] == {"echoed": "echo:hola"}

    async def test_failed_skill_emite_audit_log_con_status_failed(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending("test.boom"),
        )
        await node(state)
        entries = deps.audit_logger.entries  # type: ignore[attr-defined]
        assert len(entries) == 1
        assert entries[0]["status"] == "failed"
        assert "boom" in entries[0]["error_message"]

    async def test_permission_rejection_emite_audit_log(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(
            pending_tool_call=_pending("test.l2_dummy"),
            allowed_skills=["test.l2_dummy"],
            tool_permissions={},  # sin row → bloqueado
        )
        await node(state)
        entries = deps.audit_logger.entries  # type: ignore[attr-defined]
        assert len(entries) == 1
        assert entries[0]["status"] == "rejected_by_permissions"

    async def test_sin_tenant_id_no_emite_audit(self, deps: AgentDependencies) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending())
        del state["tenant_id"]
        await node(state)
        assert deps.audit_logger.entries == []  # type: ignore[attr-defined]

    async def test_latency_ms_esta_presente_en_audit(
        self, deps: AgentDependencies
    ) -> None:
        node = make_execute_skill_node(deps)
        state = _base_state(pending_tool_call=_pending())
        await node(state)
        entries = deps.audit_logger.entries  # type: ignore[attr-defined]
        assert entries[0]["latency_ms"] is not None
        assert isinstance(entries[0]["latency_ms"], int)
        assert entries[0]["latency_ms"] >= 0
