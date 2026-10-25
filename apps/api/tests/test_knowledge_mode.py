"""Tests de `services.knowledge_mode`: KB entera en el prompt o por RAG."""

from __future__ import annotations

import pytest
from apps.api.services.knowledge_mode import (
    KnowledgeContext,
    choose_knowledge_mode,
    estimate_tokens,
    kb_token_budget,
    max_chars_for_budget,
)


def test_choose_mode_boundaries() -> None:
    assert choose_knowledge_mode(0, 50_000) == "full_context"
    assert choose_knowledge_mode(50_000, 50_000) == "full_context"
    assert choose_knowledge_mode(50_001, 50_000) == "retrieval"


@pytest.mark.parametrize(
    ("chars", "tokens"),
    [(0, 0), (1, 1), (7, 2), (8, 3), (35, 10), (36, 11), (-5, 0)],
)
def test_estimate_tokens_is_ceil_chars_over_3_5(chars: int, tokens: int) -> None:
    assert estimate_tokens(chars) == tokens


@pytest.mark.parametrize("budget", [0, 1, 3, 10, 50_000])
def test_max_chars_is_the_exact_edge_of_the_budget(budget: int) -> None:
    edge = max_chars_for_budget(budget)
    assert estimate_tokens(edge) <= budget
    assert estimate_tokens(edge + 1) > budget


def test_budget_override_per_tenant_and_fallback() -> None:
    assert kb_token_budget({"kb_full_context_token_budget": 1000}, 50_000) == 1000
    assert kb_token_budget({}, 50_000) == 50_000
    assert kb_token_budget(None, 50_000) == 50_000
    assert kb_token_budget({"kb_full_context_token_budget": "mucho"}, 50_000) == 50_000
    assert kb_token_budget({"kb_full_context_token_budget": True}, 50_000) == 50_000
    assert kb_token_budget({"kb_full_context_token_budget": -1}, 50_000) == 50_000


def _row(title: str, content: str | None, chars: int | None = None) -> dict:
    return {
        "title": title,
        "source": f"https://x.es/{title}",
        "chars": len(content or "") if chars is None else chars,
        "content": content,
    }


def test_decide_small_kb_is_full_context_with_documents() -> None:
    ctx = KnowledgeContext.decide([_row("a", "x" * 70), _row("b", "y" * 7)], budget=100)
    assert (ctx.mode, ctx.total_tokens, ctx.doc_count) == ("full_context", 22, 2)
    assert [d.title for d in ctx.documents] == ["a", "b"]


def test_decide_large_kb_is_retrieval_without_documents() -> None:
    rows = [_row("a", None, chars=700), _row("b", None, chars=7)]
    ctx = KnowledgeContext.decide(rows, budget=100)
    assert (ctx.mode, ctx.total_tokens, ctx.doc_count) == ("retrieval", 202, 2)
    assert ctx.documents == ()


def test_state_roundtrip() -> None:
    ctx = KnowledgeContext.decide([_row("a", "hola")], budget=100)
    assert KnowledgeContext.from_state(ctx.to_state()) == ctx
    assert KnowledgeContext.from_state(None) is None
