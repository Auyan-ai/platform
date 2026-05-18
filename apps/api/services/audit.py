"""AuditLogger — registra ejecuciones de skills en skill_audit_log (fire-and-forget).

Mismo patrón que ReasoningTracker: el caller no espera el resultado.
Si la inserción en DB falla, se loguea el error pero no afecta la respuesta al cliente.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar
from uuid import UUID

from apps.api.db.client import tenant_scope
from apps.api.db.queries import get_tenant_pii_salt, insert_skill_audit_log
from apps.api.services.pii import hash_inputs, redact_inputs

logger = logging.getLogger(__name__)


class AuditLogger:
    """Servicio stateless de escritura al audit log de skills.

    Instanciar una vez en startup y pasar vía AgentDependencies.
    """

    _pending_tasks: ClassVar[set[asyncio.Task[None]]] = set()

    def log(
        self,
        *,
        tenant_id: str | UUID,
        conversation_id: str | UUID,
        aop_slug: str,
        aop_version: int,
        skill_slug: str,
        skill_tier: str,
        inputs_raw: dict[str, Any],
        status: str,
        outputs: dict[str, Any] | None = None,
        idempotency_key: UUID | None = None,
        confidence: float | None = None,
        supervisor_verdict: str | None = None,
        error_message: str | None = None,
        latency_ms: int | None = None,
        langfuse_trace_id: str | None = None,
    ) -> None:
        """Encola escritura al audit log de forma fire-and-forget."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        task = loop.create_task(
            self._write(
                tenant_id=UUID(str(tenant_id)),
                conversation_id=UUID(str(conversation_id)),
                aop_slug=aop_slug,
                aop_version=aop_version,
                skill_slug=skill_slug,
                skill_tier=skill_tier,
                inputs_raw=inputs_raw,
                status=status,
                outputs=outputs,
                idempotency_key=idempotency_key,
                confidence=confidence,
                supervisor_verdict=supervisor_verdict,
                error_message=error_message,
                latency_ms=latency_ms,
                langfuse_trace_id=langfuse_trace_id,
            ),
            name=f"audit_log_{skill_slug}_{status}",
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _write(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        aop_slug: str,
        aop_version: int,
        skill_slug: str,
        skill_tier: str,
        inputs_raw: dict[str, Any],
        status: str,
        outputs: dict[str, Any] | None,
        idempotency_key: UUID | None,
        confidence: float | None,
        supervisor_verdict: str | None,
        error_message: str | None,
        latency_ms: int | None,
        langfuse_trace_id: str | None,
    ) -> None:
        try:
            async with tenant_scope(tenant_id) as conn:
                salt = await get_tenant_pii_salt(conn, tenant_id)
                inputs_redacted = redact_inputs(inputs_raw, salt)
                inputs_hash = hash_inputs(inputs_raw)
                await insert_skill_audit_log(
                    conn,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    aop_slug=aop_slug,
                    aop_version=aop_version,
                    skill_slug=skill_slug,
                    skill_tier=skill_tier,
                    inputs_redacted=inputs_redacted,
                    inputs_hash=inputs_hash,
                    status=status,
                    outputs_redacted=outputs,
                    idempotency_key=idempotency_key,
                    confidence=confidence,
                    supervisor_verdict=supervisor_verdict,
                    error_message=error_message,
                    latency_ms=latency_ms,
                    langfuse_trace_id=langfuse_trace_id,
                )
        except Exception:
            logger.exception(
                "audit_log_write_failed",
                extra={
                    "tenant_id": str(tenant_id),
                    "skill_slug": skill_slug,
                    "status": status,
                },
            )
