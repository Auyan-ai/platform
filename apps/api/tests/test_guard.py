"""Tests del decorador `@guarded`."""

from __future__ import annotations

import pytest
from apps.api.agents.nodes._guard import guarded


class TestGuarded:
    @pytest.mark.asyncio
    async def test_happy_path_returns_node_output(self) -> None:
        @guarded(name="test_node")
        async def node(state):  # type: ignore[no-untyped-def]
            return {"result": "ok", "value": 42}

        out = await node({})
        assert out == {"result": "ok", "value": 42}

    @pytest.mark.asyncio
    async def test_captures_exception_into_error(self) -> None:
        @guarded(name="failing_node")
        async def node(state):  # type: ignore[no-untyped-def]
            raise ValueError("something broke")

        out = await node({})
        assert "error" in out
        assert "failing_node" in out["error"]
        assert "ValueError" in out["error"]
        assert "something broke" in out["error"]

    @pytest.mark.asyncio
    async def test_does_not_swallow_when_no_error_set_explicitly(self) -> None:
        """El nodo puede setear error explícitamente sin lanzar excepción."""

        @guarded(name="explicit_error_node")
        async def node(state):  # type: ignore[no-untyped-def]
            return {"error": "explicit_business_error"}

        out = await node({})
        assert out == {"error": "explicit_business_error"}

    @pytest.mark.asyncio
    async def test_preserves_node_name_in_error_message(self) -> None:
        """El nombre del nodo debe aparecer en el error para debugging."""

        @guarded(name="my_specific_node")
        async def node(state):  # type: ignore[no-untyped-def]
            raise RuntimeError("kaboom")

        out = await node({})
        assert "my_specific_node" in out["error"]
