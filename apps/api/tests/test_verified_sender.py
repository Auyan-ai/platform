"""Remitente verificado (ADR 0013, PR-1): solo el origen del mensaje decide qué contacto cuenta."""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.agents.nodes.execute_skill import build_skill_context
from apps.api.services.identity import inbound_source_channel, sender_origin
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


_HISTORY: list[dict[str, Any]] = [
    {"id": "m1", "role": "customer", "metadata": {"source_channel": "email"}},
    {"id": "m2", "role": "agent_ai", "metadata": {"source_channel": "email"}},
    {"id": "m3", "role": "customer", "metadata": {"source_channel": "chat"}},
]


def test_inbound_source_is_the_one_of_the_turn_message() -> None:
    assert inbound_source_channel(_HISTORY, "m1") == "email"
    assert inbound_source_channel(_HISTORY, "m3") == "chat"


def test_inbound_source_without_id_is_the_last_customer_message() -> None:
    assert inbound_source_channel(_HISTORY, None) == "chat"


def test_inbound_source_of_an_unknown_message_is_none() -> None:
    assert inbound_source_channel(_HISTORY, "otro") is None
    assert inbound_source_channel(None, None) is None


def _state(channel: str, source: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "tenant_id": str(TENANT_ID),
        "conversation_id": "c",
        "channel": channel,
        "inbound_message_id": "m1",
        "conversation_history": [
            {"id": "m1", "role": "customer", "metadata": {"source_channel": source}}
        ],
        "end_customer": {"email": "ana@example.com", "phone": "+34600111222"},
        **extra,
    }


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state("zendesk", "email"), ("ana@example.com", None)),
        (_state("zendesk", "chat"), (None, None)),
        (_state("gorgias", "api"), (None, None)),
        (_state("chatwoot", "Channel::WebWidget"), (None, None)),
        (_state("whatsapp", None), (None, "+34600111222")),
        (_state("chat", None), (None, None)),
        (_state("chat", None, simulation_mode=True), ("ana@example.com", None)),
    ],
    ids=[
        "zendesk_correo",
        "zendesk_chat",
        "gorgias_api",
        "chatwoot_widget",
        "whatsapp",
        "chat",
        "simulador",
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
