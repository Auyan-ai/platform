"""Remitente verificado (ADR 0013): solo el origen del mensaje decide qué contacto cuenta."""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.agents.nodes.execute_skill import build_skill_context
from apps.api.services.identity import (
    build_identity_evidence,
    inbound_identity_evidence,
    sender_origin,
)
from apps.api.simulator.runner import assign_mock_orders_to_customer
from apps.api.tests.conftest import TENANT_ID


@pytest.mark.parametrize(
    ("channel", "source", "expected"),
    [
        ("whatsapp", None, "phone"),
        ("email", None, "email"),
        ("zendesk", "email", "email"),
        ("zendesk", "web", "email"),
        ("gorgias", "email", "email"),
        ("gorgias", "contact_form", "email"),
        ("gorgias", "help-center", "email"),
        ("chatwoot", "Channel::Email", "email"),
        ("zendesk", "chat", None),
        ("zendesk", "native_messaging", None),
        ("zendesk", "api", None),
        ("zendesk", None, None),
        ("gorgias", "chat", None),
        ("gorgias", "api", None),
        ("chatwoot", "Channel::WebWidget", None),
        ("chatwoot", "Channel::Api", None),
        ("chat", None, None),
        ("widget", "email", None),
        ("instagram", None, None),
        (None, None, None),
    ],
)
def test_sender_origin(channel: str | None, source: str | None, expected: str | None) -> None:
    assert sender_origin(channel, source) == expected


@pytest.mark.parametrize(
    ("channel", "source", "email", "phone", "expected"),
    [
        ("zendesk", "email", "ana@x.com", None, {"sender_email": "ana@x.com"}),
        ("zendesk", "web", " ana@x.com ", None, {"sender_email": "ana@x.com"}),
        ("gorgias", "contact_form", "ana@x.com", None, {"sender_email": "ana@x.com"}),
        ("chatwoot", "Channel::Email", "ana@x.com", None, {"sender_email": "ana@x.com"}),
        ("email", None, "ana@x.com", None, {"sender_email": "ana@x.com"}),
        ("whatsapp", None, None, "+34 600 111 222", {"sender_phone": "+34600111222"}),
        ("whatsapp", None, "ana@x.com", "34600111222", {"sender_phone": "+34600111222"}),
        ("zendesk", "chat", "ana@x.com", None, None),
        ("zendesk", None, "ana@x.com", None, None),
        ("gorgias", "api", "ana@x.com", None, None),
        ("chatwoot", "Channel::WebWidget", "ana@x.com", None, None),
        ("chat", None, "ana@x.com", None, None),
        ("email", None, None, None, None),
        ("email", None, "  ", None, None),
        ("whatsapp", None, None, None, None),
        ("whatsapp", None, None, "123", None),
    ],
)
def test_intake_writes_evidence_only_for_what_the_origin_verifies(
    channel: str,
    source: str | None,
    email: str | None,
    phone: str | None,
    expected: dict[str, str] | None,
) -> None:
    assert build_identity_evidence(channel, source, email=email, phone=phone) == expected


def _message(message_id: str, role: str, evidence: dict[str, Any] | None) -> dict[str, Any]:
    metadata = {"identity_evidence": evidence} if evidence else {}
    return {"id": message_id, "role": role, "metadata": metadata}


_HISTORY: list[dict[str, Any]] = [
    _message("m1", "customer", {"sender_email": "ana@example.com"}),
    _message("m2", "agent_ai", {"sender_email": "agente@example.com"}),
    _message("m3", "customer", None),
]


def test_inbound_evidence_is_the_one_of_the_turn_message() -> None:
    assert inbound_identity_evidence(_HISTORY, "m1").email == "ana@example.com"
    assert inbound_identity_evidence(_HISTORY, "m3").email is None


def test_inbound_evidence_without_id_is_the_last_customer_message() -> None:
    assert inbound_identity_evidence(_HISTORY, None).email is None


def test_inbound_evidence_of_an_unknown_message_is_empty() -> None:
    assert inbound_identity_evidence(_HISTORY, "otro").email is None
    assert inbound_identity_evidence(None, None).phone is None


def test_malformed_evidence_is_ignored() -> None:
    history = [{"id": "m1", "role": "customer", "metadata": {"identity_evidence": "ana@x.com"}}]
    assert inbound_identity_evidence(history, "m1").email is None


def _state(channel: str, evidence: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
    return {
        "tenant_id": str(TENANT_ID),
        "conversation_id": "c",
        "channel": channel,
        "inbound_message_id": "m1",
        "conversation_history": [_message("m1", "customer", evidence)],
        # El perfil enlazado nunca da identidad (ADR 0013 §3).
        "end_customer": {"email": "ana@example.com", "phone": "+34600111222"},
        **extra,
    }


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state("zendesk", {"sender_email": "ana@example.com"}), ("ana@example.com", None)),
        (_state("zendesk", None), (None, None)),
        (_state("whatsapp", {"sender_phone": "+34600111222"}), (None, "+34600111222")),
        (_state("whatsapp", None), (None, None)),
        (_state("chat", None, simulation_mode=True), ("ana@example.com", None)),
        (
            _state("chat", None, simulation_mode=True, simulation_identity="chat"),
            (None, None),
        ),
    ],
    ids=[
        "zendesk_correo",
        "zendesk_sin_evidencia",
        "whatsapp",
        "whatsapp_solo_bsuid",
        "simulador",
        "simulador_chat",
    ],
)
def test_skill_context_only_carries_the_verified_contact(
    state: dict[str, Any], expected: tuple[str | None, str | None]
) -> None:
    ctx = build_skill_context(state)  # type: ignore[arg-type]
    assert (ctx.customer_email, ctx.customer_phone) == expected


def test_simulator_order_lists_belong_to_the_simulated_customer() -> None:
    fixtures = {
        "shopify": {
            "search_orders_by_email": [{"id": 1}, {"id": 2, "email": "otro@x.com"}],
        }
    }
    out = assign_mock_orders_to_customer(fixtures, "sim@x")
    assert out["shopify"]["search_orders_by_email"] == [
        {"id": 1, "email": "sim@x"},
        {"id": 2, "email": "otro@x.com"},
    ]
    assert fixtures["shopify"]["search_orders_by_email"][0] == {"id": 1}
