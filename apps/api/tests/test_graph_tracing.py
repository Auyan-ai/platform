"""Tests del tracing por-nodo a LangSmith (wrapper `_traced` en graph.py).

Foco de seguridad: el wrapper NUNCA debe emitir credenciales ni PII a LangSmith.
La allowlist `_NODE_OUTPUT_KEYS` es estricta — un nodo sin entrada emite `{}`.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.agents.graph import _NODE_OUTPUT_KEYS, _redact_dict, _traced


class _RecordingObservability:
    """Captura las llamadas a record_node_run para inspeccionar los outputs."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record_node_run(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _make_deps(obs: Any) -> Any:
    """Deps mínimo: el wrapper solo usa deps.observability."""

    class _Deps:
        observability = obs

    return _Deps()


_TRACE = {
    "_trace_run_id": "11111111-1111-1111-1111-111111111111",
    "_trace_dotted_order": "20260101T000000000000Z" + "1" * 32,
}


@pytest.mark.asyncio
async def test_unlisted_node_emits_no_outputs() -> None:
    """load_tenant_context no está en la allowlist → outputs vacíos.

    Devuelve credenciales descifradas; jamás deben llegar a LangSmith.
    """
    obs = _RecordingObservability()

    async def node(_state: dict) -> dict:
        return {
            "commerce_integration_ctx": {
                "credentials": {"domain": "marea.myshopify.com", "token": "shpat_SECRET"},
            },
            "system_prompt": "prompt interno largo",
        }

    wrapped = _traced("load_tenant_context", node, _make_deps(obs))
    await wrapped(dict(_TRACE))

    assert len(obs.calls) == 1
    assert obs.calls[0]["outputs"] == {}
    # El token no aparece en ninguna parte del payload serializado.
    assert "shpat_SECRET" not in str(obs.calls[0])


@pytest.mark.asyncio
async def test_listed_node_emits_only_allowlisted_keys() -> None:
    obs = _RecordingObservability()

    async def node(_state: dict) -> dict:
        return {
            "decision": "respond",
            "confidence": 0.92,
            "agent_response": "Tu pedido va en camino",
            "system_prompt": "no debería emitirse",  # no está en la allowlist de reason
        }

    wrapped = _traced("reason", node, _make_deps(obs))
    await wrapped(dict(_TRACE))

    outputs = obs.calls[0]["outputs"]
    assert set(outputs) <= set(_NODE_OUTPUT_KEYS["reason"])
    assert "system_prompt" not in outputs
    assert outputs["decision"] == "respond"


@pytest.mark.asyncio
async def test_obs_none_is_passthrough() -> None:
    """Sin observability el wrapper no rompe el nodo."""

    async def node(_state: dict) -> dict:
        return {"decision": "respond"}

    wrapped = _traced("reason", node, _make_deps(None))
    result = await wrapped(dict(_TRACE))
    assert result == {"decision": "respond"}


@pytest.mark.asyncio
async def test_missing_trace_is_passthrough() -> None:
    """Sin trace id en el state (caller sin LangSmith) no se intenta emitir."""
    obs = _RecordingObservability()

    async def node(_state: dict) -> dict:
        return {"decision": "respond"}

    wrapped = _traced("reason", node, _make_deps(obs))
    result = await wrapped({})
    assert result == {"decision": "respond"}
    assert obs.calls == []


@pytest.mark.asyncio
async def test_node_exception_still_traces_and_reraises() -> None:
    obs = _RecordingObservability()

    async def node(_state: dict) -> dict:
        raise ValueError("boom")

    wrapped = _traced("reason", node, _make_deps(obs))
    with pytest.raises(ValueError, match="boom"):
        await wrapped(dict(_TRACE))

    assert len(obs.calls) == 1
    assert obs.calls[0]["error"] == "boom"
    assert obs.calls[0]["outputs"] == {}


def test_redact_dict_strips_nested_secrets() -> None:
    payload = {
        "tool_results": [
            {"slug": "shopify.get_order", "credentials": {"token": "shpat_x"}},
        ],
        "access_token": "abc",
        "safe": "visible",
    }
    out = _redact_dict(payload)
    assert out["access_token"] == "[REDACTED]"
    assert out["tool_results"][0]["credentials"] == "[REDACTED]"
    assert out["tool_results"][0]["slug"] == "shopify.get_order"
    assert out["safe"] == "visible"
