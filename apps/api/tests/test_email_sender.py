"""Tests del EmailSender: fire-and-forget, no-op sin adapter, escalation fallback.

El EmailSender sigue el mismo patrón que ReasoningTracker/AuditLogger:
fire-and-forget via asyncio.create_task, silencia errores del envío,
funciona como no-op si el adapter no está configurado.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.api.services.email_sender import EmailSender

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(send_email_result: dict | Exception | None = None) -> MagicMock:
    adapter = MagicMock()
    if isinstance(send_email_result, Exception):
        adapter.send_email = AsyncMock(side_effect=send_email_result)
    else:
        adapter.send_email = AsyncMock(return_value=send_email_result or {})
    return adapter


# ---------------------------------------------------------------------------
# No-op cuando adapter es None
# ---------------------------------------------------------------------------


class TestEmailSenderNoAdapter:
    def test_send_email_noop_when_no_adapter(self) -> None:
        sender = EmailSender(adapter=None)
        # No lanza excepción
        sender.send_email(to="a@b.com", subject="s", text_body="t")

    def test_send_escalation_fallback_noop_when_no_adapter(self) -> None:
        sender = EmailSender(adapter=None)
        sender.send_escalation_fallback(
            to_email="ops@cliente.com",
            tenant_name="Lunaria",
            conversation_id="conv-123",
            reason="Cliente muy enojado",
        )


# ---------------------------------------------------------------------------
# Fire-and-forget: crea tarea asyncio
# ---------------------------------------------------------------------------


class TestEmailSenderFireAndForget:
    @pytest.mark.asyncio
    async def test_send_email_creates_task(self) -> None:
        adapter = _make_adapter()
        sender = EmailSender(adapter=adapter)

        sender.send_email(to="x@y.com", subject="s", text_body="hello")

        # Deja que el event loop procese la tarea
        await asyncio.sleep(0)

        adapter.send_email.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_email_passes_correct_args(self) -> None:
        adapter = _make_adapter()
        sender = EmailSender(adapter=adapter)

        sender.send_email(
            to="user@example.com",
            subject="Asunto prueba",
            text_body="Texto",
            html_body="<p>HTML</p>",
            tag="test-tag",
        )
        await asyncio.sleep(0)

        adapter.send_email.assert_awaited_once_with(
            to="user@example.com",
            subject="Asunto prueba",
            text_body="Texto",
            html_body="<p>HTML</p>",
            tag="test-tag",
        )

    @pytest.mark.asyncio
    async def test_send_email_silences_adapter_error(self) -> None:
        adapter = _make_adapter(send_email_result=RuntimeError("Postmark down"))
        sender = EmailSender(adapter=adapter)

        # No lanza excepción al llamar (fire-and-forget)
        sender.send_email(to="x@y.com", subject="s", text_body="t")
        # La tarea falla internamente pero no propaga
        await asyncio.sleep(0)

    def test_send_email_noop_outside_event_loop(self) -> None:
        adapter = _make_adapter()
        sender = EmailSender(adapter=adapter)
        # Fuera de un event loop no lanza excepción
        sender.send_email(to="x@y.com", subject="s", text_body="t")
        adapter.send_email.assert_not_awaited()


class TestEmailSenderAwaitableSend:
    @pytest.mark.asyncio
    async def test_send_email_now_returns_adapter_response(self) -> None:
        adapter = _make_adapter({"MessageID": "pm-123"})
        sender = EmailSender(adapter=adapter)

        result = await sender.send_email_now(
            to="x@y.com",
            subject="Reporte",
            text_body="Texto",
            html_body="<p>Texto</p>",
            tag="weekly-report",
        )

        assert result["MessageID"] == "pm-123"
        adapter.send_email.assert_awaited_once_with(
            to="x@y.com",
            subject="Reporte",
            text_body="Texto",
            html_body="<p>Texto</p>",
            tag="weekly-report",
        )

    @pytest.mark.asyncio
    async def test_send_email_now_raises_without_adapter(self) -> None:
        sender = EmailSender(adapter=None)

        with pytest.raises(RuntimeError, match="email_adapter_not_configured"):
            await sender.send_email_now(to="x@y.com", subject="s", text_body="t")


# ---------------------------------------------------------------------------
# send_escalation_fallback
# ---------------------------------------------------------------------------


class TestSendEscalationFallback:
    @pytest.mark.asyncio
    async def test_sends_email_with_fallback_template(self) -> None:
        adapter = _make_adapter()
        sender = EmailSender(adapter=adapter)

        sender.send_escalation_fallback(
            to_email="ops@lunaria.com",
            tenant_name="Lunaria",
            conversation_id="conv-abc-123",
            reason="Cliente no identificado",
            customer_email="cliente@ejemplo.com",
            agent_summary="El cliente preguntó por devoluciones pero no se identificó.",
        )
        await asyncio.sleep(0)

        adapter.send_email.assert_awaited_once()
        call_kwargs = adapter.send_email.call_args.kwargs
        assert call_kwargs["to"] == "ops@lunaria.com"
        assert call_kwargs["tag"] == "escalation-fallback"
        assert "Lunaria" in call_kwargs["subject"]
        assert "conv-abc-123" in call_kwargs["text_body"]
        assert "Cliente no identificado" in call_kwargs["text_body"]

    @pytest.mark.asyncio
    async def test_fallback_without_optional_fields(self) -> None:
        adapter = _make_adapter()
        sender = EmailSender(adapter=adapter)

        sender.send_escalation_fallback(
            to_email="ops@test.com",
            tenant_name="TestShop",
            conversation_id="conv-xyz",
            reason="No sabe responder",
        )
        await asyncio.sleep(0)

        adapter.send_email.assert_awaited_once()
        call_kwargs = adapter.send_email.call_args.kwargs
        # Sin customer_email ni agent_summary, el text_body sigue siendo válido
        assert "conv-xyz" in call_kwargs["text_body"]

    @pytest.mark.asyncio
    async def test_fallback_includes_html_body(self) -> None:
        adapter = _make_adapter()
        sender = EmailSender(adapter=adapter)

        sender.send_escalation_fallback(
            to_email="ops@test.com",
            tenant_name="Tienda",
            conversation_id="conv-1",
            reason="Razón test",
        )
        await asyncio.sleep(0)

        call_kwargs = adapter.send_email.call_args.kwargs
        assert call_kwargs["html_body"] is not None
        assert "conv-1" in call_kwargs["html_body"]
