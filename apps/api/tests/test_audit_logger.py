"""Tests del AuditLogger — verifica fire-and-forget y manejo de errores."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from apps.api.services.audit import AuditLogger

TENANT_ID = "11111111-1111-1111-1111-111111111111"
CONV_ID = "22222222-2222-2222-2222-222222222222"

BASE_KWARGS: dict[str, Any] = dict(
    tenant_id=TENANT_ID,
    conversation_id=CONV_ID,
    aop_slug="consulta_envio",
    aop_version=1,
    skill_slug="shopify.list_my_orders",
    skill_tier="L1",
    inputs_raw={"email": "test@test.com"},
    status="success",
)


class TestAuditLoggerNoLoop:
    def test_log_sin_event_loop_no_lanza(self) -> None:
        """En contexto síncrono sin event loop, log() debe ser no-op."""
        logger = AuditLogger()
        logger.log(**BASE_KWARGS)  # no debe lanzar


class TestAuditLoggerAsync:
    @pytest.mark.asyncio
    async def test_log_crea_task(self) -> None:
        logger = AuditLogger()
        with patch.object(logger, "_write", new_callable=AsyncMock) as mock_write:
            logger.log(**BASE_KWARGS)
            await asyncio.sleep(0)  # cede para que la task corra
            mock_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_task_se_limpia_de_pending(self) -> None:
        logger = AuditLogger()
        with patch.object(logger, "_write", new_callable=AsyncMock):
            before = len(logger._pending_tasks)
            logger.log(**BASE_KWARGS)
            assert len(logger._pending_tasks) == before + 1
            # Esperar a que la task termine y el done_callback limpie _pending_tasks
            for _ in range(5):
                await asyncio.sleep(0)
            assert len(logger._pending_tasks) == before

    @pytest.mark.asyncio
    async def test_write_falla_silenciosamente(self) -> None:
        """Si _write lanza, no debe propagarse al caller."""
        logger = AuditLogger()
        with patch.object(
            logger, "_write", new_callable=AsyncMock, side_effect=Exception("db_down")
        ):
            logger.log(**BASE_KWARGS)
            # No debe lanzar
            await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_write_llama_insert_audit_log(self) -> None:
        logger = AuditLogger()
        with (
            patch("apps.api.services.audit.tenant_scope") as mock_scope,
            patch("apps.api.services.audit.get_tenant_pii_salt", return_value="testsalt") as _,
            patch(
                "apps.api.services.audit.insert_skill_audit_log", new_callable=AsyncMock
            ) as mock_insert,
        ):
            fake_conn = AsyncMock()
            mock_scope.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
            mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

            await logger._write(
                tenant_id=__import__("uuid").UUID(TENANT_ID),
                conversation_id=__import__("uuid").UUID(CONV_ID),
                aop_slug="consulta_envio",
                aop_version=1,
                skill_slug="shopify.list_my_orders",
                skill_tier="L1",
                inputs_raw={"email": "ana@test.com"},
                status="success",
                outputs={"orders": []},
                idempotency_key=None,
                confidence=None,
                supervisor_verdict=None,
                error_message=None,
                latency_ms=42,
                langfuse_trace_id=None,
            )

            mock_insert.assert_called_once()
            call_kwargs = mock_insert.call_args.kwargs
            # El email debe estar redactado
            assert "ana@test.com" not in str(call_kwargs["inputs_redacted"])
            assert call_kwargs["inputs_redacted"]["email"].startswith("<email:")
            # El hash debe estar presente
            assert len(call_kwargs["inputs_hash"]) == 64
            assert call_kwargs["status"] == "success"
            assert call_kwargs["latency_ms"] == 42
