"""Tests del router de propuestas del slow agent."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import jwt
import pytest
from apps.api.core.errors import register_exception_handlers
from apps.api.core.security import UserRecord, reset_user_cache
from apps.api.db.models import AopWithContent, ImprovementProposal
from apps.api.routers.proposals import router as proposals_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret-for-unit-tests-32b!"
JWT_ALG = "HS256"
JWT_AUD = "authenticated"
USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT = UUID("11111111-1111-1111-1111-111111111111")
PROPOSAL_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()
AOP_ID = uuid.uuid4()
NOW = datetime(2026, 5, 19, 12, 0, 0)


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
    return jwt.encode(
        {"aud": JWT_AUD, "sub": str(USER_ID), "exp": now + timedelta(hours=1), "iat": now},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


def _admin_record() -> UserRecord:
    return UserRecord(tenant_id=TENANT, role="tenant_admin", email="admin@acme.io")


_PENDING_PROPOSAL = ImprovementProposal(
    id=PROPOSAL_ID,
    tenant_id=TENANT,
    run_id=RUN_ID,
    proposal_type="aop_edit",
    aop_slug="consulta_envio",
    diff_markdown="## Añadir instrucción\n- Ofrecer tracking antes de escalar.",
    rationale="El agente escaló cuando tenía suficiente info.",
    evidence_conversations=[uuid.uuid4()],
    judge_model_used="claude-sonnet-4-6",
    judge_confidence=0.85,
    requires_eval_pass=True,
    status="pending",
    created_at=NOW,
)

_FAKE_AOP = AopWithContent(
    id=AOP_ID,
    tenant_id=TENANT,
    slug="consulta_envio",
    workspace="production",
    current_version=2,
    is_active=True,
    yaml_frontmatter={"slug": "consulta_envio", "name": "Consulta de Envío"},
    body_markdown="## Procedimiento\nAyuda al cliente con su envío.",
    raw_source="---\nslug: consulta_envio\n---\n\n## Procedimiento\nAyuda al cliente.",
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_user_cache()
    yield  # type: ignore[misc]
    reset_user_cache()


def _make_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def _fake_lookup(user_id: UUID, settings: Any) -> UserRecord:
        return _admin_record()

    monkeypatch.setattr("apps.api.core.security._lookup_user", _fake_lookup)

    from apps.api.core.config import get_settings
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: FakeAuthSettings()
    app.include_router(proposals_router)
    return app


def _auth() -> dict:
    return {"Authorization": f"Bearer {_make_jwt()}"}


# ─── list proposals ───────────────────────────────────────────────────────────


def test_list_proposals_ok(monkeypatch):
    with patch("apps.api.routers.proposals.tenant_scope") as mock_scope, \
         patch("apps.api.routers.proposals.list_improvement_proposals",
               new_callable=AsyncMock) as mock_list:

        conn = AsyncMock()
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_list.return_value = [_PENDING_PROPOSAL]

        app = _make_app(monkeypatch)
        client = TestClient(app)
        resp = client.get("/proposals", headers=_auth())

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "pending"


def test_get_proposal_not_found(monkeypatch):
    with patch("apps.api.routers.proposals.tenant_scope") as mock_scope, \
         patch("apps.api.routers.proposals.get_improvement_proposal",
               new_callable=AsyncMock) as mock_get:

        conn = AsyncMock()
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_get.return_value = None

        app = _make_app(monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/proposals/{uuid.uuid4()}", headers=_auth())

    assert resp.status_code == 404


# ─── ProposalResponse.from_model ─────────────────────────────────────────────


def test_proposal_response_from_model():
    from apps.api.routers.proposals import ProposalResponse
    resp = ProposalResponse.from_model(_PENDING_PROPOSAL)
    assert resp.id == PROPOSAL_ID
    assert resp.status == "pending"
    assert resp.proposal_type == "aop_edit"
    assert resp.judge_confidence == 0.85
    assert resp.reviewed_at is None
    assert len(resp.evidence_conversations) == 1


def test_proposal_response_confidence_as_float():
    from apps.api.routers.proposals import ProposalResponse
    resp = ProposalResponse.from_model(_PENDING_PROPOSAL)
    assert isinstance(resp.judge_confidence, float)


# ─── approve / reject logic ───────────────────────────────────────────────────


def test_approve_proposal_non_pending_rejected(monkeypatch):
    """Aprobar una propuesta ya rechazada retorna 409."""
    rejected_proposal = ImprovementProposal(
        **{**_PENDING_PROPOSAL.model_dump(), "status": "rejected"}
    )
    with patch("apps.api.routers.proposals.tenant_scope") as mock_scope, \
         patch("apps.api.routers.proposals.get_improvement_proposal",
               new_callable=AsyncMock) as mock_get:

        conn = AsyncMock()
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_get.return_value = rejected_proposal

        app = _make_app(monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/proposals/{PROPOSAL_ID}/approve",
            headers=_auth(),
        )

    assert resp.status_code == 409


def test_reject_proposal_missing_proposal(monkeypatch):
    with patch("apps.api.routers.proposals.tenant_scope") as mock_scope, \
         patch("apps.api.routers.proposals.get_improvement_proposal",
               new_callable=AsyncMock) as mock_get:

        conn = AsyncMock()
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_get.return_value = None

        app = _make_app(monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/proposals/{uuid.uuid4()}/reject",
            headers=_auth(),
            json={"comment": "No aplica"},
        )

    assert resp.status_code == 404


# ─── metrics ──────────────────────────────────────────────────────────────────


def test_metrics_response_fields(monkeypatch):
    fake_metrics = {
        "total": 10, "pending": 3, "approved": 4, "rejected": 2, "applied": 1,
        "acceptance_rate": 0.5, "cost_usd_total": 1.23,
        "cost_per_accepted_proposal": 0.246,
        "sonnet_tokens_total": 50000, "opus_tokens_total": 5000,
    }
    with patch("apps.api.routers.proposals.tenant_scope") as mock_scope, \
         patch("apps.api.routers.proposals.get_proposals_metrics",
               new_callable=AsyncMock) as mock_metrics:

        conn = AsyncMock()
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_metrics.return_value = fake_metrics

        app = _make_app(monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/proposals/metrics", headers=_auth())

    assert resp.status_code == 200
    data = resp.json()
    assert data["pending"] == 3
    assert data["acceptance_rate"] == 0.5
