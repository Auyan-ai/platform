"""Origen del mensaje que Chatwoot manda en el webhook (superficie de escritura)."""

from __future__ import annotations

import pytest
from apps.api.routers.webhooks_chatwoot import _source_channel


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"conversation": {"channel": "Channel::Email"}}, "Channel::Email"),
        ({"inbox": {"channel_type": "Channel::WebWidget"}}, "Channel::WebWidget"),
        ({"conversation": {"meta": {"channel": "Channel::Whatsapp"}}}, "Channel::Whatsapp"),
        (
            {"conversation": {"channel": "Channel::Email"}, "inbox": {"channel_type": "x"}},
            "Channel::Email",
        ),
        ({}, None),
        ({"conversation": None, "inbox": None}, None),
    ],
)
def test_source_channel(payload: dict, expected: str | None) -> None:
    assert _source_channel(payload) == expected
