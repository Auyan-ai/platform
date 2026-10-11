"""Tests del webhook handler de Gorgias."""

from __future__ import annotations

import pytest
from apps.api.routers.webhooks_gorgias import _is_from_agent, source_channel


class TestIsFromAgent:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (True, True),
            (False, False),
            ("true", True),
            ("false", False),
            ("True", True),
            ("False", False),
            ("  TRUE  ", True),
            ("1", True),
            ("0", False),
            ("", False),
        ],
    )
    def test_coerces_bool_and_string(self, value: object, expected: bool) -> None:
        assert _is_from_agent(value) is expected


class TestSourceChannel:
    def test_message_channel_wins(self) -> None:
        assert source_channel({"channel": "chat"}, {"channel": "email"}) == "chat"

    def test_falls_back_to_ticket_channel(self) -> None:
        assert source_channel({}, {"channel": "email"}) == "email"

    def test_missing_is_none(self) -> None:
        assert source_channel({}, {}) is None
