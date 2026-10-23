"""Tests para routers/approvals.py, services/approval_execution.py y routers/tool_permissions.py.

Las carreras entre peticiones se prueban contra Postgres real en `test_approvals_pg.py`.
Aquí, con la base mockeada, cada rama del cierre de una ejecución.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.db.models import PendingApproval, TenantToolPermission
from apps.api.integrations.base import MutationNotApplied
from apps.api.routers.approvals import router as approvals_router
from apps.api.routers.tool_permissions import router as tool_permissions_router
from apps.api.skills.base import (
    ReconcileUnknown,
    Skill,
    SkillContext,
    SkillInput,
    SkillOutput,
    SkillRefusal,
)
from apps.api.tests.conftest import TENANT_ID
from fastapi import FastAPI
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret-for-unit-tests-32b!"
JWT_ALG = "HS256"
JWT_AUD = "authenticated"
USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CONVERSATION_ID = UUID("22222222-2222-2222-2222-222222222222")
APPROVAL_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
MESSAGE_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
NOW = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)

ROUTER = "apps.api.routers.approvals"
SERVICE = "apps.api.services.approval_execution"


class _SecretWrap:
    def get_secret_value(self) -> str:
        return JWT_SECRET


@dataclass
class FakeAuthSettings:
    auth_user_cache_maxsize: int = 1000
    auth_user_cache_ttl_seconds: int = 60
    supabase_jwt_algorithm: str = JWT_ALG
    supabase_jwt_audience: str = JWT_AUD

    @property
    def supabase_jwt_secret(self) -> _SecretWrap:
        return _SecretWrap()


def _make_jwt() -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(USER_ID),
        "role": "authenticated",
        "aud": JWT_AUD,
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


AUTH = {"Authorization": f"Bearer {_make_jwt()}"}


def _sample_approval(status: str = "pending", **overrides: Any) -> PendingApproval:
    return PendingApproval(
        **{
            "id": APPROVAL_ID,
            "tenant_id": TENANT_ID,
            "conversation_id": CONVERSATION_ID,
            "skill_slug": "shopify.cancel_order",
            "skill_tier": "L3",
            "inputs_raw": {"order_id": 1001},
            "inputs_redacted": {"order_id": 1001},
            "aop_slug": "cancelaciones",
            "aop_version": 1,
            "langfuse_trace_id": None,
            "status": status,
            "reviewed_by": USER_ID if status != "pending" else None,
            "created_at": NOW,
            **overrides,
        }
    )


class _Input(SkillInput):
    order_id: int


class _Output(SkillOutput):
    cancelled: bool = True


class FakeSkill(Skill):
    """L3 de prueba. `outcome` decide qué hace `execute` y `found` qué ve `reconcile`."""

    slug = "shopify.cancel_order"
    description = "fake"
    tier = "L3"
    input_schema = _Input
    output_schema = _Output
    requires_idempotency = True
    default_threshold = 0.95

    outcome: ClassVar[Any] = None
    found: ClassVar[Any] = ReconcileUnknown("sin lectura")
    seen_ctx: ClassVar[SkillContext | None] = None
    executions: ClassVar[int] = 0

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        type(self).seen_ctx = ctx
        type(self).executions += 1
        if isinstance(type(self).outcome, BaseException):
            raise type(self).outcome
        if isinstance(type(self).outcome, dict):
            return MagicMock(model_dump=lambda mode: type(self).outcome)  # type: ignore[return-value]
        return _Output()

    async def reconcile(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput | None:
        if isinstance(type(self).found, BaseException):
            raise type(self).found
        return type(self).found


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_user_cache()
    yield  # type: ignore[misc]
    reset_user_cache()


@dataclass
class Wiring:
    claim: AsyncMock
    reject: AsyncMock
    settle_cas: AsyncMock
    insert_message: AsyncMock
    deliver: AsyncMock
    release_all: AsyncMock
    release_own: AsyncMock
    hand_off: AsyncMock
    push: AsyncMock
    finalize: AsyncMock
    conversation: MagicMock


def _wire(monkeypatch: pytest.MonkeyPatch, *, channel: str = "zendesk", delivered: bool = True):
    """La base y el helpdesk mockeados para el router y el servicio."""
    FakeSkill.outcome = None
    FakeSkill.found = ReconcileUnknown("sin lectura")
    FakeSkill.seen_ctx = None
    FakeSkill.executions = 0

    @asynccontextmanager
    async def _fake_scope(*args: Any, **kwargs: Any) -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    conversation = MagicMock()
    conversation.channel = channel
    w = Wiring(
        claim=AsyncMock(return_value=_sample_approval("executing", execution_attempt=1)),
        reject=AsyncMock(return_value=_sample_approval("rejected")),
        settle_cas=AsyncMock(
            side_effect=lambda conn, *, tenant_id, approval_id, execution_attempt, new_status: (
                _sample_approval(new_status)
            )
        ),
        insert_message=AsyncMock(return_value=MagicMock(id=MESSAGE_ID)),
        deliver=AsyncMock(return_value=delivered),
        release_all=AsyncMock(return_value=1),
        release_own=AsyncMock(return_value=True),
        hand_off=AsyncMock(return_value=UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")),
        push=AsyncMock(return_value=True),
        finalize=AsyncMock(return_value=True),
        conversation=conversation,
    )
    patches: dict[str, Any] = {
        f"{ROUTER}.tenant_scope": _fake_scope,
        f"{SERVICE}.tenant_scope": _fake_scope,
        f"{ROUTER}.get_pending_approval": AsyncMock(return_value=_sample_approval()),
        f"{ROUTER}.is_simulation_conversation": AsyncMock(return_value=False),
        f"{ROUTER}.SkillRegistry.get": lambda slug: FakeSkill,
        f"{ROUTER}.claim_pending_approval": w.claim,
        f"{ROUTER}.reject_pending_approval": w.reject,
        f"{ROUTER}.get_tenant_configuration": AsyncMock(return_value=None),
        f"{ROUTER}.conversation_text_languages": AsyncMock(return_value=("es", "es")),
        f"{ROUTER}.get_conversation": AsyncMock(return_value=conversation),
        f"{ROUTER}.release_approval_escalation": w.release_own,
        f"{SERVICE}.get_tenant_configuration": AsyncMock(return_value=None),
        f"{SERVICE}.build_commerce_integration_ctx": AsyncMock(return_value=None),
        f"{SERVICE}.conversation_text_languages": AsyncMock(return_value=("es", "es")),
        f"{SERVICE}.settle_executing_approval": w.settle_cas,
        f"{SERVICE}.insert_message": w.insert_message,
        f"{SERVICE}.update_conversation_last_message": AsyncMock(return_value=None),
        f"{SERVICE}.get_conversation": AsyncMock(return_value=conversation),
        f"{SERVICE}.deliver_message_to_helpdesk": w.deliver,
        f"{SERVICE}.release_escalations_after_executed_action": w.release_all,
        f"{SERVICE}.hand_approval_to_team": w.hand_off,
        f"{SERVICE}.push_escalation_to_helpdesk_safe": w.push,
        f"{SERVICE}.finalize_agent_resolution": w.finalize,
        f"{SERVICE}.get_settings": lambda: FakeAuthSettings(),
    }
    for target, value in patches.items():
        monkeypatch.setattr(target, value)
    return w


def _make_app(monkeypatch: pytest.MonkeyPatch, router_under_test=None) -> tuple[FastAPI, TestClient]:
    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord:
        return UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="a@b.com")

    @asynccontextmanager
    async def _fake_scope(*args: Any, **kwargs: Any) -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    monkeypatch.setattr("apps.api.core.security._lookup_user", _fake_lookup)
    monkeypatch.setattr(f"{ROUTER}.tenant_scope", _fake_scope)
    monkeypatch.setattr("apps.api.routers.tool_permissions.tenant_scope", _fake_scope)

    from apps.api.core.config import get_settings

    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    for r in [router_under_test] if router_under_test else [approvals_router, tool_permissions_router]:
        app.include_router(r)
    return app, TestClient(app, raise_server_exceptions=False)


def _approve(client: TestClient) -> Any:
    return client.post(f"/approvals/{APPROVAL_ID}/approve", json={"comment": "ok"}, headers=AUTH)


def _reject(client: TestClient, comment: str = "No procede") -> Any:
    return client.post(f"/approvals/{APPROVAL_ID}/reject", json={"comment": comment}, headers=AUTH)


# ----------------------------------------------------------------
# GET /approvals
# ----------------------------------------------------------------


class TestListApprovals:
    def test_returns_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            f"{ROUTER}.list_pending_approvals", AsyncMock(return_value=[_sample_approval()])
        )
        _app, client = _make_app(monkeypatch, approvals_router)
        resp = client.get("/approvals", headers=AUTH)

        assert resp.status_code == 200
        assert len(resp.json()["approvals"]) == 1

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        assert client.get("/approvals").status_code == 401


# ----------------------------------------------------------------
# GET /approvals/{id}
# ----------------------------------------------------------------


class TestGetApproval:
    def test_returns_approval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            f"{ROUTER}.get_pending_approval", AsyncMock(return_value=_sample_approval())
        )
        _app, client = _make_app(monkeypatch, approvals_router)
        resp = client.get(f"/approvals/{APPROVAL_ID}", headers=AUTH)

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(APPROVAL_ID)
        assert data["status"] == "pending"
        # El operador ve los inputs reales (su propio cliente) para poder revisar.
        assert data["inputs_raw"] == {"order_id": 1001}

    def test_returns_404_when_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(f"{ROUTER}.get_pending_approval", AsyncMock(return_value=None))
        _app, client = _make_app(monkeypatch, approvals_router)
        assert client.get(f"/approvals/{APPROVAL_ID}", headers=AUTH).status_code == 404


# ----------------------------------------------------------------
# POST /approvals/{id}/approve
# ----------------------------------------------------------------


class TestApproveAction:
    @pytest.mark.parametrize("status", ["executing", "approved", "rejected", "failed"])
    def test_approve_when_not_pending_is_409_and_runs_nothing(
        self, monkeypatch: pytest.MonkeyPatch, status: str
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        monkeypatch.setattr(
            f"{ROUTER}.get_pending_approval", AsyncMock(return_value=_sample_approval(status))
        )

        resp = _approve(client)

        assert resp.status_code == 409
        assert resp.json()["error"] == "approval_not_pending"
        w.claim.assert_not_awaited()
        assert FakeSkill.executions == 0

    def test_losing_the_claim_is_409_and_runs_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        w.claim.return_value = None

        resp = _approve(client)

        assert resp.status_code == 409
        assert FakeSkill.executions == 0
        w.insert_message.assert_not_awaited()

    def test_approve_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        _wire(monkeypatch)
        monkeypatch.setattr(f"{ROUTER}.get_pending_approval", AsyncMock(return_value=None))
        assert _approve(client).status_code == 404

    def test_success_claims_executes_with_the_approval_as_key_and_tells_the_customer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)

        resp = _approve(client)

        assert resp.status_code == 200
        data = resp.json()
        assert data["approval_status"] == "approved"
        assert data["execution_status"] == "success"
        assert w.claim.await_args.kwargs["reviewed_by"] == USER_ID
        assert FakeSkill.executions == 1
        assert FakeSkill.seen_ctx is not None
        assert FakeSkill.seen_ctx.idempotency_key == str(APPROVAL_ID)
        assert FakeSkill.seen_ctx.tenant_id == str(TENANT_ID)
        assert w.settle_cas.await_args.kwargs["new_status"] == "approved"
        # 'agent_human' exige autor: lo firma quien aprobó.
        assert w.insert_message.await_args.kwargs["author_user_id"] == USER_ID
        content = w.insert_message.await_args.kwargs["content"]
        assert content == "Hemos cancelado tu pedido."
        assert w.deliver.await_args.kwargs["content"] == content

    def test_skill_without_idempotency_gets_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        _wire(monkeypatch)
        monkeypatch.setattr(FakeSkill, "requires_idempotency", False)

        _approve(client)

        assert FakeSkill.seen_ctx is not None
        assert FakeSkill.seen_ctx.idempotency_key is None

    def test_approve_writes_skill_audit_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        app, client = _make_app(monkeypatch, approvals_router)
        _wire(monkeypatch)
        audit_logger = MagicMock()
        app.state.agent_deps = SimpleNamespace(audit_logger=audit_logger, anthropic=None)

        assert _approve(client).status_code == 200
        kwargs = audit_logger.log.call_args.kwargs
        assert kwargs["status"] == "success"
        assert kwargs["skill_slug"] == "shopify.cancel_order"
        assert kwargs["aop_slug"] == "cancelaciones"
        assert kwargs["idempotency_key"] == APPROVAL_ID
        assert kwargs["outputs"] == {"cancelled": True}


class TestExecutionErrors:
    """Tras un error la L3 nunca se repite: se lee Shopify (`reconcile`) y se cierra."""

    def test_error_before_the_mutation_was_sent_reopens_the_approval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        FakeSkill.outcome = MutationNotApplied("lectura previa: Client error '404 Not Found'")
        FakeSkill.found = None

        data = _approve(client).json()

        assert data["approval_status"] == "pending"
        assert data["execution_status"] == "failed"
        assert "404" in data["output"]["error"]
        assert w.settle_cas.await_args.kwargs["new_status"] == "pending"
        assert FakeSkill.executions == 1
        w.insert_message.assert_not_awaited()
        w.deliver.assert_not_awaited()
        w.hand_off.assert_not_awaited()

    def test_error_after_the_mutation_was_sent_never_reopens_the_approval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`orderCancel` es asíncrono y un reembolso puede seguir en curso: que Shopify
        aún no lo muestre no prueba que no se aplicó. No se sabe: al equipo."""
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        FakeSkill.outcome = RuntimeError("poll: Server error '503 Service Unavailable'")
        FakeSkill.found = None

        data = _approve(client).json()

        assert data["approval_status"] == "failed"
        assert data["execution_status"] == "unknown"
        assert w.settle_cas.await_args.kwargs["new_status"] == "failed"
        assert "503" in w.hand_off.await_args.kwargs["reason"]
        w.insert_message.assert_not_awaited()
        w.deliver.assert_not_awaited()

    def test_timeout_after_the_mutation_landed_closes_as_approved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        FakeSkill.outcome = TimeoutError("read timeout")
        FakeSkill.found = _Output()

        data = _approve(client).json()

        assert data["approval_status"] == "approved"
        assert data["execution_status"] == "success"
        assert FakeSkill.executions == 1
        assert w.insert_message.await_args.kwargs["content"] == "Hemos cancelado tu pedido."
        w.release_all.assert_awaited_once()

    def test_a_return_created_before_a_timeout_closes_as_approved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`returnCreate` llega a Shopify y la respuesta se pierde: `reconcile` encuentra la
        devolución por la marca del plan y se cierra como aplicada, sin crear otra."""
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        shopify = _return_in_flight(monkeypatch, created_before_failing=True)

        data = _approve(client).json()

        assert data["approval_status"] == "approved"
        assert data["execution_status"] == "success"
        assert data["output"]["return_id"] == 5001
        assert len(shopify.called("create_return")) == 1
        assert w.insert_message.await_args.kwargs["content"].startswith(
            "Hemos abierto la devolución"
        )
        w.release_all.assert_awaited_once()

    def test_a_return_timeout_with_nothing_in_shopify_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        _return_in_flight(monkeypatch, created_before_failing=False)

        data = _approve(client).json()

        assert data["approval_status"] == "failed"
        assert data["execution_status"] == "unknown"
        reason = w.hand_off.await_args.kwargs["reason"]
        assert reason.startswith("La devolución del pedido 1431 se aprobó, pero no se pudo")
        assert "No se abrió nada" not in reason
        w.insert_message.assert_not_awaited()

    def test_error_that_cannot_be_checked_fails_and_goes_to_the_team(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        FakeSkill.outcome = TimeoutError("read timeout")
        FakeSkill.found = ReconcileUnknown("shopify caído")

        data = _approve(client).json()

        assert data["approval_status"] == "failed"
        assert data["execution_status"] == "unknown"
        reason = w.hand_off.await_args.kwargs["reason"]
        assert reason.startswith(
            "La cancelación del pedido 1001 se aprobó, pero no se pudo comprobar en Shopify"
        )
        assert data["team_followup"] == reason
        assert w.push.await_args.kwargs["reason"] == reason
        w.insert_message.assert_not_awaited()
        w.finalize.assert_not_awaited()

    def test_refusal_tells_the_customer_and_hands_the_reason_to_the_team(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        FakeSkill.outcome = SkillRefusal(
            "order_shipped",
            customer_message="Tu pedido ya salió del almacén.",
            team_reason="El pedido 1001 ya salió: revisad con el almacén.",
        )
        FakeSkill.found = None

        data = _approve(client).json()

        assert data["approval_status"] == "failed"
        assert data["execution_status"] == "refused"
        assert data["team_followup"] == "El pedido 1001 ya salió: revisad con el almacén."
        assert w.settle_cas.await_args.kwargs["new_status"] == "failed"
        assert w.insert_message.await_args.kwargs["content"] == "Tu pedido ya salió del almacén."
        assert w.insert_message.await_args.kwargs["metadata"]["refusal_code"] == "order_shipped"
        assert w.deliver.await_args.kwargs["content"] == "Tu pedido ya salió del almacén."
        assert w.hand_off.await_args.kwargs["reason"] == data["team_followup"]
        w.finalize.assert_not_awaited()

    def test_refusal_of_a_skill_that_cannot_reconcile_is_still_a_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        _wire(monkeypatch)
        FakeSkill.outcome = SkillRefusal("x", customer_message="No es posible.", team_reason="r")

        assert _approve(client).json()["execution_status"] == "refused"

    def test_refusal_on_the_first_attempt_is_a_refusal_even_if_shopify_shows_the_change(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El pedido ya estaba cancelado antes de aprobar: lo canceló otro, no Auyan. Ni
        mensaje de éxito ni audit de éxito: texto fijo al cliente y caso al equipo."""
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        FakeSkill.outcome = SkillRefusal(
            "order_cancelled", customer_message="Ya estaba cancelado.", team_reason="r"
        )
        FakeSkill.found = _Output()

        data = _approve(client).json()

        assert data["approval_status"] == "failed"
        assert data["execution_status"] == "refused"
        assert w.insert_message.await_args.kwargs["content"] == "Ya estaba cancelado."
        assert w.hand_off.await_args.kwargs["reason"] == "r"

    def test_not_applied_on_the_first_attempt_ignores_what_shopify_shows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        _wire(monkeypatch)
        FakeSkill.outcome = MutationNotApplied("lectura previa: 404")
        FakeSkill.found = _Output()

        assert _approve(client).json()["approval_status"] == "pending"

    def test_refusal_of_an_order_our_earlier_attempt_already_changed_is_applied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Segundo claim de la aprobación: el guard ve el pedido ya cancelado y pudo
        cancelarlo el intento anterior. Shopify manda: consta aplicada."""
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        w.claim.return_value = _sample_approval("executing", execution_attempt=2)
        FakeSkill.outcome = SkillRefusal("order_cancelled", customer_message="m", team_reason="r")
        FakeSkill.found = _Output()

        assert _approve(client).json()["approval_status"] == "approved"

    def test_losing_the_settle_cas_writes_and_delivers_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        w.settle_cas.side_effect = None
        w.settle_cas.return_value = None

        resp = _approve(client)

        assert resp.status_code == 409
        assert resp.json()["error"] == "approval_settled_elsewhere"
        w.insert_message.assert_not_awaited()
        w.deliver.assert_not_awaited()


# ----------------------------------------------------------------
# POST /approvals/{id}/reject
# ----------------------------------------------------------------


class TestRejectAction:
    def test_reject_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        _wire(monkeypatch)
        monkeypatch.setattr(f"{ROUTER}.get_pending_approval", AsyncMock(return_value=None))
        assert _reject(client).status_code == 404

    @pytest.mark.parametrize("status", ["executing", "approved", "rejected"])
    def test_reject_when_not_pending_is_409(
        self, monkeypatch: pytest.MonkeyPatch, status: str
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        monkeypatch.setattr(
            f"{ROUTER}.get_pending_approval", AsyncMock(return_value=_sample_approval(status))
        )

        assert _reject(client).status_code == 409
        w.reject.assert_not_awaited()

    def test_losing_the_reject_cas_is_409_and_tells_nobody(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        w.reject.return_value = None

        assert _reject(client).status_code == 409
        w.insert_message.assert_not_awaited()
        w.deliver.assert_not_awaited()
        w.release_own.assert_not_awaited()

    def test_reject_records_releases_its_escalation_and_delivers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)

        resp = _reject(client, "fuera de plazo")

        assert resp.status_code == 200
        assert resp.json()["approval_status"] == "rejected"
        assert w.reject.await_args.kwargs["reviewed_by"] == USER_ID
        assert w.insert_message.await_args.kwargs["author_user_id"] == USER_ID
        assert w.deliver.await_args.kwargs["content"] == w.insert_message.await_args.kwargs[
            "content"
        ]
        # Solo se cierra la escalación del gate; la acción no se hizo.
        assert w.release_own.await_args.kwargs["approval_id"] == APPROVAL_ID
        w.release_all.assert_not_awaited()
        w.finalize.assert_not_awaited()

    def test_rejection_is_written_in_the_conversation_language(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        monkeypatch.setattr(
            f"{ROUTER}.conversation_text_languages", AsyncMock(return_value=("en", "es"))
        )

        assert _reject(client).status_code == 200
        content = w.insert_message.await_args.kwargs["content"]
        assert content.startswith("We've reviewed your request")
        assert content.endswith("No procede")


class TestSimulatedApproval:
    """#348: una aprobación nacida en el simulador no se ejecuta ni se resuelve."""

    @pytest.mark.parametrize("action", ["approve", "reject"])
    def test_refuses_approval_of_simulated_conversation(
        self, monkeypatch: pytest.MonkeyPatch, action: str
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        monkeypatch.setattr(
            f"{ROUTER}.is_simulation_conversation", AsyncMock(return_value=True)
        )

        resp = client.post(
            f"/approvals/{APPROVAL_ID}/{action}", json={"comment": "desde el panel"}, headers=AUTH
        )

        assert resp.status_code == 403
        assert resp.json()["error"] == "simulated_approval"
        assert FakeSkill.executions == 0
        w.claim.assert_not_awaited()
        w.reject.assert_not_awaited()
        w.insert_message.assert_not_awaited()


# ----------------------------------------------------------------
# Cierre de la escalación tras aprobar (E2E pedido #1428)
# ----------------------------------------------------------------


class TestCloseAfterApproval:
    def test_success_delivered_releases_escalation_and_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch, channel="zendesk", delivered=True)

        assert _approve(client).status_code == 200
        # Acción ejecutada → se cierran TODAS las escalaciones de la conversación
        # (tickets #29/#31 del E2E A4 quedaban 'pending' por un escalado previo).
        assert w.release_all.await_args.kwargs["conversation_id"] == CONVERSATION_ID
        assert w.finalize.await_args.kwargs["delivered"] is True

    def test_success_undelivered_does_not_resolve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch, channel="zendesk", delivered=False)

        _approve(client)

        assert w.finalize.await_args.kwargs["delivered"] is False

    def test_channel_without_helpdesk_counts_as_delivered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch, channel="chat", delivered=False)

        _approve(client)

        assert w.finalize.await_args.kwargs["delivered"] is True

    def test_manual_refund_hands_the_case_to_the_team(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancelación ejecutada con pasarela manual (#318): el cliente recibe la
        plantilla fija, la conversación queda escalada con el motivo para el equipo y
        no hay resolución autónoma."""
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        FakeSkill.outcome = {
            "order_id": 1001,
            "cancelled": True,
            "outcome": "refund_manual",
            "detail": None,
            "refund_mode": "manual",
            "refund_gateway": "Transferencia",
            "success": False,
        }

        resp = _approve(client)

        expected_reason = (
            "La cancelación del pedido 1001 se ejecutó en Shopify, pero el cobro es de una "
            "pasarela manual (Transferencia) o no consta en Shopify: Shopify no devuelve el "
            "dinero. Haced el reembolso a mano si el cliente pagó y confirmádselo."
        )
        assert resp.json()["team_followup"] == expected_reason
        assert w.hand_off.await_args.kwargs["reason"] == expected_reason
        assert w.push.await_args.kwargs["reason"] == expected_reason
        assert w.insert_message.await_args.kwargs["content"] == (
            "Hemos cancelado tu pedido. Si ya realizaste el pago, la tienda te devolverá el "
            "importe por el mismo medio con el que pagaste. Nuestro equipo ya está avisado y "
            "te escribirá en cuanto lo tenga resuelto."
        )
        w.release_all.assert_not_awaited()
        w.finalize.assert_not_awaited()

    def test_confirmed_outcome_resolves_as_before(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _app, client = _make_app(monkeypatch, approvals_router)
        w = _wire(monkeypatch)
        FakeSkill.outcome = {"order_id": 1001, "outcome": "confirmed", "success": True}

        assert _approve(client).json()["team_followup"] is None
        w.release_all.assert_awaited_once()
        w.finalize.assert_awaited_once()


def _return_in_flight(monkeypatch: pytest.MonkeyPatch, *, created_before_failing: bool) -> Any:
    """Una devolución aprobada de verdad (`StartReturn` con su plan) cuyo `returnCreate`
    acaba en timeout; `created_before_failing` dice si Shopify llegó a crearla."""
    import asyncio

    from apps.api.integrations.base import IntegrationContext
    from apps.api.skills.shopify.start_return import StartReturn
    from apps.api.tests.skills.test_return_skills import RAW, BrokenShopify, _ctx, _policy

    shopify = BrokenShopify(fail_on="create_return", created_before_failing=created_before_failing)
    prepared = asyncio.run(StartReturn().prepare(_ctx(shopify, _policy()), RAW))
    approval = _sample_approval(skill_slug="shopify.start_return", inputs_raw=prepared)
    executing = _sample_approval(
        "executing", skill_slug="shopify.start_return", inputs_raw=prepared, execution_attempt=1
    )
    monkeypatch.setattr(f"{ROUTER}.get_pending_approval", AsyncMock(return_value=approval))
    monkeypatch.setattr(f"{ROUTER}.claim_pending_approval", AsyncMock(return_value=executing))
    monkeypatch.setattr(f"{ROUTER}.SkillRegistry.get", lambda slug: StartReturn)
    monkeypatch.setattr(
        f"{SERVICE}.build_commerce_integration_ctx",
        AsyncMock(return_value=IntegrationContext(tenant_id=TENANT_ID, credentials={})),
    )
    monkeypatch.setattr("apps.api.skills.shopify.start_return.ShopifyAdapter", lambda: shopify)
    return shopify


class TestStaleExecutionRecovery:
    """Un proceso murió con la devolución en `executing`: pasado `STALE_EXECUTION` la
    recuperación lee Shopify por la marca del plan y nunca la vuelve a crear."""

    @staticmethod
    def _stale(monkeypatch: pytest.MonkeyPatch, *, in_shopify: bool) -> tuple[Wiring, Any, Any]:
        import asyncio

        from apps.api.services import approval_execution
        from apps.api.skills.shopify.start_return import StartReturn
        from apps.api.tests.skills.test_return_skills import RAW, FakeShopify, _ctx, _policy

        w = _wire(monkeypatch)
        shopify = _return_in_flight(monkeypatch, created_before_failing=False)
        prepared = asyncio.run(StartReturn().prepare(_ctx(FakeShopify(), _policy()), RAW))
        if in_shopify:
            # El proceso murió justo después de que Shopify creara la devolución.
            shopify = FakeShopify()
            inputs = StartReturn.input_schema.model_validate(prepared)
            asyncio.run(StartReturn().execute(_ctx(shopify), inputs))
            monkeypatch.setattr(
                "apps.api.skills.shopify.start_return.ShopifyAdapter", lambda: shopify
            )
        stale = _sample_approval(
            "executing",
            skill_slug="shopify.start_return",
            inputs_raw=prepared,
            execution_attempt=1,
        )
        listed = AsyncMock(return_value=[stale])

        @asynccontextmanager
        async def _bootstrap() -> AsyncIterator[AsyncMock]:
            yield AsyncMock()

        monkeypatch.setattr(f"{SERVICE}.bootstrap_connection", _bootstrap)
        monkeypatch.setattr(
            f"{SERVICE}.list_all_tenants", AsyncMock(return_value=[MagicMock(id=TENANT_ID)])
        )
        monkeypatch.setattr(f"{SERVICE}.list_stale_executing_approvals", listed)
        now = NOW + approval_execution.STALE_EXECUTION
        recovered = asyncio.run(approval_execution.recover_stale_executions(now=now))
        assert recovered == 1
        assert listed.await_args.kwargs["started_before"] == NOW
        return w, shopify, stale

    def test_a_return_that_landed_closes_as_approved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w, shopify, _ = self._stale(monkeypatch, in_shopify=True)

        assert w.settle_cas.await_args.kwargs["new_status"] == "approved"
        assert len(shopify.called("create_return")) == 1
        assert w.insert_message.await_args.kwargs["content"].startswith(
            "Hemos abierto la devolución"
        )

    def test_a_return_that_never_landed_reopens_without_creating_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        w, shopify, _ = self._stale(monkeypatch, in_shopify=False)

        assert w.settle_cas.await_args.kwargs["new_status"] == "pending"
        assert shopify.called("create_return") == []
        w.insert_message.assert_not_awaited()


def test_every_l3_skill_declares_idempotency() -> None:
    """Una L3 sin `requires_idempotency` no recibe clave ni sabe reconciliar (#376)."""
    import importlib
    import inspect
    import pkgutil

    import apps.api.skills.shopify as shopify_skills

    l3 = [
        cls
        for info in pkgutil.iter_modules(shopify_skills.__path__)
        for _, cls in inspect.getmembers(
            importlib.import_module(f"{shopify_skills.__name__}.{info.name}"), inspect.isclass
        )
        if issubclass(cls, Skill)
        and hasattr(cls, "slug")  # sin slug es una base común (p. ej. _ReturnSkill)
        and getattr(cls, "tier", None) == "L3"
    ]
    assert {s.slug for s in l3} >= {"shopify.cancel_order", "shopify.refund_partial"}
    assert [s.slug for s in l3 if not s.requires_idempotency] == []


# ----------------------------------------------------------------
# GET /tenants/me/tool-permissions
# ----------------------------------------------------------------


class TestListToolPermissions:
    def test_returns_permissions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        perm = TenantToolPermission(
            id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            tenant_id=TENANT_ID,
            skill_slug="shopify.get_order",
            is_enabled=True,
            human_approval_required=False,
            threshold_override=None,
        )
        monkeypatch.setattr(
            "apps.api.routers.tool_permissions.list_tool_permissions",
            AsyncMock(return_value=[perm]),
        )

        _app, client = _make_app(monkeypatch, tool_permissions_router)
        resp = client.get("/tenants/me/tool-permissions", headers=AUTH)

        assert resp.status_code == 200
        assert resp.json()["permissions"][0]["skill_slug"] == "shopify.get_order"

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _app, client = _make_app(monkeypatch, tool_permissions_router)
        assert client.get("/tenants/me/tool-permissions").status_code == 401


# ----------------------------------------------------------------
# PUT /tenants/me/tool-permissions/{slug}
# ----------------------------------------------------------------


class TestUpdateToolPermission:
    def test_skill_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _app, client = _make_app(monkeypatch, tool_permissions_router)
        resp = client.put(
            "/tenants/me/tool-permissions/skill.no_existe",
            json={"is_enabled": True, "human_approval_required": False},
            headers=AUTH,
        )
        assert resp.status_code == 404
