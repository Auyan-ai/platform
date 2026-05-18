"""Fixtures y helpers compartidos.

Los tests unitarios NO tocan DB ni LLMs reales. Estrategia:
- `tenant_scope` se mockea con un async context manager fake que yieldea una conn mock.
- Las queries se parchean por nombre con `monkeypatch.setattr("apps.api.agents.nodes.<x>.<query>", AsyncMock(...))`.
- Los modelos Pydantic se construyen con factories (`make_tenant_configuration`, etc.).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from apps.api.agents.dependencies import AgentDependencies
from apps.api.db.models import (
    Conversation,
    EndCustomer,
    Escalation,
    KnowledgeChunk,
    Message,
    Tenant,
    TenantConfiguration,
)

# ----------------------------------------------------------------
# Constantes de IDs
# ----------------------------------------------------------------
TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
CONVERSATION_ID = UUID("22222222-2222-2222-2222-222222222222")
CUSTOMER_ID = UUID("33333333-3333-3333-3333-333333333333")
INBOUND_MSG_ID = UUID("44444444-4444-4444-4444-444444444444")
OUTBOUND_MSG_ID = UUID("55555555-5555-5555-5555-555555555555")
ESCALATION_ID = UUID("66666666-6666-6666-6666-666666666666")
DOCUMENT_ID = UUID("77777777-7777-7777-7777-777777777777")


# ----------------------------------------------------------------
# Settings + dependencias
# ----------------------------------------------------------------


@dataclass
class FakeSettings:
    default_agent_model: str = "claude-sonnet-4-6"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    rag_top_k: int = 5
    rag_min_similarity: float = 0.6
    history_limit: int = 20
    llm_max_retries: int = 3
    llm_timeout_seconds: int = 30
    intent_min_confidence: float = 0.60
    intent_classifier_model: str = "claude-haiku-4-5-20251001"


@pytest.fixture
def fake_settings() -> FakeSettings:
    return FakeSettings()


@pytest.fixture
def fake_anthropic() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def fake_openai() -> AsyncMock:
    return AsyncMock()


class FakeReasoningTracker:
    """Tracker sin-op para tests — registra las llamadas pero no toca DB ni event loop."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class FakeAuditLogger:
    """AuditLogger sin-op para tests — registra las llamadas pero no toca DB ni event loop."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def log(self, **kwargs: Any) -> None:
        self.entries.append(kwargs)


@pytest.fixture
def fake_reasoning_tracker() -> FakeReasoningTracker:
    return FakeReasoningTracker()


@pytest.fixture
def fake_audit_logger() -> FakeAuditLogger:
    return FakeAuditLogger()


@pytest.fixture
def fake_deps(
    fake_anthropic: AsyncMock,
    fake_openai: AsyncMock,
    fake_settings: FakeSettings,
    fake_reasoning_tracker: FakeReasoningTracker,
    fake_audit_logger: FakeAuditLogger,
) -> AgentDependencies:
    return AgentDependencies(
        anthropic=fake_anthropic,  # type: ignore[arg-type]
        openai=fake_openai,  # type: ignore[arg-type]
        settings=fake_settings,  # type: ignore[arg-type]
        reasoning_tracker=fake_reasoning_tracker,  # type: ignore[arg-type]
        audit_logger=fake_audit_logger,  # type: ignore[arg-type]
    )


# ----------------------------------------------------------------
# Async context manager fake para tenant_scope
# ----------------------------------------------------------------


def make_fake_tenant_scope(conn: Any = None) -> Callable:
    """Devuelve un `tenant_scope`-like asynccontextmanager que yieldea `conn`."""
    if conn is None:
        conn = AsyncMock()

    @asynccontextmanager
    async def _scope(tenant_id: UUID | str) -> AsyncIterator[Any]:
        yield conn

    return _scope


def make_fake_bootstrap_connection(conn: Any = None) -> Callable:
    """Igual que `make_fake_tenant_scope` pero sin args (firma de `bootstrap_connection`)."""
    if conn is None:
        conn = AsyncMock()

    @asynccontextmanager
    async def _scope() -> AsyncIterator[Any]:
        yield conn

    return _scope


@pytest.fixture
def fake_conn() -> AsyncMock:
    """Mock de asyncpg.Connection. Para verificar que se llamen las queries con ella."""
    return AsyncMock()


# ----------------------------------------------------------------
# Anthropic response mock (reusado por test_reason_node)
# ----------------------------------------------------------------


class _ToolUseBlock:
    def __init__(
        self,
        input_payload: dict[str, Any],
        *,
        name: str = "respond_or_escalate",
        id: str = "toolu_test_001",
    ) -> None:
        self.type = "tool_use"
        self.input = input_payload
        self.name = name
        self.id = id


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeAnthropicResponse:
    def __init__(
        self,
        tool_input: dict[str, Any],
        *,
        tool_name: str = "respond_or_escalate",
        tool_id: str = "toolu_test_001",
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> None:
        self.content = [_ToolUseBlock(tool_input, name=tool_name, id=tool_id)]
        self.usage = _Usage(input_tokens, output_tokens)


@pytest.fixture
def make_anthropic_response() -> Callable:
    def _factory(
        tool_input: dict[str, Any],
        *,
        tool_name: str = "respond_or_escalate",
        tool_id: str = "toolu_test_001",
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> FakeAnthropicResponse:
        return FakeAnthropicResponse(
            tool_input,
            tool_name=tool_name,
            tool_id=tool_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    return _factory


# ----------------------------------------------------------------
# Factories de modelos Pydantic
# ----------------------------------------------------------------


def make_tenant(**overrides: Any) -> Tenant:
    base = {"id": TENANT_ID, "slug": "acme", "name": "Acme", "status": "active"}
    return Tenant(**{**base, **overrides})


def make_tenant_configuration(**overrides: Any) -> TenantConfiguration:
    base = {
        "tenant_id": TENANT_ID,
        "agent_model": "claude-sonnet-4-6",
        "escalation_threshold": 0.70,
        "active_channels": ["chat"],
        "branding": {},
        "extra": {},
    }
    return TenantConfiguration(**{**base, **overrides})


def make_end_customer(**overrides: Any) -> EndCustomer:
    base = {
        "id": CUSTOMER_ID,
        "tenant_id": TENANT_ID,
        "email": "juan@example.com",
        "full_name": "Juan Pérez",
        "metadata": {},
    }
    return EndCustomer(**{**base, **overrides})


def make_conversation(**overrides: Any) -> Conversation:
    base = {
        "id": CONVERSATION_ID,
        "tenant_id": TENANT_ID,
        "end_customer_id": CUSTOMER_ID,
        "channel": "chat",
        "status": "open",
    }
    return Conversation(**{**base, **overrides})


def make_message(**overrides: Any) -> Message:
    base = {
        "id": INBOUND_MSG_ID,
        "tenant_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "role": "customer",
        "direction": "inbound",
        "content": "hola",
        "attachments": [],
        "metadata": {},
        "created_at": datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC),
    }
    return Message(**{**base, **overrides})


def make_escalation(**overrides: Any) -> Escalation:
    base = {
        "id": ESCALATION_ID,
        "tenant_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "reason": "test",
        "status": "pending",
        "metadata": {},
    }
    return Escalation(**{**base, **overrides})


def make_knowledge_chunk(**overrides: Any) -> KnowledgeChunk:
    base = {
        "id": UUID("88888888-8888-8888-8888-888888888888"),
        "document_id": DOCUMENT_ID,
        "document_title": "FAQ",
        "content": "contenido del chunk",
        "similarity": 0.85,
    }
    return KnowledgeChunk(**{**base, **overrides})


# ----------------------------------------------------------------
# State inicial canónico
# ----------------------------------------------------------------


@pytest.fixture
def initial_state() -> dict:
    """State inicial que un router típico construiría antes de invocar el grafo."""
    return {
        "tenant_id": str(TENANT_ID),
        "conversation_id": str(CONVERSATION_ID),
        "inbound_message_id": str(INBOUND_MSG_ID),
        "inbound_message_content": "¿Cuánto tarda el envío a Argentina?",
        "channel": "chat",
        "end_customer_id": str(CUSTOMER_ID),
        "langfuse_trace_id": "trace-fake-001",
    }
