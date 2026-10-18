"""Cliente de Anthropic real con el transporte HTTP falso.

El SDK valida los argumentos y serializa la petición igual que en producción; el test lee
el JSON y las cabeceras que habrían salido y decide qué devuelve la API.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx2


class RecordingAnthropic:
    def __init__(self, *responses: dict[str, Any]) -> None:
        self.requests: list[dict[str, Any]] = []
        self.beta_headers: list[str | None] = []
        self._responses = list(responses)
        self.client = anthropic.AsyncAnthropic(
            api_key="test-key",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle)),
        )

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        self.beta_headers.append(request.headers.get("anthropic-beta"))
        return httpx2.Response(200, json=self._responses.pop(0))


def message(
    *content: dict[str, Any],
    stop_reason: str = "tool_use",
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 100,
    output_tokens: int = 50,
    stop_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": list(content),
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def tool_use(name: str, payload: dict[str, Any], *, id: str = "toolu_1") -> dict[str, Any]:
    return {"type": "tool_use", "id": id, "name": name, "input": payload}


def thinking(signature: str = "sig_1") -> dict[str, Any]:
    return {"type": "thinking", "thinking": "", "signature": signature}


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def refusal(category: str = "cyber", model: str = "claude-opus-5-5") -> dict[str, Any]:
    return message(
        stop_reason="refusal",
        model=model,
        stop_details={"type": "refusal", "category": category, "explanation": None},
    )
