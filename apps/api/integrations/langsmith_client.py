"""Wrapper de LangSmith.

LangSmith es la fuente primaria de observabilidad para staging/evals. Igual que
con otros providers externos, si falla no debe tumbar el flujo del agente.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from langsmith import Client

if TYPE_CHECKING:
    from apps.api.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LangSmithTrace:
    """Handle mínimo para actualizar un run raíz en LangSmith."""

    run_id: UUID


class LangSmithClient:
    """Adaptador thin sobre `langsmith.Client`."""

    def __init__(self, client: Client | None, *, project_name: str) -> None:
        self._client = client
        self._project_name = project_name

    @property
    def is_enabled(self) -> bool:
        return self._client is not None

    @property
    def project_name(self) -> str:
        return self._project_name

    def start_conversation_trace(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        end_customer_id: str,
        channel: str,
        input_text: str,
    ) -> LangSmithTrace | None:
        if self._client is None:
            return None

        run_id = uuid4()
        try:
            self._client.create_run(
                id=run_id,
                project_name=self._project_name,
                name="agent_conversation",
                run_type="chain",
                inputs={"message": input_text},
                start_time=datetime.now(UTC),
                tags=[f"tenant:{tenant_id}", f"channel:{channel}", "source:agent_service"],
                extra={
                    "metadata": {
                        "tenant_id": tenant_id,
                        "conversation_id": conversation_id,
                        "end_customer_id": end_customer_id,
                        "channel": channel,
                    }
                },
            )
            return LangSmithTrace(run_id=run_id)
        except Exception:
            logger.exception("langsmith_trace_start_failed")
            return None

    def finalize_trace(
        self,
        trace: LangSmithTrace | None,
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
        if self._client is None or trace is None:
            return

        try:
            self._client.update_run(
                trace.run_id,
                end_time=datetime.now(UTC),
                outputs={
                    "decision": decision,
                    "response_text": response_text,
                    "escalation_reason": escalation_reason,
                },
                error=error,
                extra={
                    "metadata": {
                        "confidence": confidence,
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "cost_usd": cost_usd,
                        "model": model,
                        "had_error": bool(error),
                    }
                },
            )
        except Exception:
            logger.exception("langsmith_trace_finalize_failed")

    def trace_id(self, trace: LangSmithTrace | None) -> str | None:
        if trace is None:
            return None
        return str(trace.run_id)

    async def flush(self) -> None:
        if self._client is None:
            return
        try:
            await asyncio.to_thread(self._client.flush)
        except Exception:
            logger.exception("langsmith_flush_failed")


def build_langsmith_client(settings: Settings) -> LangSmithClient:
    """Construye LangSmith o devuelve cliente deshabilitado si no hay API key."""
    if settings.langsmith_api_key is None:
        if settings.app_env != "development":
            logger.warning("langsmith_api_key_missing env=%s", settings.app_env)
        return LangSmithClient(None, project_name=settings.langsmith_project)

    try:
        client = Client(
            api_key=settings.langsmith_api_key.get_secret_value(),
            api_url=str(settings.langsmith_endpoint),
            tracing_error_callback=lambda exc: logger.error(
                "langsmith_background_trace_failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            ),
        )
        return LangSmithClient(client, project_name=settings.langsmith_project)
    except Exception:
        logger.exception("langsmith_init_failed")
        return LangSmithClient(None, project_name=settings.langsmith_project)
