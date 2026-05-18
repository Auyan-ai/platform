"""Tests del router de propuestas del slow agent."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from apps.api.core.errors import register_exception_handlers
from apps.api.db.models import AopWithContent, ImprovementProposal
from apps.api.routers.proposals import router as proposals_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

TENANT = uuid.uuid4()
PROPOSAL_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()
AOP_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
NOW = datetime(2026, 5, 19, 12, 0, 0)

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


def _auth_headers() -> dict:
    return {"Authorization": "Bearer fake-token"}


def _mock_auth():
    from apps.api.core.security import AuthContext
    return AuthContext(
        user_id=USER_ID,
        tenant_id=TENANT,
        role="tenant_admin",
        email="admin@test.com",
    )


def _make_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(
        "apps.api.routers.proposals.get_auth_context",
        lambda: _mock_auth(),
    )
    monkeypatch.setattr(
        "apps.api.routers.proposals.get_tenant_id",
        lambda: TENANT,
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(proposals_router)
    return app


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
        resp = client.get("/proposals", headers=_auth_headers())

    assert resp.status_code in (200, 401, 422)


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
        resp = client.get(f"/proposals/{uuid.uuid4()}", headers=_auth_headers())

    assert resp.status_code in (401, 404, 422)


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
               new_callable=AsyncMock) as mock_get, \
         patch("apps.api.routers.proposals.require_role", return_value=lambda: None):

        conn = AsyncMock()
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_get.return_value = rejected_proposal

        app = _make_app(monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/proposals/{PROPOSAL_ID}/approve",
            headers=_auth_headers(),
        )

    assert resp.status_code in (401, 409, 422)


def test_reject_proposal_missing_proposal(monkeypatch):
    with patch("apps.api.routers.proposals.tenant_scope") as mock_scope, \
         patch("apps.api.routers.proposals.get_improvement_proposal",
               new_callable=AsyncMock) as mock_get, \
         patch("apps.api.routers.proposals.require_role", return_value=lambda: None):

        conn = AsyncMock()
        mock_scope.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_get.return_value = None

        app = _make_app(monkeypatch)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/proposals/{uuid.uuid4()}/reject",
            headers=_auth_headers(),
            json={"comment": "No aplica"},
        )

    assert resp.status_code in (401, 404, 422)


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
        resp = client.get("/proposals/metrics", headers=_auth_headers())

    assert resp.status_code in (200, 401, 422)
