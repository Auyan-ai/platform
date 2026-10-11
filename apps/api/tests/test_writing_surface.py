"""Resolutor de superficie de escritura (chat | whatsapp | email)."""

from __future__ import annotations

import pytest
from apps.api.services.writing_surface import resolve_surface, surface_for_source


def _history(*source_channels: str | None) -> list[dict]:
    return [
        {"role": "customer", "metadata": {"source_channel": s} if s is not None else {}}
        for s in source_channels
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Zendesk via.channel
        ("email", "email"),
        ("mail", "email"),
        ("web", "email"),
        ("web_form", "email"),
        ("api", "email"),
        ("help_center", "email"),
        ("chat", "chat"),
        ("native_messaging", "chat"),
        ("web_widget", "chat"),
        ("mobile_sdk", "chat"),
        ("whatsapp", "chat"),
        ("facebook", "chat"),
        # Gorgias message.channel
        ("contact_form", "email"),
        ("instagram-direct-message", "chat"),
        ("facebook-messenger", "chat"),
        ("sms", "chat"),
        # Chatwoot channel type
        ("Channel::Email", "email"),
        ("Channel::WebWidget", "chat"),
        ("Channel::Whatsapp", "chat"),
        ("Channel::Api", "email"),
        # Desconocido o vacío → email (registro más seguro)
        ("fax_machine", "email"),
        ("", "email"),
        (None, "email"),
    ],
)
def test_surface_for_source(raw: str | None, expected: str) -> None:
    assert surface_for_source(raw) == expected


def test_whatsapp_and_chat_channels_ignore_history() -> None:
    assert resolve_surface("whatsapp", _history("email")) == "whatsapp"
    assert resolve_surface("chat", _history("email")) == "chat"
    assert resolve_surface("widget", []) == "chat"


def test_email_channel_is_email() -> None:
    assert resolve_surface("email", []) == "email"


@pytest.mark.parametrize("provider", ["zendesk", "gorgias", "chatwoot"])
def test_helpdesk_uses_latest_customer_source(provider: str) -> None:
    assert resolve_surface(provider, _history("email", "chat")) == "chat"
    assert resolve_surface(provider, _history("chat", "email")) == "email"


def test_helpdesk_skips_messages_without_source_and_agent_rows() -> None:
    history = [
        {"role": "customer", "metadata": {"source_channel": "chat"}},
        {"role": "agent_ai", "metadata": {"source_channel": "email"}},
        {"role": "customer", "metadata": {}},
    ]
    assert resolve_surface("zendesk", history) == "chat"


def test_helpdesk_without_any_source_defaults_to_email() -> None:
    assert resolve_surface("zendesk", _history(None, None)) == "email"
    assert resolve_surface("gorgias", []) == "email"
    assert resolve_surface("chatwoot", None) == "email"


def test_other_messaging_channels_are_chat() -> None:
    assert resolve_surface("instagram", []) == "chat"
    assert resolve_surface("intercom", []) == "chat"
