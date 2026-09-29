"""Tests del webhook handler de Zendesk: idempotencia por comentario + guard anti-loop."""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.routers.webhooks_zendesk import (
    _is_from_requester,
    _placeholder_value,
    _zendesk_idempotency_key,
)


class TestPlaceholderValue:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("123", "123"),
            (123, "123"),
            ("  456 ", "456"),
            ("", None),
            (None, None),
            # Placeholder que Zendesk no resolvió → llega literal.
            ("{{ticket.latest_comment.id}}", None),
        ],
    )
    def test_normalizes(self, value: Any, expected: str | None) -> None:
        assert _placeholder_value(value) == expected


class TestIdempotencyKey:
    def test_key_is_per_comment_not_per_ticket(self) -> None:
        """Dos mensajes del mismo ticket no pueden compartir clave (bug: solo se
        procesaba el primer mensaje de cada ticket)."""
        first = _zendesk_idempotency_key({"ticket_id": "10", "comment_id": "111", "content": "a"})
        second = _zendesk_idempotency_key({"ticket_id": "10", "comment_id": "222", "content": "b"})
        assert first == "zendesk:10:111"
        assert second == "zendesk:10:222"

    def test_retry_of_same_comment_shares_key(self) -> None:
        payload = {"ticket_id": "10", "comment_id": "111", "content": "hola"}
        assert _zendesk_idempotency_key(payload) == _zendesk_idempotency_key(dict(payload))

    def test_fallback_without_comment_id_hashes_content(self) -> None:
        a = _zendesk_idempotency_key({"ticket_id": "10", "content": "¿dónde está mi pedido?"})
        b = _zendesk_idempotency_key({"ticket_id": "10", "content": "ya lo recibí, gracias"})
        retry = _zendesk_idempotency_key({"ticket_id": "10", "content": "¿dónde está mi pedido?"})
        assert a is not None and a.startswith("zendesk:10:c")
        assert a != b
        assert a == retry

    def test_unrendered_comment_placeholder_uses_fallback(self) -> None:
        key = _zendesk_idempotency_key(
            {"ticket_id": "10", "comment_id": "{{ticket.latest_comment.id}}", "content": "x"}
        )
        assert key is not None and key.startswith("zendesk:10:c")

    def test_without_ticket_id_returns_none(self) -> None:
        assert _zendesk_idempotency_key({"comment_id": "111", "content": "x"}) is None


class TestIsFromRequester:
    def test_requester_comment_is_processed(self) -> None:
        assert _is_from_requester({"author_id": "7", "requester_id": "7"}) is True

    def test_agent_comment_is_ignored(self) -> None:
        """La respuesta pública del propio agente (u otro agente humano) re-dispara
        el trigger: no debe volver a entrar al grafo."""
        assert _is_from_requester({"author_id": "99", "requester_id": "7"}) is False

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"author_id": "", "requester_id": "7"},
            {"author_id": "{{ticket.latest_comment.author.id}}", "requester_id": "7"},
        ],
    )
    def test_missing_author_data_defers_to_trigger(self, payload: dict[str, Any]) -> None:
        """Sin datos de autor se confía en la condición del Trigger (current user
        = end user); el router lo loguea como warning."""
        assert _is_from_requester(payload) is None
