"""Observabilidad combinada del agente.

LangSmith es el provider primario. Langfuse puede seguir activo como espejo
secundario para compatibilidad durante la transición.

Todo el texto libre que sale hacia estos SaaS (mensaje del cliente, respuesta,
motivo de escalado, outputs de nodos) pasa por `services.pii.mask_*`: emails y
teléfonos que escriba el cliente no llegan a terceros. La correlación con Supabase
va por IDs (tenant_id, conversation_id) en metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from apps.api.integrations.langfuse_client import LangfuseClient
from apps.api.integrations.langsmith_client import LangSmithClient, LangSmithTrace
from apps.api.services.pii import mask_free_text_pii, mask_pii_recursive


@dataclass(frozen=True)
class ObservabilityTrace:
    primary: LangSmithTrace | None
    mirror: Any | None


class ObservabilityClient:
    def __init__(self, *, primary: LangSmithClient, mirror: LangfuseClient | None = None) -> None:
        self._primary = primary
        self._mirror = mirror

    @property
    def is_enabled(self) -> bool:
        return self.primary_enabled or self.mirror_enabled

    @property
    def primary_enabled(self) -> bool:
        return bool(self._primary.is_enabled)

    @property
    def primary_project(self) -> str:
        return self._primary.project_name

    @property
    def mirror_enabled(self) -> bool:
        return bool(self._mirror and self._mirror.is_enabled)

    def start_conversation_trace(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        end_customer_id: str,
        channel: str,
        input_text: str,
    ) -> ObservabilityTrace:
        input_text = mask_free_text_pii(input_text)
        primary = self._primary.start_conversation_trace(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            end_customer_id=end_customer_id,
            channel=channel,
            input_text=input_text,
        )
        mirror = None
        if self._mirror is not None:
            mirror = self._mirror.start_conversation_trace(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                end_customer_id=end_customer_id,
                channel=channel,
                input_text=input_text,
            )
        return ObservabilityTrace(primary=primary, mirror=mirror)

    def finalize_trace(
        self,
        trace: ObservabilityTrace,
        *,
        decision: str | None,
        confidence: float | None,
        response_text: str | None,
        escalation_reason: str | None,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        model: str | None,
        error: str | None,
    ) -> None:
        response_text = mask_free_text_pii(response_text) if response_text else response_text
        if escalation_reason:
            escalation_reason = mask_free_text_pii(escalation_reason)
        self._primary.finalize_trace(
            trace.primary,
            decision=decision,
            confidence=confidence,
            response_text=response_text,
            escalation_reason=escalation_reason,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            model=model,
            error=error,
        )
        if self._mirror is not None:
            self._mirror.finalize_trace(
                trace.mirror,
                decision=decision,
                confidence=confidence,
                response_text=response_text,
                escalation_reason=escalation_reason,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                model=model,
                error=error,
            )

    def record_node_run(
        self,
        *,
        trace_run_id: str,
        trace_dotted_order: str,
        node_name: str,
        start_time: datetime,
        end_time: datetime,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        from uuid import UUID

        ls_trace = LangSmithTrace(run_id=UUID(trace_run_id), dotted_order=trace_dotted_order)
        self._primary.record_node_run(
            ls_trace,
            node_name=node_name,
            start_time=start_time,
            end_time=end_time,
            outputs=mask_pii_recursive(outputs) if outputs else outputs,
            error=error,
        )

    def trace_id(self, trace: ObservabilityTrace) -> str | None:
        primary_id = self._primary.trace_id(trace.primary)
        if primary_id is not None:
            return str(primary_id)
        if self._mirror is not None:
            mirror_id = self._mirror.trace_id(trace.mirror)
            return str(mirror_id) if mirror_id is not None else None
        return None

    async def flush(self) -> None:
        await self._primary.flush()
        if self._mirror is not None:
            await self._mirror.flush()
