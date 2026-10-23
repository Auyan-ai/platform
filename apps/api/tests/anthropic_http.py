"""Cliente de Anthropic real con el transporte HTTP falso.

El SDK valida los argumentos y serializa la petición igual que en producción; el test lee
el JSON y las cabeceras que habrían salido y decide qué devuelve la API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx2


@dataclass(frozen=True)
class ApiError:
    """Respuesta de error de la API: el SDK la convierte en su clase de error real."""

    status: int
    headers: dict[str, str] = field(default_factory=dict)


class ConnectionDrop:
    """La conexión se cae antes de la respuesta: el SDK lanza `APIConnectionError`."""


def overloaded() -> ApiError:
    return ApiError(529)


def api_error(status: int, **headers: str) -> ApiError:
    return ApiError(status, headers)


_ERROR_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    429: "rate_limit_error",
    529: "overloaded_error",
}


class RecordingAnthropic:
    def __init__(self, *responses: dict[str, Any] | ApiError | ConnectionDrop) -> None:
        self.requests: list[dict[str, Any]] = []
        self.beta_headers: list[str | None] = []
        # Timeout de lectura con el que salió cada intento (`timeout=` de la petición).
        self.read_timeouts: list[float | None] = []
        self._responses = list(responses)
        self.client = anthropic.AsyncAnthropic(
            api_key="test-key",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle)),
        )

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        self.beta_headers.append(request.headers.get("anthropic-beta"))
        self.read_timeouts.append(request.extensions.get("timeout", {}).get("read"))
        response = self._responses.pop(0)
        if isinstance(response, ConnectionDrop):
            raise httpx2.ConnectError("connection reset", request=request)
        if isinstance(response, ApiError):
            error_type = _ERROR_TYPES.get(response.status, "api_error")
            return httpx2.Response(
                response.status,
                headers=response.headers,
                json={"type": "error", "error": {"type": error_type, "message": error_type}},
            )
        return httpx2.Response(200, json=response)


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
