"""Nodo `resolve_identity` (ADR 0013 §3): grants del remitente, sin LLM y solo con hashes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apps.api.agents.nodes.resolve_identity import make_resolve_identity_node
from apps.api.services.identity import IdentityContext

from tests.conftest import make_fake_tenant_scope
from tests.identity_support import identity_state

MODULE = "apps.api.agents.nodes.resolve_identity"


@pytest.fixture(autouse=True)
def _db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{MODULE}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{MODULE}.get_tenant_pii_salt", AsyncMock(return_value="salt-x"))


def _unresolved(**kwargs: object) -> dict:
    state = identity_state(**kwargs)  # type: ignore[arg-type]
    state.pop("identity")
    state.pop("claim_salt")
    return state


@pytest.mark.parametrize(
    ("email", "phone", "channel", "methods"),
    [
        ("ana@x.com", None, "zendesk", ["sender_email"]),
        (None, "+34600111222", "whatsapp", ["sender_phone"]),
        (None, None, "zendesk", []),
    ],
)
async def test_grants_come_from_the_message_evidence(
    fake_deps, email: str | None, phone: str | None, channel: str, methods: list[str]
) -> None:
    state = _unresolved(email=email, phone=phone, channel=channel)
    out = await make_resolve_identity_node(fake_deps)(state)  # type: ignore[arg-type]
    identity = IdentityContext.from_state(out["identity"])
    assert out["identity_summary"]["methods"] == methods
    assert identity.has_grant("verified") == bool(methods)
    assert out["claim_salt"] == "salt-x"


async def test_the_linked_profile_never_grants_anything(fake_deps) -> None:
    state = _unresolved()
    state["end_customer"] = {"email": "ana@x.com", "phone": "+34600111222"}
    out = await make_resolve_identity_node(fake_deps)(state)  # type: ignore[arg-type]
    assert out["identity_summary"] == {"level": None, "methods": []}
    assert "no verificada" in out["identity_note"]


async def test_state_and_summary_carry_hashes_only(fake_deps) -> None:
    out = await make_resolve_identity_node(fake_deps)(_unresolved(email="ana@x.com"))  # type: ignore[arg-type]
    public = {k: v for k, v in out.items() if k != "claim_salt"}
    assert "ana@x.com" not in str(public)


async def test_simulator_customer_writes_as_an_email_sender(fake_deps) -> None:
    state = _unresolved()
    state.update(simulation_mode=True, end_customer={"email": "sim@x.com"})
    out = await make_resolve_identity_node(fake_deps)(state)  # type: ignore[arg-type]
    assert out["identity_summary"]["methods"] == ["sender_email"]
