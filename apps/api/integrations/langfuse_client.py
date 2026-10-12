"""Wrapper de Langfuse.

Diseño: el cliente real es opcional. Si Langfuse falla al inicializar o falla en
runtime, log warning y seguimos. La observabilidad NO debe ser un punto de
falla del flujo del agente — un trace perdido es peor que un ticket sin
respuesta porque el observability provider se cayó.

El wrapper expone una API estable; si en el futuro cambiamos de Langfuse a
otro provider, sólo este archivo se modifica.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from langfuse import Langfuse

if TYPE_CHECKING:
    from apps.api.core.config import Settings

logger = logging.getLogger(__name__)


class LangfuseClient:
    """Adaptador thin sobre `langfuse.Langfuse`. Fallback silencioso si está roto."""

    def __init__(self, langfuse: Langfuse | None) -> None:
        self._lf = langfuse

    @property
    def is_enabled(self) -> bool:
        return self._lf is not None

    def start_conversation_trace(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        end_customer_id: str,
        channel: str,
        input_text: str,
    ) -> Any | None:
        if self._lf is None:
            return None
        try:
            return self._lf.trace(
                name="agent_conversation",
                user_id=end_customer_id,
                session_id=conversation_id,
                input=input_text,
                metadata={"tenant_id": tenant_id, "channel": channel},
                tags=[f"tenant:{tenant_id}", f"channel:{channel}"],
            )
        except Exception:
            logger.exception("langfuse_trace_start_failed")
            return None

    def finalize_trace(
        self,
        trace: Any,
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
    ) -> None:
        if trace is None:
            return
        try:
            trace.update(
                output={
                    "decision": decision,
                    "response_text": response_text,
                    "escalation_reason": escalation_reason,
                },
                metadata={
                    "confidence": confidence,
                    "tokens_in": tokens_in,
                    "tokens_cache_write": tokens_cache_write,
                    "tokens_cache_read": tokens_cache_read,
                    "tokens_out": tokens_out,
                    "cost_usd": cost_usd,
                    "model": model,
                    "had_error": bool(error),
                    "error": error,
                },
                level="ERROR" if error else "DEFAULT",
            )
        except Exception:
            logger.exception("langfuse_trace_finalize_failed")

    def trace_id(self, trace: Any) -> str | None:
        if trace is None:
            return None
        return getattr(trace, "id", None)

    async def flush(self) -> None:
        """Bloquea hasta que el batch pendiente se envíe. Llamar en shutdown."""
        if self._lf is None:
            return
        try:
            # Langfuse.flush() es síncrono; lo movemos a thread para no bloquear el loop.
            await asyncio.to_thread(self._lf.flush)
        except Exception:
            logger.exception("langfuse_flush_failed")


def build_langfuse_client(settings: Settings) -> LangfuseClient:
    """Construye el cliente o devuelve un wrapper deshabilitado si falla la init."""
    if settings.langfuse_public_key is None or settings.langfuse_secret_key is None:
        logger.info("langfuse_disabled_missing_credentials")
        return LangfuseClient(None)

    try:
        lf = Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            host=str(settings.langfuse_host),
        )
        return LangfuseClient(lf)
    except Exception:
        logger.exception("langfuse_init_failed — operando sin observabilidad")
        return LangfuseClient(None)
