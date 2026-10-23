"""Registro de cada llamada al LLM, atribuida a su rol del `ModelRegistry` (#379).

`integrations/anthropic_client.py` anota cada respuesta en el ledger activo. Quien es
dueño del gasto (un turno del agente, una corrida del simulador, el mensaje tras una
L3) abre el ledger con `open_ledger()` y, al cerrar, lo persiste y lo traza. Los nodos
no suman tokens ni coste: un nodo nuevo no puede olvidarse de contarlos.

Una llamada sin ledger activo se loguea como `llm_call_unattributed`: es un hueco de
atribución a cerrar, no un caso normal.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from apps.api.integrations.pricing import LLMUsage

logger = logging.getLogger(__name__)

# Los roles del `ModelRegistry` (`core/config.py`). Un test exige que coincidan con sus
# campos: un rol nuevo en el registro no se puede llamar sin añadirlo aquí.
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


@dataclass(frozen=True)
class LLMCall:
    """Una respuesta de Anthropic: quién la pidió, con qué modelo y cuánto costó."""

    role: ModelRole
    label: str
    model: str
    usage: LLMUsage
    cost_usd: float
    started_at: datetime
    ended_at: datetime
    stop_reason: str | None

    @property
    def latency_ms(self) -> int:
        return int((self.ended_at - self.started_at).total_seconds() * 1000)


@dataclass
class LLMLedger:
    """Llamadas de un ámbito de gasto. Un ledger anidado también anota en su padre."""

    parent: LLMLedger | None = None
    _calls: list[LLMCall] = field(default_factory=list)

    @property
    def calls(self) -> tuple[LLMCall, ...]:
        return tuple(self._calls)

    def record(self, call: LLMCall) -> None:
        self._calls.append(call)
        if self.parent is not None:
            self.parent.record(call)

    @property
    def usage(self) -> LLMUsage:
        return sum((c.usage for c in self._calls), LLMUsage())

    @property
    def cost_usd(self) -> float:
        return sum(c.cost_usd for c in self._calls)

    def usage_by_role(self) -> dict[str, dict[str, Any]]:
        return usage_by_role(self._calls)

    def message_metadata(self) -> dict[str, Any]:
        """Totales y desglose por rol para `messages.metadata`."""
        usage = self.usage
        return {
            "prompt_tokens": usage.prompt_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "completion_tokens": usage.output_tokens,
            "cost_usd": self.cost_usd,
            "usage_by_role": self.usage_by_role(),
        }


def usage_by_role(calls: tuple[LLMCall, ...] | list[LLMCall]) -> dict[str, dict[str, Any]]:
    """`{rol: {model, input, cache_write, cache_read, output, cost_usd, calls}}`.

    `input` es el prompt completo (cacheado o no), igual que `prompt_tokens`."""
    out: dict[str, dict[str, Any]] = {}
    for call in calls:
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
            },
        )
        row["model"] = ",".join(sorted({*row["model"].split(","), call.model}))
        row["input"] += call.usage.prompt_tokens
        row["cache_write"] += call.usage.cache_write_tokens
        row["cache_read"] += call.usage.cache_read_tokens
        row["output"] += call.usage.output_tokens
        row["cost_usd"] += call.cost_usd
        row["calls"] += 1
    return out


_active: ContextVar[LLMLedger | None] = ContextVar("llm_ledger", default=None)


@contextmanager
def open_ledger() -> Iterator[LLMLedger]:
    """Abre un ámbito de gasto. Dentro, toda llamada al LLM queda anotada en él (y en el
    ledger que lo contenga). Las tareas asyncio creadas dentro heredan el ámbito."""
    ledger = LLMLedger(parent=_active.get())
    token = _active.set(ledger)
    try:
        yield ledger
    finally:
        _active.reset(token)


def active_ledger() -> LLMLedger | None:
    return _active.get()


def turn_usage_metadata() -> dict[str, Any]:
    """Totales y desglose por rol del ámbito activo, para `messages.metadata`. Lo leen
    `respond` y `escalate`, los nodos finales: para entonces el turno ya no llama al LLM."""
    return (active_ledger() or LLMLedger()).message_metadata()


def record_llm_call(call: LLMCall) -> None:
    ledger = _active.get()
    if ledger is None:
        logger.warning(
            "llm_call_unattributed role=%s label=%s model=%s cost_usd=%.6f",
            call.role,
            call.label,
            call.model,
            call.cost_usd,
            extra={"role": call.role, "model": call.model},
        )
        return
    ledger.record(call)
