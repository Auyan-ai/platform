"""Wrapper de LangSmith.

LangSmith es la fuente primaria de observabilidad para staging/evals. Igual que
con otros providers externos, si falla no debe tumbar el flujo del agente.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from langsmith import Client

if TYPE_CHECKING:
    from apps.api.core.config import Settings
    from apps.api.integrations.llm_ledger import LLMCall
    from apps.api.integrations.pricing import LLMUsage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LangSmithTrace:
    """Handle mínimo para actualizar un run raíz en LangSmith."""

    run_id: UUID
    dotted_order: str
    # Metadata de correlación con Supabase (tenant_id, conversation_id…). Se reenvía al
    # finalizar: `update_run` REEMPLAZA extra.metadata, y sin esto se perdía.
    metadata: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)
    # LangSmith rechaza actualizar un run anidado sin su `parent_run_id`.
    parent_run_id: UUID | None = None

    @property
    def root_id(self) -> UUID:
        """Id de la traza a la que pertenece el run. Es `run_id` en una raíz; en un run
        anidado (un turno de simulación bajo su `simulation_run`) es el de la raíz, que
        es el primer segmento del `dotted_order`."""
        return UUID(self.dotted_order.split(".")[0][-36:])


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

    @staticmethod
    def _dotted_order_segment(start_time: datetime, run_id: UUID) -> str:
        return start_time.strftime("%Y%m%dT%H%M%S%fZ") + str(run_id)

    @staticmethod
    def _usage_metadata(
        *,
        tokens_in: int,
        tokens_cache_write: int,
        tokens_cache_read: int,
        tokens_out: int,
        cost_usd: float,
    ) -> dict[str, Any]:
        usage: dict[str, Any] = {
            "input_tokens": max(tokens_in, 0),
            "output_tokens": max(tokens_out, 0),
            "total_tokens": max(tokens_in, 0) + max(tokens_out, 0),
            "input_token_details": {
                "cache_creation": max(tokens_cache_write, 0),
                "cache_read": max(tokens_cache_read, 0),
            },
        }
        if cost_usd > 0:
            usage["total_cost"] = cost_usd
        return usage

    def record_node_run(
        self,
        trace: LangSmithTrace,
        *,
        node_name: str,
        start_time: datetime,
        end_time: datetime,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Registra un child run por cada nodo del grafo (chain type)."""
        if self._client is None:
            return
        run_id = uuid4()
        dotted_order = f"{trace.dotted_order}.{self._dotted_order_segment(start_time, run_id)}"
        try:
            self._client.create_run(
                id=run_id,
                trace_id=trace.root_id,
                parent_run_id=trace.run_id,
                dotted_order=dotted_order,
                project_name=self._project_name,
                name=node_name,
                run_type="chain",
                inputs={"node": node_name},
                start_time=start_time,
                end_time=end_time,
                outputs=outputs or {},
                error=error,
                tags=["source:agent_service", "graph_node"],
            )
        except Exception:
            logger.exception("langsmith_node_run_failed node=%s", node_name)

    def record_standalone_run(
        self,
        *,
        name: str,
        run_type: str,
        metadata: dict[str, Any],
        start_time: datetime,
        end_time: datetime,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Run raíz fuera del grafo (p. ej. `transcribe_audio` en el worker), con la
        metadata de correlación con Supabase (tenant_id, conversation_id, message_id)."""
        if self._client is None:
            return
        run_id = uuid4()
        try:
            self._client.create_run(
                id=run_id,
                trace_id=run_id,
                dotted_order=self._dotted_order_segment(start_time, run_id),
                project_name=self._project_name,
                name=name,
                run_type=run_type,
                inputs={"name": name},
                start_time=start_time,
                end_time=end_time,
                outputs=outputs or {},
                error=error,
                extra={"metadata": metadata},
                tags=["source:inbound_worker", name],
            )
        except Exception:
            logger.exception("langsmith_standalone_run_failed name=%s", name)

    def _record_llm_calls(self, trace: LangSmithTrace, calls: Sequence[LLMCall]) -> None:
        """Corrida hija `llm` por llamada: `name` es el rol del `ModelRegistry`."""
        for call in calls:
            self.record_llm_run(
                trace,
                name=call.role,
                model=call.model,
                usage=call.usage,
                cost_usd=call.cost_usd,
                start_time=call.started_at,
                end_time=call.ended_at,
                call={"stop_reason": call.stop_reason, "latency_ms": call.latency_ms},
                source="agent_service",
                metadata={"role": call.role, "label": call.label},
            )

    def _record_model_usage_run(
        self,
        trace: LangSmithTrace,
        *,
        decision: str | None,
        confidence: float | None,
        response_text: str | None,
        tokens_in: int,
        tokens_cache_write: int,
        tokens_cache_read: int,
        tokens_out: int,
        cost_usd: float,
        model: str | None,
    ) -> None:
        if self._client is None:
            return
        if tokens_in <= 0 and tokens_out <= 0 and cost_usd <= 0:
            return

        run_id = uuid4()
        start_time = datetime.now(UTC)
        dotted_order = f"{trace.dotted_order}.{self._dotted_order_segment(start_time, run_id)}"
        usage_metadata = self._usage_metadata(
            tokens_in=tokens_in,
            tokens_cache_write=tokens_cache_write,
            tokens_cache_read=tokens_cache_read,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )

        self._client.create_run(
            id=run_id,
            trace_id=trace.root_id,
            parent_run_id=trace.run_id,
            dotted_order=dotted_order,
            project_name=self._project_name,
            name="agent_model_call",
            run_type="llm",
            inputs={"model": model, "aggregate_usage": True},
            start_time=start_time,
            tags=["source:agent_service", "usage:aggregate"],
            extra={
                "metadata": {
                    "model": model,
                    "decision": decision,
                    "confidence": confidence,
                    "usage_metadata": usage_metadata,
                    "aggregate_usage": True,
                }
            },
        )
        self._client.update_run(
            run_id,
            trace_id=trace.root_id,
            parent_run_id=trace.run_id,
            dotted_order=dotted_order,
            end_time=datetime.now(UTC),
            outputs={"response_text": response_text},
            extra={
                "metadata": {
                    "model": model,
                    "usage_metadata": usage_metadata,
                    "aggregate_usage": True,
                }
            },
        )

    def start_conversation_trace(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        end_customer_id: str,
        channel: str,
        input_text: str,
        parent: LangSmithTrace | None = None,
        extra_metadata: dict[str, Any] | None = None,
        extra_tags: list[str] | None = None,
    ) -> LangSmithTrace | None:
        """Raíz de un turno del agente. Con `parent` (la traza de una simulación) el turno
        cuelga de ella como run hijo; `extra_metadata` y `extra_tags` marcan su origen."""
        if self._client is None:
            return None

        run_id = uuid4()
        start_time = datetime.now(UTC)
        segment = self._dotted_order_segment(start_time, run_id)
        dotted_order = f"{parent.dotted_order}.{segment}" if parent else segment
        correlation: dict[str, Any] = {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "end_customer_id": end_customer_id,
            "channel": channel,
            **(extra_metadata or {}),
        }
        try:
            self._client.create_run(
                id=run_id,
                trace_id=parent.root_id if parent else run_id,
                parent_run_id=parent.run_id if parent else None,
                dotted_order=dotted_order,
                project_name=self._project_name,
                name="agent_conversation",
                run_type="chain",
                inputs={"message": input_text},
                start_time=start_time,
                tags=[
                    f"tenant:{tenant_id}",
                    f"channel:{channel}",
                    "source:agent_service",
                    *(extra_tags or []),
                ],
                extra={"metadata": correlation},
            )
            return LangSmithTrace(
                run_id=run_id,
                dotted_order=dotted_order,
                metadata=correlation,
                parent_run_id=parent.run_id if parent else None,
            )
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
        tokens_cache_write: int,
        tokens_cache_read: int,
        tokens_out: int,
        cost_usd: float,
        model: str | None,
        error: str | None,
        llm_calls: Sequence[LLMCall] | None = None,
    ) -> None:
        if self._client is None or trace is None:
            return

        try:
            if llm_calls:
                # Una corrida `llm` por llamada, con su rol: la suma de sus `total_cost`
                # es el `cost_usd` del turno. Sin llamadas (turno sin LLM) no hay corrida.
                self._record_llm_calls(trace, llm_calls)
            else:
                self._record_model_usage_run(
                    trace,
                    decision=decision,
                    confidence=confidence,
                    response_text=response_text,
                    tokens_in=tokens_in,
                    tokens_cache_write=tokens_cache_write,
                    tokens_cache_read=tokens_cache_read,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    model=model,
                )
        except Exception:
            logger.exception("langsmith_model_usage_run_failed")

        try:
            self._client.update_run(
                trace.run_id,
                trace_id=trace.root_id,
                parent_run_id=trace.parent_run_id,
                dotted_order=trace.dotted_order,
                end_time=datetime.now(UTC),
                outputs={
                    "decision": decision,
                    "response_text": response_text,
                    "escalation_reason": escalation_reason,
                },
                error=error,
                extra={
                    "metadata": {
                        **trace.metadata,
                        "confidence": confidence,
                        "tokens_in": tokens_in,
                        "tokens_cache_write": tokens_cache_write,
                        "tokens_cache_read": tokens_cache_read,
                        "tokens_out": tokens_out,
                        "cost_usd": cost_usd,
                        "model": model,
                        "had_error": bool(error),
                    }
                },
            )
        except Exception:
            logger.exception("langsmith_trace_finalize_failed")

    def start_simulation_trace(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        metadata: dict[str, Any],
        tags: list[str],
        input_text: str,
    ) -> LangSmithTrace | None:
        """Raíz de una corrida del simulador. Sus turnos, el cliente simulado y el judge
        cuelgan de ella; `metadata` (simulation, scenario_id, capabilities,
        simulation_run_id) es lo que permite filtrarla en LangSmith."""
        if self._client is None:
            return None

        run_id = uuid4()
        start_time = datetime.now(UTC)
        dotted_order = self._dotted_order_segment(start_time, run_id)
        correlation: dict[str, Any] = {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            **metadata,
        }
        try:
            self._client.create_run(
                id=run_id,
                trace_id=run_id,
                dotted_order=dotted_order,
                project_name=self._project_name,
                name="simulation_run",
                run_type="chain",
                inputs={"first_message": input_text},
                start_time=start_time,
                tags=[f"tenant:{tenant_id}", "source:simulator", *tags],
                extra={"metadata": correlation},
            )
            return LangSmithTrace(run_id=run_id, dotted_order=dotted_order, metadata=correlation)
        except Exception:
            logger.exception("langsmith_simulation_trace_start_failed")
            return None

    def finalize_simulation_trace(
        self,
        trace: LangSmithTrace | None,
        *,
        outputs: dict[str, Any],
        metadata: dict[str, Any],
        error: str | None = None,
    ) -> None:
        if self._client is None or trace is None:
            return
        try:
            self._client.update_run(
                trace.run_id,
                trace_id=trace.root_id,
                dotted_order=trace.dotted_order,
                end_time=datetime.now(UTC),
                outputs=outputs,
                error=error,
                extra={"metadata": {**trace.metadata, **metadata}},
            )
        except Exception:
            logger.exception("langsmith_simulation_trace_finalize_failed")

    def record_llm_run(
        self,
        trace: LangSmithTrace | None,
        *,
        name: str,
        model: str,
        usage: LLMUsage,
        cost_usd: float,
        start_time: datetime,
        end_time: datetime,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
        call: dict[str, Any] | None = None,
        source: str = "simulator",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Run hijo de tipo llm con su usage y coste (cliente simulado, judge, cada llamada
        del agente). `call`: thinking, esfuerzo y `stop_reason` de la llamada
        (`CallTrace.as_dict()`); `metadata`: rol y etiqueta de la llamada del agente."""
        if self._client is None or trace is None:
            return
        run_id = uuid4()
        dotted_order = f"{trace.dotted_order}.{self._dotted_order_segment(start_time, run_id)}"
        usage_metadata = self._usage_metadata(
            tokens_in=usage.prompt_tokens,
            tokens_cache_write=usage.cache_write_tokens,
            tokens_cache_read=usage.cache_read_tokens,
            tokens_out=usage.output_tokens,
            cost_usd=cost_usd,
        )
        try:
            self._client.create_run(
                id=run_id,
                trace_id=trace.root_id,
                parent_run_id=trace.run_id,
                dotted_order=dotted_order,
                project_name=self._project_name,
                name=name,
                run_type="llm",
                inputs={"model": model},
                start_time=start_time,
                end_time=end_time,
                outputs=outputs or {},
                error=error,
                tags=[f"source:{source}", name],
                extra={
                    "metadata": {
                        "model": model,
                        "usage_metadata": usage_metadata,
                        "llm_call": call,
                        **(metadata or {}),
                    }
                },
            )
        except Exception:
            logger.exception("langsmith_llm_run_failed name=%s", name)

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
            workspace_id=settings.langsmith_workspace_id,
            auto_batch_tracing=False,
            tracing_error_callback=lambda exc: logger.error(
                "langsmith_background_trace_failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            ),
        )
        return LangSmithClient(client, project_name=settings.langsmith_project)
    except Exception:
        logger.exception("langsmith_init_failed")
        return LangSmithClient(None, project_name=settings.langsmith_project)
