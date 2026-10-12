"""Tests para routers/approvals.py y routers/tool_permissions.py."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.db.models import PendingApproval, TenantToolPermission
from apps.api.routers.approvals import router as approvals_router
from apps.api.routers.tool_permissions import router as tool_permissions_router
from apps.api.tests.conftest import TENANT_ID
from fastapi import FastAPI
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret-for-unit-tests-32b!"
JWT_ALG = "HS256"
JWT_AUD = "authenticated"
USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CONVERSATION_ID = UUID("22222222-2222-2222-2222-222222222222")
APPROVAL_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
NOW = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)


class _SecretWrap:
    def get_secret_value(self) -> str:
        return JWT_SECRET


@dataclass
class FakeAuthSettings:
    auth_user_cache_maxsize: int = 1000
    auth_user_cache_ttl_seconds: int = 60
    supabase_jwt_algorithm: str = JWT_ALG
    supabase_jwt_audience: str = JWT_AUD
    reply_model: str = "claude-haiku-4-5-20251001"

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


def _sample_approval(status: str = "pending") -> PendingApproval:
    return PendingApproval(
        id=APPROVAL_ID,
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        skill_slug="shopify.cancel_order",
        skill_tier="L3",
        inputs_raw={"order_id": 1001},
        inputs_redacted={"order_id": 1001},
        aop_slug="cancelaciones",
        aop_version=1,
        langfuse_trace_id=None,
        status=status,
        created_at=NOW,
    )


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_user_cache()
    yield  # type: ignore[misc]
    reset_user_cache()


def _make_app(
    monkeypatch: pytest.MonkeyPatch,
    router_under_test=None,
) -> tuple[FastAPI, TestClient]:
    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord:
        return UserRecord(tenant_id=TENANT_ID, role="tenant_admin", email="a@b.com")

    monkeypatch.setattr("apps.api.core.security._lookup_user", _fake_lookup)

    @asynccontextmanager
    async def _fake_scope(*args: Any, **kwargs: Any) -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    monkeypatch.setattr("apps.api.routers.approvals.tenant_scope", _fake_scope)
    # Defaults del cierre post-aprobación; los tests que lo verifican los sobrescriben.
    monkeypatch.setattr(
        "apps.api.routers.approvals.release_approval_escalation", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "apps.api.routers.approvals.release_escalations_after_executed_action",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(
        "apps.api.routers.approvals.finalize_agent_resolution", AsyncMock(return_value=True)
    )
    monkeypatch.setattr("apps.api.routers.tool_permissions.tenant_scope", _fake_scope)
    # El router llama get_settings() directo (reply_model); en tests no hay env real.
    monkeypatch.setattr("apps.api.routers.approvals.get_settings", lambda: FakeAuthSettings())

    from apps.api.core.config import get_settings

    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()

    routers = [approvals_router, tool_permissions_router]
    if router_under_test:
        routers = [router_under_test]
    for r in routers:
        app.include_router(r)

    return app, TestClient(app, raise_server_exceptions=False)


# ----------------------------------------------------------------
# GET /approvals
# ----------------------------------------------------------------


class TestListApprovals:
    def test_returns_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.list_pending_approvals",
            AsyncMock(return_value=[_sample_approval()]),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.get("/approvals", headers={"Authorization": f"Bearer {_make_jwt()}"})

        assert resp.status_code == 200
        data = resp.json()
        assert "approvals" in data
        assert len(data["approvals"]) == 1

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.get("/approvals")
        assert resp.status_code == 401


# ----------------------------------------------------------------
# GET /approvals/{id}
# ----------------------------------------------------------------


class TestGetApproval:
    def test_returns_approval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval()),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.get(
            f"/approvals/{APPROVAL_ID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(APPROVAL_ID)
        assert data["status"] == "pending"
        # El operador ve los inputs reales (su propio cliente) para poder revisar.
        assert data["inputs_raw"] == {"order_id": 1001}

    def test_returns_404_when_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=None),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.get(
            f"/approvals/{APPROVAL_ID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 404


# ----------------------------------------------------------------
# POST /approvals/{id}/approve
# ----------------------------------------------------------------


class TestApproveAction:
    def test_approve_already_resolved_returns_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval(status="approved")),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/approve",
            json={"comment": "ok"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 403

    def test_approve_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=None),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/approve",
            json={},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 404

    def test_approve_executes_skill_and_returns_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Happy-path: arma el SkillContext con integration_ctx y ejecuta la skill.

        Regresión del 500: antes construía SkillContext con kwargs obsoletos
        (shopify_domain/shopify_token) → TypeError. Este test recorre la línea 140+.
        """
        from pydantic import BaseModel

        captured: dict[str, Any] = {}

        class _FakeInput(BaseModel):
            order_id: int

        class _FakeOutput(BaseModel):
            cancelled: bool = True

        class _FakeSkill:
            input_schema = _FakeInput

            async def execute(self, ctx: Any, inputs: Any) -> _FakeOutput:
                captured["ctx"] = ctx
                return _FakeOutput()

        class _FakeMsg:
            id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")

        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval()),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_tenant_configuration",
            AsyncMock(return_value=None),
        )
        # No hace falta Shopify real: el helper devuelve None y la fake skill lo ignora.
        monkeypatch.setattr(
            "apps.api.routers.approvals.build_commerce_integration_ctx",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.SkillRegistry.get",
            lambda slug: _FakeSkill,
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.resolve_pending_approval", AsyncMock(return_value=None)
        )
        insert_message_mock = AsyncMock(return_value=_FakeMsg())
        monkeypatch.setattr("apps.api.routers.approvals.insert_message", insert_message_mock)
        monkeypatch.setattr(
            "apps.api.routers.approvals.update_conversation_last_message",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_conversation", AsyncMock(return_value=MagicMock())
        )
        deliver_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("apps.api.routers.approvals.deliver_message_to_helpdesk", deliver_mock)

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/approve",
            json={"comment": "ok"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_status"] == "success"
        # El SkillContext se construyó bien (integration_ctx, no kwargs obsoletos).
        assert captured["ctx"].integration_ctx is None
        assert captured["ctx"].tenant_id == str(TENANT_ID)
        # El mensaje 'agent_human' lleva autor (constraint messages_human_has_author).
        assert insert_message_mock.await_args.kwargs["role"] == "agent_human"
        assert insert_message_mock.await_args.kwargs["author_user_id"] == USER_ID
        # Bug D: mensaje al cliente limpio (plantilla, sin agent_deps → sin LLM),
        # nunca el slug interno ni el dict crudo del output.
        content = insert_message_mock.await_args.kwargs["content"]
        assert content == "Hemos cancelado tu pedido."
        assert "shopify." not in content and "order_id" not in content
        # Bug E: el resultado se entrega al helpdesk del cliente.
        assert deliver_mock.await_args.kwargs["content"] == content

    def test_approve_writes_skill_audit_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Observabilidad: aprobar y ejecutar una skill L3 deja fila en skill_audit_log
        (status real + latencia + outputs), no solo el gate como rejected_by_permissions."""
        from types import SimpleNamespace

        from pydantic import BaseModel

        class _FakeInput(BaseModel):
            order_id: int

        class _FakeOutput(BaseModel):
            cancelled: bool = True

        class _FakeSkill:
            input_schema = _FakeInput

            async def execute(self, ctx: Any, inputs: Any) -> _FakeOutput:
                return _FakeOutput()

        class _FakeMsg:
            id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")

        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval()),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_tenant_configuration", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.build_commerce_integration_ctx",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr("apps.api.routers.approvals.SkillRegistry.get", lambda slug: _FakeSkill)
        monkeypatch.setattr(
            "apps.api.routers.approvals.resolve_pending_approval", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.insert_message", AsyncMock(return_value=_FakeMsg())
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.update_conversation_last_message",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_conversation", AsyncMock(return_value=None)
        )

        app, client = _make_app(monkeypatch, approvals_router)
        audit_logger = MagicMock()
        app.state.agent_deps = SimpleNamespace(audit_logger=audit_logger, anthropic=None)

        resp = client.post(
            f"/approvals/{APPROVAL_ID}/approve",
            json={"comment": "ok"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        audit_logger.log.assert_called_once()
        kwargs = audit_logger.log.call_args.kwargs
        assert kwargs["status"] == "success"
        assert kwargs["skill_slug"] == "shopify.cancel_order"
        assert kwargs["skill_tier"] == "L3"
        assert kwargs["aop_slug"] == "cancelaciones"
        assert kwargs["latency_ms"] is not None
        assert kwargs["outputs"] == {"cancelled": True}

    def test_approve_skill_failure_leaves_pending_and_sends_no_reply(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Hallazgo 1: si la skill falla, no se resuelve ni se le confirma al cliente.

        La aprobación queda 'pending' (reintentable), no se inserta mensaje al
        cliente (no enmascarar el fallo) ni se entrega nada al helpdesk, y la
        respuesta reporta execution_status='failed' con el error.
        """
        from pydantic import BaseModel

        class _FakeInput(BaseModel):
            order_id: int

        class _FakeSkill:
            input_schema = _FakeInput

            async def execute(self, ctx: Any, inputs: Any) -> Any:
                raise RuntimeError("Client error '404 Not Found' for url ...")

        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval()),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_tenant_configuration",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.build_commerce_integration_ctx",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.SkillRegistry.get",
            lambda slug: _FakeSkill,
        )
        resolve_mock = AsyncMock(return_value=None)
        monkeypatch.setattr("apps.api.routers.approvals.resolve_pending_approval", resolve_mock)
        insert_message_mock = AsyncMock()
        monkeypatch.setattr("apps.api.routers.approvals.insert_message", insert_message_mock)
        deliver_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("apps.api.routers.approvals.deliver_message_to_helpdesk", deliver_mock)

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/approve",
            json={"comment": "ok"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_status"] == "failed"
        assert data["message_id"] is None
        assert "404" in data["output"]["error"]
        # No se resuelve (queda 'pending' para reintento), no se le confirma nada
        # al cliente ni se entrega al helpdesk.
        resolve_mock.assert_not_awaited()
        insert_message_mock.assert_not_awaited()
        deliver_mock.assert_not_awaited()


# ----------------------------------------------------------------
# POST /approvals/{id}/reject
# ----------------------------------------------------------------


class TestRejectAction:
    def test_reject_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=None),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/reject",
            json={"comment": "No procede"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 404

    def test_reject_already_resolved_returns_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval(status="rejected")),
        )

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/reject",
            json={"comment": "rechazado"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 403

    def test_reject_inserts_message_with_author(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """El mensaje 'agent_human' de rechazo lleva autor (constraint messages_human_has_author)."""

        class _FakeMsg:
            id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")

        monkeypatch.setattr(
            "apps.api.routers.approvals.get_pending_approval",
            AsyncMock(return_value=_sample_approval()),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.resolve_pending_approval", AsyncMock(return_value=None)
        )
        insert_message_mock = AsyncMock(return_value=_FakeMsg())
        monkeypatch.setattr("apps.api.routers.approvals.insert_message", insert_message_mock)
        monkeypatch.setattr(
            "apps.api.routers.approvals.update_conversation_last_message",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "apps.api.routers.approvals.get_conversation", AsyncMock(return_value=MagicMock())
        )
        deliver_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("apps.api.routers.approvals.deliver_message_to_helpdesk", deliver_mock)

        app, client = _make_app(monkeypatch, approvals_router)
        resp = client.post(
            f"/approvals/{APPROVAL_ID}/reject",
            json={"comment": "No procede"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        assert resp.json()["execution_status"] == "rejected"
        assert insert_message_mock.await_args.kwargs["author_user_id"] == USER_ID
        # Bug E: el rechazo se entrega al helpdesk del cliente.
        assert (
            deliver_mock.await_args.kwargs["content"]
            == insert_message_mock.await_args.kwargs["content"]
        )


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

        app, client = _make_app(monkeypatch, tool_permissions_router)
        resp = client.get(
            "/tenants/me/tool-permissions",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "permissions" in data
        assert data["permissions"][0]["skill_slug"] == "shopify.get_order"

    def test_unauthenticated_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app, client = _make_app(monkeypatch, tool_permissions_router)
        resp = client.get("/tenants/me/tool-permissions")
        assert resp.status_code == 401


# ----------------------------------------------------------------
# PUT /tenants/me/tool-permissions/{slug}
# ----------------------------------------------------------------


class TestUpdateToolPermission:
    def test_skill_not_found_returns_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app, client = _make_app(monkeypatch, tool_permissions_router)
        resp = client.put(
            "/tenants/me/tool-permissions/skill.no_existe",
            json={"is_enabled": True, "human_approval_required": False},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 404


# ----------------------------------------------------------------
# Cierre de la escalación tras aprobar / rechazar (E2E pedido #1428)
# ----------------------------------------------------------------


def _patch_success_path(
    monkeypatch: pytest.MonkeyPatch,
    *,
    channel: str,
    delivered: bool,
    output: dict[str, Any] | None = None,
) -> tuple[AsyncMock, AsyncMock]:
    from pydantic import BaseModel

    class _FakeInput(BaseModel):
        order_id: int

    class _FakeOutput(BaseModel):
        cancelled: bool = True

    class _FakeSkill:
        input_schema = _FakeInput

        async def execute(self, ctx: Any, inputs: Any) -> Any:
            if output is not None:
                return MagicMock(model_dump=lambda mode: output)
            return _FakeOutput()

    class _FakeMsg:
        id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")

    conversation = MagicMock()
    conversation.channel = channel
    for name, value in {
        "get_pending_approval": AsyncMock(return_value=_sample_approval()),
        "get_tenant_configuration": AsyncMock(return_value=None),
        "build_commerce_integration_ctx": AsyncMock(return_value=None),
        "resolve_pending_approval": AsyncMock(return_value=None),
        "insert_message": AsyncMock(return_value=_FakeMsg()),
        "update_conversation_last_message": AsyncMock(return_value=None),
        "get_conversation": AsyncMock(return_value=conversation),
        "deliver_message_to_helpdesk": AsyncMock(return_value=delivered),
    }.items():
        monkeypatch.setattr(f"apps.api.routers.approvals.{name}", value)
    monkeypatch.setattr("apps.api.routers.approvals.SkillRegistry.get", lambda slug: _FakeSkill)
    release = AsyncMock(return_value=1)
    finalize = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "apps.api.routers.approvals.release_escalations_after_executed_action", release
    )
    monkeypatch.setattr("apps.api.routers.approvals.finalize_agent_resolution", finalize)
    return release, finalize


class TestCloseAfterApproval:
    def _client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        # _make_app instala mocks por defecto: la app va primero, los parches después.
        _app, client = _make_app(monkeypatch, approvals_router)
        return client

    def _approve(self, client: TestClient) -> Any:
        return client.post(
            f"/approvals/{APPROVAL_ID}/approve",
            json={},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    def test_success_delivered_releases_escalation_and_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(monkeypatch)
        release, finalize = _patch_success_path(monkeypatch, channel="zendesk", delivered=True)

        resp = self._approve(client)

        assert resp.status_code == 200
        # Acción ejecutada → se cierran TODAS las escalaciones de la conversación
        # (tickets #29/#31 del E2E A4 quedaban 'pending' por un escalado previo).
        release.assert_awaited_once()
        assert release.await_args.kwargs["conversation_id"] == _sample_approval().conversation_id
        finalize.assert_awaited_once()
        assert finalize.await_args.kwargs["delivered"] is True

    def test_success_undelivered_does_not_resolve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Confirmación sin entregar al helpdesk → no se resuelve ni se cierra el ticket."""
        client = self._client(monkeypatch)
        _release, finalize = _patch_success_path(monkeypatch, channel="zendesk", delivered=False)

        self._approve(client)

        assert finalize.await_args.kwargs["delivered"] is False

    def test_channel_without_helpdesk_counts_as_delivered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(monkeypatch)
        _release, finalize = _patch_success_path(monkeypatch, channel="chat", delivered=False)

        self._approve(client)

        assert finalize.await_args.kwargs["delivered"] is True

    def test_manual_refund_hands_the_case_to_the_team(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancelación ejecutada con pasarela manual (#318): el cliente recibe la
        plantilla fija, la conversación queda escalada con el motivo para el equipo y
        no hay resolución autónoma."""
        client = self._client(monkeypatch)
        release, finalize = _patch_success_path(
            monkeypatch,
            channel="zendesk",
            delivered=True,
            output={
                "order_id": 1001,
                "cancelled": True,
                "outcome": "refund_manual",
                "detail": None,
                "refund_mode": "manual",
                "refund_gateway": "Transferencia",
                "success": False,
            },
        )
        hand_off = AsyncMock(return_value=UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"))
        push = AsyncMock(return_value=True)
        monkeypatch.setattr("apps.api.routers.approvals.hand_executed_action_to_team", hand_off)
        monkeypatch.setattr("apps.api.routers.approvals.push_escalation_to_helpdesk_safe", push)

        resp = self._approve(client)

        expected_reason = (
            "La cancelación del pedido 1001 se ejecutó en Shopify, pero el cobro es de una "
            "pasarela manual (Transferencia) o no consta en Shopify: Shopify no devuelve el "
            "dinero. Haced el reembolso a mano si el cliente pagó y confirmádselo."
        )
        assert resp.json()["team_followup"] == expected_reason
        assert hand_off.await_args.kwargs["reason"] == expected_reason
        assert push.await_args.kwargs["reason"] == expected_reason
        from apps.api.routers import approvals as approvals_module

        sent = approvals_module.insert_message.await_args.kwargs["content"]  # type: ignore[attr-defined]
        assert sent == (
            "Hemos cancelado tu pedido. Si ya realizaste el pago, la tienda te devolverá el "
            "importe por el mismo medio con el que pagaste. Nuestro equipo ya está avisado y "
            "te escribirá en cuanto lo tenga resuelto."
        )
        release.assert_not_awaited()
        finalize.assert_not_awaited()

    def test_confirmed_outcome_resolves_as_before(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._client(monkeypatch)
        release, finalize = _patch_success_path(
            monkeypatch,
            channel="zendesk",
            delivered=True,
            output={"order_id": 1001, "outcome": "confirmed", "success": True},
        )

        resp = self._approve(client)

        assert resp.json()["team_followup"] is None
        release.assert_awaited_once()
        finalize.assert_awaited_once()

    def test_execution_failure_keeps_escalation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._client(monkeypatch)
        release, finalize = _patch_success_path(monkeypatch, channel="zendesk", delivered=True)

        class _Boom:
            input_schema = MagicMock(model_validate=lambda raw: raw)

            async def execute(self, ctx: Any, inputs: Any) -> Any:
                raise RuntimeError("shopify 500")

        monkeypatch.setattr("apps.api.routers.approvals.SkillRegistry.get", lambda slug: _Boom)

        resp = self._approve(client)

        assert resp.json()["execution_status"] == "failed"
        release.assert_not_awaited()
        finalize.assert_not_awaited()

    def test_reject_releases_escalation_without_resolving(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(monkeypatch)
        release_all, finalize = _patch_success_path(monkeypatch, channel="zendesk", delivered=True)
        release_own = AsyncMock(return_value=True)
        monkeypatch.setattr("apps.api.routers.approvals.release_approval_escalation", release_own)

        resp = client.post(
            f"/approvals/{APPROVAL_ID}/reject",
            json={"comment": "fuera de plazo"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

        assert resp.status_code == 200
        # Rechazo: solo se cierra la escalación del gate; la acción no se hizo, así
        # que un escalado previo sigue abierto para el equipo.
        release_own.assert_awaited_once()
        assert release_own.await_args.kwargs["approval_id"] == APPROVAL_ID
        release_all.assert_not_awaited()
        finalize.assert_not_awaited()
