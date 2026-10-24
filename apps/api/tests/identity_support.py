"""Helpers de tests para el estado de identidad del grafo (ADR 0013)."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from apps.api.agents.nodes import execute_skill
from apps.api.integrations.base import IntegrationContext
from apps.api.services.identity import (
    EVIDENCE_KEY,
    IdentityEvidence,
    sender_identity,
)
from apps.api.skills.base import SkillContext
from apps.api.tests.conftest import TENANT_ID

SALT = "test-salt"
EXECUTE_SKILL_MODULE = "apps.api.agents.nodes.execute_skill"


def identity_state(
    *,
    email: str | None = None,
    phone: str | None = None,
    channel: str = "zendesk",
    **extra: Any,
) -> dict[str, Any]:
    """Estado de un turno cuyo mensaje trae esa evidencia de remitente y su identidad ya
    resuelta (lo que dejan el intake y `resolve_identity`). Sin email ni teléfono, el
    turno no tiene ningún grant."""
    evidence = {
        key: value for key, value in (("sender_email", email), ("sender_phone", phone)) if value
    }
    metadata = {EVIDENCE_KEY: evidence} if evidence else {}
    state: dict[str, Any] = {
        "tenant_id": str(TENANT_ID),
        "conversation_id": "22222222-2222-2222-2222-222222222222",
        "channel": channel,
        "inbound_message_id": "m1",
        "conversation_history": [{"id": "m1", "role": "customer", "metadata": metadata}],
        "identity": sender_identity(
            IdentityEvidence(email=email, phone=phone), salt=SALT
        ).to_state(),
        "claim_salt": SALT,
    }
    state.update(extra)
    return state


def patch_commerce(monkeypatch: pytest.MonkeyPatch, adapter: Any) -> None:
    """`build_skill_context` real, con el adapter de commerce de la prueba."""
    real = execute_skill.build_skill_context

    def _ctx(state: Any) -> SkillContext:
        return dataclasses.replace(
            real(state),
            integration_ctx=IntegrationContext(tenant_id=TENANT_ID, credentials={}, config={}),
            commerce_mock=adapter,
        )

    monkeypatch.setattr(f"{EXECUTE_SKILL_MODULE}.build_skill_context", _ctx)


def verified_context(
    *, email: str | None = None, phone: str | None = None, **overrides: Any
) -> SkillContext:
    """SkillContext de una skill ejecutada para un remitente verificado."""
    fields: dict[str, Any] = {
        "tenant_id": str(TENANT_ID),
        "conversation_id": "c",
        "integration_ctx": IntegrationContext(tenant_id=TENANT_ID, credentials={}, config={}),
        "customer_email": email,
        "customer_phone": phone,
        "identity": sender_identity(IdentityEvidence(email=email, phone=phone), salt=SALT),
        "claim_salt": SALT,
    }
    return SkillContext(**{**fields, **overrides})
