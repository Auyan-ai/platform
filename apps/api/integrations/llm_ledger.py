"""Libro de llamadas al LLM de un turno: atribución de tokens y coste por rol (#378, #379).

`create_message` (`integrations/anthropic_client.py`) es el único sitio que habla con la API
de mensajes y registra cada respuesta aquí, con el rol del `ModelRegistry` que la pidió. Los
nodos no suman nada a mano: quien abre el turno (`open_ledger`) lee al final el total y el
desglose por rol, y por construcción no hay llamada que se quede fuera.

Fuera de un `open_ledger` (jueces, doctor, scripts) `record_call` no anota nada: esas
llamadas no son parte de un turno del agente y tienen su propia contabilidad.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, get_args

from apps.api.integrations.pricing import LLMUsage

logger = logging.getLogger(__name__)

# Un campo `str` de `ModelRegistry` por rol. Un test exige que coincidan.
ModelRole = Literal[
    "default_agent_model",
    "simple_turn_model",
    "intent_classifier_model",
    "supervisor_model_l1_l2",
    "supervisor_model_l3",
    "reply_model",
    "simulator_model",
    "judge_sonnet_model",
    "judge_opus_model",
    "slow_agent_model",
]
MODEL_ROLES: frozenset[str] = frozenset(get_args(ModelRole))


@dataclass(frozen=True)
class LLMCall:
    """Una respuesta de la API: quién la pidió, con qué modelo y cuánto costó."""

    role: str
    model: str
    label: str
    usage: LLMUsage
    cost_usd: float
    latency_ms: int
    started_at: datetime
    ended_at: datetime
    stop_reason: str | None = None


@dataclass
class LLMLedger:
    calls: list[LLMCall] = field(default_factory=list)

    def record(self, call: LLMCall) -> None:
        self.calls.append(call)

    @property
    def usage(self) -> LLMUsage:
        total = LLMUsage()
        for call in self.calls:
            total = total + call.usage
        return total

    @property
    def cost_usd(self) -> float:
        return sum(call.cost_usd for call in self.calls)

    def by_role(self) -> dict[str, dict[str, Any]]:
        """Rol -> modelo, tokens (entrada total, caché escrita y leída, salida), coste,
        llamadas y latencia. Un rol con dos modelos en el turno guarda el último."""
        out: dict[str, dict[str, Any]] = {}
        for call in self.calls:
            row = out.setdefault(
                call.role,
                {
                    "model": call.model,
                    "input": 0,
                    "cache_write": 0,
                    "cache_read": 0,
                    "output": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                    "latency_ms": 0,
                },
            )
            row["model"] = call.model
            row["input"] += call.usage.prompt_tokens
            row["cache_write"] += call.usage.cache_write_tokens
            row["cache_read"] += call.usage.cache_read_tokens
            row["output"] += call.usage.output_tokens
            row["cost_usd"] += call.cost_usd
            row["calls"] += 1
            row["latency_ms"] += call.latency_ms
        return out

    def telemetry(self) -> dict[str, Any]:
        """Totales del turno en los nombres que ya usan el state y `messages.metadata`."""
        usage = self.usage
        return {
            "tokens_in": usage.prompt_tokens,
            "tokens_cache_write": usage.cache_write_tokens,
            "tokens_cache_read": usage.cache_read_tokens,
            "tokens_out": usage.output_tokens,
            "cost_usd": self.cost_usd,
            "usage_by_role": self.by_role(),
        }

    def overlay(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """`state` con los totales del libro. Sin llamadas anotadas (turno sin LLM, o un
        grafo de prueba) se queda con lo que traiga el state."""
        if not self.calls:
            return dict(state)
        return {**state, **self.telemetry()}


_current: ContextVar[LLMLedger | None] = ContextVar("llm_ledger", default=None)


@contextlib.contextmanager
def open_ledger() -> Iterator[LLMLedger]:
    """Abre el libro del turno: las llamadas del bloque (y de las tareas que lance) se
    anotan en él."""
    ledger = LLMLedger()
    token = _current.set(ledger)
    try:
        yield ledger
    finally:
        _current.reset(token)


def record_call(call: LLMCall) -> None:
    if call.role not in MODEL_ROLES:
        logger.error(
            "llm_call_unknown_role role=%s label=%s model=%s: rol que no es del ModelRegistry",
            call.role,
            call.label,
            call.model,
            extra={"role": call.role, "model": call.model},
        )
    ledger = _current.get()
    if ledger is not None:
        ledger.record(call)


def turn_telemetry(state: Mapping[str, Any]) -> dict[str, Any]:
    """Totales del turno para escribirlos en `messages.metadata`: los del libro abierto y,
    sin libro (tests de un nodo suelto), los que haya en el state."""
    ledger = _current.get()
    if ledger is not None:
        return ledger.telemetry()
    return {
        "tokens_in": state.get("tokens_in", 0),
        "tokens_cache_write": state.get("tokens_cache_write", 0),
        "tokens_cache_read": state.get("tokens_cache_read", 0),
        "tokens_out": state.get("tokens_out", 0),
        "cost_usd": state.get("cost_usd", 0.0),
        "usage_by_role": {},
    }
