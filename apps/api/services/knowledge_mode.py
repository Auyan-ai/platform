"""Cómo llega la base de conocimiento al agente: entera en el prompt o por RAG.

Según la guía de Anthropic (Contextual Retrieval), una KB pequeña va entera en el
prompt con prompt caching en vez de recuperarse por fragmentos. Aquí se decide con una
función pura sobre el tamaño estimado; no se llama a ningún modelo.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

KnowledgeMode = Literal["full_context", "retrieval"]

# Por debajo de este tamaño la KB entra entera. Por debajo del tope de ~200k de Anthropic
# a propósito: una KB más corta protege la atención del modelo y el coste.
DEFAULT_KB_FULL_CONTEXT_TOKEN_BUDGET = 50_000

BUDGET_KEY = "kb_full_context_token_budget"


def estimate_tokens(chars: int) -> int:
    """Tokens estimados de `chars` caracteres, por exceso: ceil(chars / 3.5)."""
    return (max(chars, 0) * 2 + 6) // 7


def max_chars_for_budget(budget: int) -> int:
    """Mayor nº de caracteres cuyo estimado cabe en `budget` tokens."""
    return budget * 7 // 2


def choose_knowledge_mode(total_tokens: int, budget: int) -> KnowledgeMode:
    return "full_context" if total_tokens <= budget else "retrieval"


def kb_token_budget(config_extra: Mapping[str, Any] | None, default: int) -> int:
    """Presupuesto del tenant (`tenant_configurations.extra`) o el del sistema."""
    raw = (config_extra or {}).get(BUDGET_KEY)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return default
    return raw


@dataclass(frozen=True)
class KbDocument:
    title: str
    source: str | None
    content: str


@dataclass(frozen=True)
class KnowledgeContext:
    """Decisión del turno. `documents` va lleno solo en `full_context`."""

    mode: KnowledgeMode
    total_tokens: int
    doc_count: int
    documents: tuple[KbDocument, ...] = field(default=())

    @classmethod
    def decide(
        cls,
        rows: Iterable[Mapping[str, Any]],
        *,
        budget: int,
    ) -> KnowledgeContext:
        """Filas `{title, source, chars, content}` (en orden fijo). `content` llega None
        cuando la KB ya superaba el presupuesto y no hacía falta leerla."""
        rows = list(rows)
        total = estimate_tokens(sum(int(r["chars"]) for r in rows))
        mode = choose_knowledge_mode(total, budget)
        documents = (
            tuple(KbDocument(r["title"], r.get("source"), r["content"] or "") for r in rows)
            if mode == "full_context"
            else ()
        )
        return cls(mode=mode, total_tokens=total, doc_count=len(rows), documents=documents)

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "total_tokens": self.total_tokens,
            "doc_count": self.doc_count,
        }

    def to_state(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "documents": [
                {"title": d.title, "source": d.source, "content": d.content}
                for d in self.documents
            ],
        }

    @classmethod
    def from_state(cls, raw: Mapping[str, Any] | None) -> KnowledgeContext | None:
        if not raw:
            return None
        return cls(
            mode=raw["mode"],
            total_tokens=int(raw["total_tokens"]),
            doc_count=int(raw["doc_count"]),
            documents=tuple(
                KbDocument(d["title"], d.get("source"), d["content"])
                for d in raw.get("documents") or []
            ),
        )
