from __future__ import annotations

import json
import re
from typing import Any

from apps.api.services.site_ingestion.models import (
    DiscardReason,
    Platform,
    SourceDoc,
    SourceKind,
    SourceName,
)
from apps.api.services.site_ingestion.sources.base import SourceContext, SourceSpec

TOOL_NAME = "search_shop_policies_and_faqs"

CX_QUESTIONS: tuple[str, ...] = (
    "What is the return policy and how many days do I have?",
    "Are returns free or do I pay for return shipping?",
    "Can I exchange an item for another size or product?",
    "How long does a refund take?",
    "How much does shipping cost and is there free shipping?",
    "How long does delivery take?",
    "Do you ship internationally? Which countries?",
    "How can I track my order?",
    "Can I cancel or modify my order?",
    "Which payment methods do you accept?",
    "How can I contact customer service? Email, phone, hours?",
    "Do you have physical stores?",
    "Is there a warranty for defective products?",
    "How do I choose my size?",
    "How should I care for the products?",
    "Do you sell gift cards or gift wrapping?",
    "Do you have discount codes or a loyalty program?",
    "What if my order arrives damaged or wrong?",
)

# Respuestas que Shopify genera solo, sin FAQ de la tienda: un texto fijo o la lista de
# códigos ISO de su configuración de envíos.
GENERIC_ANSWER_MARKERS: tuple[str, ...] = (
    "Self-serve returns in customer accounts aren't available",
    "The store ships to the following locations:",
    "No pickup locations available",
)


def is_generic_answer(answer: str) -> bool:
    return any(marker in answer for marker in GENERIC_ANSWER_MARKERS)


def faq_source_key(question: str) -> str:
    return "mcp:faq/" + re.sub(r"\s+", " ", question).strip().lower()


def _parse_items(body: dict[str, Any]) -> list[dict[str, Any]] | None:
    result = body.get("result") or {}
    if result.get("isError"):
        return None
    content = result.get("content") or []
    if not content:
        return []
    try:
        items = json.loads(content[0].get("text") or "[]")
    except (json.JSONDecodeError, AttributeError):
        return None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else None


async def collect(ctx: SourceContext) -> list[SourceDoc]:
    url = f"{ctx.origin}/api/mcp"
    docs: dict[str, SourceDoc] = {}
    for n, question in enumerate(CX_QUESTIONS, start=1):
        response = await ctx.session.post_json(
            url,
            {
                "jsonrpc": "2.0",
                "id": n,
                "method": "tools/call",
                "params": {"name": TOOL_NAME, "arguments": {"query": question}},
            },
        )
        if response is None:
            if ctx.session.abandoned:
                break
            continue
        if response.status_code != 200:
            ctx.session.abandon(f"http_{response.status_code}")
            break
        try:
            items = _parse_items(response.json())
        except ValueError:
            items = None
        if items is None:
            ctx.stats.errors += 1
            continue
        for item in items:
            store_question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if not store_question or not answer:
                continue
            if is_generic_answer(answer):
                ctx.stats.discard(DiscardReason.GENERIC_MCP_ANSWER)
                continue
            key = faq_source_key(store_question)
            if key in docs:
                continue
            docs[key] = SourceDoc.build(
                url=url,
                source_key=key,
                kind=SourceKind.FAQ_ANSWER,
                title=store_question,
                markdown=f"## {store_question}\n\n{answer}",
            )
    return list(docs.values())


SPEC = SourceSpec(
    name=SourceName.STOREFRONT_MCP,
    platforms=frozenset({Platform.SHOPIFY}),
    collect=collect,
)
