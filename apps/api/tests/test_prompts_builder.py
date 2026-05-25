"""Tests del builder de prompts."""

from __future__ import annotations

import pytest
from apps.api.agents.prompts.builder import (
    build_message_history,
    build_system_prompt,
    format_knowledge_chunks,
)


class TestFormatKnowledgeChunks:
    def test_empty_list_returns_empty_string(self) -> None:
        assert format_knowledge_chunks([]) == ""

    def test_single_chunk(self) -> None:
        out = format_knowledge_chunks(
            [
                {
                    "document_title": "FAQ Envíos",
                    "similarity": 0.84,
                    "content": "Envíos a Argentina: 3-5 días hábiles.",
                }
            ]
        )
        assert "FAQ Envíos" in out
        assert "0.84" in out
        assert "3-5 días" in out
        assert "Fragmento 1" in out

    def test_multiple_chunks_separated(self) -> None:
        out = format_knowledge_chunks(
            [
                {"document_title": "A", "similarity": 0.9, "content": "alpha"},
                {"document_title": "B", "similarity": 0.7, "content": "beta"},
            ]
        )
        assert "Fragmento 1" in out
        assert "Fragmento 2" in out
        assert out.index("alpha") < out.index("beta")


class TestBuildSystemPrompt:
    def test_no_chunks_returns_base(self) -> None:
        base = "Eres el agente de Acme."
        assert build_system_prompt(base, []) == base

    def test_with_chunks_adds_section(self) -> None:
        base = "Eres el agente de Acme."
        out = build_system_prompt(
            base, [{"document_title": "x", "similarity": 0.8, "content": "y"}]
        )
        assert out.startswith(base)
        assert "Contexto relevante de la base de conocimiento" in out
        assert "NO inventes" in out  # warning sobre no alucinar

    def test_current_date_injected(self) -> None:
        base = "Eres el agente de Acme."
        out = build_system_prompt(base, [], current_date="2026-05-25")
        assert "Fecha actual: 2026-05-25" in out
        assert base in out

    def test_current_date_none_no_injection(self) -> None:
        base = "Eres el agente de Acme."
        assert build_system_prompt(base, [], current_date=None) == base


class TestBuildMessageHistory:
    def test_maps_customer_to_user(self) -> None:
        msgs = build_message_history(
            [{"role": "customer", "content": "hola"}]
        )
        assert msgs == [{"role": "user", "content": "hola"}]

    def test_maps_agent_ai_to_assistant(self) -> None:
        msgs = build_message_history(
            [
                {"role": "customer", "content": "hola"},
                {"role": "agent_ai", "content": "buenas"},
                {"role": "customer", "content": "una pregunta"},
            ]
        )
        assert [m["role"] for m in msgs] == ["user", "assistant", "user"]

    def test_maps_agent_human_to_assistant(self) -> None:
        msgs = build_message_history(
            [
                {"role": "customer", "content": "hi"},
                {"role": "agent_human", "content": "hello"},
                {"role": "customer", "content": "?"},
            ]
        )
        assert msgs[1]["role"] == "assistant"

    def test_coalesces_consecutive_assistant(self) -> None:
        """agent_ai + agent_human consecutivos se mergean (Claude exige alternancia)."""
        msgs = build_message_history(
            [
                {"role": "customer", "content": "hola"},
                {"role": "agent_ai", "content": "bot dice esto"},
                {"role": "agent_human", "content": "humano agrega esto"},
                {"role": "customer", "content": "ok"},
            ]
        )
        assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
        assert "bot dice esto" in msgs[1]["content"]
        assert "humano agrega esto" in msgs[1]["content"]

    def test_skips_system_role(self) -> None:
        msgs = build_message_history(
            [
                {"role": "system", "content": "ignore me"},
                {"role": "customer", "content": "hola"},
            ]
        )
        assert msgs == [{"role": "user", "content": "hola"}]

    def test_skips_empty_content(self) -> None:
        msgs = build_message_history(
            [
                {"role": "agent_ai", "content": "   "},
                {"role": "customer", "content": "hola"},
            ]
        )
        assert msgs == [{"role": "user", "content": "hola"}]

    def test_fails_if_last_is_not_user(self) -> None:
        """Defensa: el caller debe persistir el inbound antes de invocar el grafo."""
        with pytest.raises(ValueError, match="terminar con un mensaje del cliente"):
            build_message_history(
                [
                    {"role": "customer", "content": "hola"},
                    {"role": "agent_ai", "content": "buenas"},
                ]
            )

    def test_fails_on_empty_history(self) -> None:
        with pytest.raises(ValueError):
            build_message_history([])
