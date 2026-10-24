"""Wrapper para llamadas a Claude con tools y reintentos.

Reintentos: solo aquí (`create_message`); el cliente del SDK va con `max_retries=0`.
Backoff exponencial (o el `retry-after` de la API) sobre errores transitorios
(`is_transient`): conexión, timeout y los códigos que el propio SDK reintenta (408, 409,
429, 5xx, 529 incluido). Se decide por código de estado, no por clase: en el SDK 1.x el
529 es `OverloadedError`, que ya no hereda de `InternalServerError`. El resto de 4xx NO se
reintenta — son problemas nuestros. Cada llamada, reintentos incluidos, cabe en
`LLM_CALL_BUDGET_SECONDS`: el último intento se acorta a lo que queda.

Caída total del proveedor (saldo agotado, 401, 403): no es transitoria ni reintentable.
`classify_provider_error` la detecta y `call_claude_with_tools` la relanza como
`LLMProviderUnavailable`, para que el turno escale y se alerte (ver `services/llm_alert.py`).

`call_claude_for_decision` es la única pieza que traduce "necesito una decisión con esta
tool" a la petición del modelo configurado (`integrations/model_capabilities.py`): tool
forzada donde el modelo la acepta y no piensa; `auto` + `strict` + instrucción donde no.
Devuelve la tool llamada o un `NoDecision` explícito (refusal, sin tool, max_tokens).
`call_claude_text` hace lo mismo para las llamadas que solo esperan texto.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import anthropic
from apps.api.core.config import LLM_CALL_BUDGET_SECONDS, get_models
from apps.api.integrations.llm_ledger import LLMCall, ModelRole, record_call
from apps.api.integrations.model_capabilities import ThinkingSettings, capabilities_of
from apps.api.integrations.pricing import LLMUsage, compute_llm_cost

if TYPE_CHECKING:
    from anthropic.types import Message

logger = logging.getLogger(__name__)

_TRANSIENT_STATUSES = frozenset({408, 409, 429})
_MAX_BACKOFF_SECONDS = 10.0
# Un intento con menos margen que esto no llega a recibir la respuesta: mejor fallar ya.
_MIN_ATTEMPT_SECONDS = 5.0


def is_transient(exc: BaseException) -> bool:
    """Error que puede salir bien al repetir la misma petición. Misma política que el SDK
    (`x-should-retry` manda si viene), para que no dependa de la jerarquía de clases."""
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if not isinstance(exc, anthropic.APIStatusError):
        return False
    should_retry = exc.response.headers.get("x-should-retry")
    if should_retry in ("true", "false"):
        return should_retry == "true"
    return exc.status_code in _TRANSIENT_STATUSES or exc.status_code >= 500


def _backoff_seconds(attempt: int, exc: BaseException) -> float:
    delay = min(2.0 ** (attempt - 1), _MAX_BACKOFF_SECONDS)
    if isinstance(exc, anthropic.APIStatusError):
        try:
            delay = max(delay, float(exc.response.headers.get("retry-after", 0)))
        except ValueError:
            pass
    return delay


async def create_message(
    client: anthropic.AsyncAnthropic,
    request: Mapping[str, Any],
    *,
    role: ModelRole,
    attempts: int,
    timeout_seconds: float,
    budget_seconds: float = LLM_CALL_BUDGET_SECONDS,
    trace_label: str | None = None,
) -> Message:
    """`messages.create` con reintentos sobre errores transitorios, todo dentro de
    `budget_seconds`: cada intento dura como mucho `timeout_seconds` o lo que quede.

    Único punto que llama a la API de mensajes: anota la respuesta (tokens, coste,
    latencia) en el libro del turno con su `role` (`integrations/llm_ledger.py`) y deja la
    línea de log `llm_call`."""
    started_at = datetime.now(UTC)
    started = time.monotonic()
    deadline = started + budget_seconds
    for attempt in range(1, attempts + 1):
        remaining = deadline - time.monotonic()
        try:
            response = await client.messages.create(
                **request, timeout=min(timeout_seconds, remaining)
            )
            _record_response(
                response,
                role=role,
                model=request["model"],
                label=trace_label or role,
                started_at=started_at,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            return response
        except anthropic.APIError as exc:
            delay = _backoff_seconds(attempt, exc)
            out_of_time = deadline - time.monotonic() - delay < _MIN_ATTEMPT_SECONDS
            if attempt == attempts or not is_transient(exc) or out_of_time:
                raise
            logger.warning(
                "llm_call_retry attempt=%d status=%s delay_s=%.1f",
                attempt,
                getattr(exc, "status_code", None),
                delay,
            )
            await asyncio.sleep(delay)
    raise ValueError("attempts debe ser >= 1")


def _record_response(
    response: Any,
    *,
    role: str,
    model: str,
    label: str,
    started_at: datetime,
    latency_ms: int,
) -> None:
    usage = LLMUsage.from_anthropic(response.usage)
    stop_reason = getattr(response, "stop_reason", None)
    record_call(
        LLMCall(
            role=role,
            model=model,
            label=label,
            usage=usage,
            cost_usd=compute_llm_cost(model, usage),
            latency_ms=latency_ms,
            started_at=started_at,
            ended_at=datetime.now(UTC),
            stop_reason=stop_reason if isinstance(stop_reason, str) else None,
        )
    )
    # dur_ms incluye los reintentos previos; sin ellos es la llamada en sí.
    logger.info(
        "llm_call label=%s role=%s model=%s dur_ms=%d in=%d cache_w=%d cache_r=%d out=%d stop=%s",
        label,
        role,
        model,
        latency_ms,
        usage.input_tokens,
        usage.cache_write_tokens,
        usage.cache_read_tokens,
        usage.output_tokens,
        stop_reason,
    )


PROVIDER_UNAVAILABLE_CATEGORY = "llm_provider_unavailable"
_CREDIT_BALANCE_MARKER = "credit balance"


class LLMProviderUnavailable(Exception):
    """Anthropic rechaza TODA llamada: saldo agotado, key inválida o sin permisos."""

    def __init__(self, reason: str, *, status_code: int | None, detail: str) -> None:
        super().__init__(f"{PROVIDER_UNAVAILABLE_CATEGORY}: {reason}")
        self.reason = reason
        self.status_code = status_code
        self.detail = detail


def classify_provider_error(exc: BaseException) -> str | None:
    """Devuelve la razón (`credit_balance_exhausted`, `authentication_failed`,
    `permission_denied`) si `exc` es una caída total del proveedor; si no, None.

    429 y 5xx no entran aquí: son transitorios y ya se reintentan.
    """
    if isinstance(exc, anthropic.AuthenticationError):
        return "authentication_failed"
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "permission_denied"
    if isinstance(exc, anthropic.BadRequestError) and _CREDIT_BALANCE_MARKER in str(exc).lower():
        return "credit_balance_exhausted"
    return None


def provider_unavailable_from(exc: BaseException) -> LLMProviderUnavailable | None:
    reason = classify_provider_error(exc)
    if reason is None:
        return None
    return LLMProviderUnavailable(
        reason, status_code=getattr(exc, "status_code", None), detail=str(exc)[:500]
    )


async def call_claude_with_tools(
    *,
    client: anthropic.AsyncAnthropic,
    model: str,
    role: ModelRole,
    system: str | list[dict[str, Any]],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any] | None = None,
    max_tokens: int = 1024,
    max_retries: int = 3,
    timeout_seconds: int = 30,
    cache: bool = False,
    trace_label: str | None = None,
    request_options: Mapping[str, Any] | None = None,
) -> Message:
    """Llama a Claude con una lista de tools, con reintentos en errores transitorios.

    Args:
        tools: lista de tool definitions ({"name", "description", "input_schema"}).
        tool_choice: si None, Claude elige libremente entre tools o texto.
            `{"type": "any"}` fuerza el uso de alguna tool.
            `{"type": "tool", "name": "..."}` fuerza una tool específica.
        cache: si True activa prompt caching (cache_control ephemeral) sobre el
            prefijo tools + system. Cachea las definiciones de tools (marca la última)
            y, si `system` llega como string, lo envuelve en un bloque cacheado. Si
            `system` llega ya como lista de bloques, el caller controla los breakpoints
            (debe marcar el bloque ESTABLE con cache_control). Pega solo si el prefijo
            es idéntico entre llamadas (TTL ~5 min).
        role: campo del `ModelRegistry` que pide la llamada: a él se atribuyen sus tokens y
            su coste (`integrations/llm_ledger.py`).
        trace_label: nombre de la línea `llm_call` que deja cada llamada (duración real +
            breakdown de tokens input/cache_write/cache_read/output; sirve para medir el
            prompt caching). Por defecto, el rol.
        request_options: campos extra de la petición (thinking, output_config,
            extra_headers) que arma la traducción por modelo.

    Raises:
        LLMProviderUnavailable si Anthropic rechaza por saldo agotado, 401 o 403.
        anthropic.APIError o subclase si después de los reintentos sigue fallando.
    """
    system_param, tools_param = _cached(system, tools, cache=cache)
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_param,
        "messages": messages,
    }
    if tools_param:
        kwargs["tools"] = tools_param
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if request_options:
        kwargs.update(request_options)

    try:
        return await create_message(
            client,
            kwargs,
            role=role,
            attempts=max_retries,
            timeout_seconds=timeout_seconds,
            trace_label=trace_label,
        )
    except anthropic.APIStatusError as exc:
        unavailable = provider_unavailable_from(exc)
        if unavailable is None:
            raise
        raise unavailable from exc


def _cached(
    system: str | list[dict[str, Any]], tools: list[dict[str, Any]], *, cache: bool
) -> tuple[Any, list[dict[str, Any]]]:
    """System y tools tal como salen, con los breakpoints de caché si `cache`."""
    if not cache:
        return system, tools
    tools_param = tools
    if tools_param:
        # cache_control en la última tool cachea TODO el bloque de tools.
        # Copia superficial: no mutamos el input del caller.
        tools_param = [
            *tools_param[:-1],
            {**tools_param[-1], "cache_control": {"type": "ephemeral"}},
        ]
    system_param: Any = system
    if isinstance(system_param, str):
        system_param = [
            {"type": "text", "text": system_param, "cache_control": {"type": "ephemeral"}}
        ]
    return system_param, tools_param


def prefix_digest(system: Any, tools: Any, messages: list[dict[str, Any]]) -> str:
    """Huella de lo que precede a un turno del assistant: system, tools y mensajes previos,
    lo que la API comprueba antes de aceptar sus thinking blocks (preserved thinking)."""
    raw = json.dumps(
        {"system": system, "tools": tools, "messages": messages},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()


_THINKING_TYPES = frozenset({"thinking", "redacted_thinking"})


def _has_thinking(message: dict[str, Any]) -> bool:
    content = message.get("content")
    return isinstance(content, list) and any(b.get("type") in _THINKING_TYPES for b in content)


def _without_thinking(message: dict[str, Any]) -> dict[str, Any]:
    if not _has_thinking(message):
        return message
    return {
        **message,
        "content": [b for b in message["content"] if b.get("type") not in _THINKING_TYPES],
    }


def _turn_key(message: dict[str, Any]) -> str | None:
    """Un turno replayado se reconoce por su primer `tool_use`."""
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return str(block["id"])
    return None


def drop_stale_thinking(
    messages: list[dict[str, Any]],
    *,
    system: Any,
    tools: Any,
    prefixes: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Sin `block_binding` (thinking `between_tools`) la API no descarta un thinking block
    cuyo prefijo cambió: una cuenta con la comprobación activa da 400. Desde el primer
    turno del assistant cuyo prefijo ya no es el que tenía al escribirse (`prefixes`, por
    su primer `tool_use`), sus thinking blocks y los de después no se reenvían; texto y
    `tool_use` sí. Quitar un sufijo de la cadena de bloques es válido; uno del medio no."""
    for i, message in enumerate(messages):
        if message["role"] != "assistant" or not _has_thinking(message):
            continue
        key = _turn_key(message)
        if key is not None and prefixes.get(key) == prefix_digest(system, tools, messages[:i]):
            continue
        logger.warning(
            "thinking_blocks_not_replayed from_message=%d turn=%s: el prefijo cambió",
            i,
            key,
            extra={"from_message": i, "turn": key},
        )
        return [*messages[:i], *(_without_thinking(m) for m in messages[i:])]
    return messages


# Con thinking (adaptive, o las notas de progreso de `between_tools`), esos tokens cuentan
# contra `max_tokens`: un límite pensado para una respuesta corta cortaría la decisión
# antes de la tool.
THINKING_MIN_MAX_TOKENS = 16_000
# Con `auto` el modelo puede contestar sin tool: un reintento con la instrucción explícita.
NO_TOOL_RETRIES = 1


@dataclass(frozen=True)
class ToolDecision:
    """Lo que pide un nodo: una llamada a `tool`, o a cualquier tool ofrecida (`any_tool`,
    el paso del loop ReAct) cerrando con `tool`. `closing`: última vuelta del loop, solo
    vale `tool` (las demás siguen definidas porque el historial trae sus `tool_use`)."""

    tool: str
    any_tool: bool = False
    closing: bool = False

    @property
    def this_round(self) -> ToolDecision:
        """Lo que vale en esta vuelta: en la de cierre, solo `tool`."""
        return ToolDecision(self.tool, any_tool=self.any_tool and not self.closing)


def operator_messages_supported(model: str) -> bool:
    """El modelo admite mensajes `role: system` a mitad de conversación: una instrucción
    del operador va como mensaje añadido en vez de editar el system de arriba."""
    return capabilities_of(model).system_messages


def operator_note(text: str) -> dict[str, Any]:
    """Instrucción del operador a mitad de conversación (solo si
    `operator_messages_supported`). Va tras un mensaje `user` y antes de un `assistant` o
    al final."""
    return {"role": "system", "content": text}


def _with_trailing_note(messages: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Añade la nota al final; si ya acaba en una nota del operador, la amplía (dos
    mensajes `system` seguidos no siguen a un `user`)."""
    if messages and messages[-1]["role"] == "system":
        return [*messages[:-1], operator_note(f"{messages[-1]['content']}\n\n{text}")]
    return [*messages, operator_note(text)]


@dataclass(frozen=True)
class CallTrace:
    """Con qué salió una llamada y cómo terminó: va a su run de LangSmith."""

    model: str
    # "off", "adaptive" o "between_tools".
    thinking: str
    effort: str | None
    stop_reason: str | None
    refusal_category: str | None = None
    # Llamadas cobradas (el reintento sin tool cuenta).
    calls: int = 1

    @classmethod
    def of(
        cls, model: str, settings: ThinkingSettings, response: Any | None, *, calls: int = 1
    ) -> CallTrace:
        stop_reason = getattr(response, "stop_reason", None)
        category = None
        if stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
        return cls(
            model=model,
            thinking=settings.thinking["type"] if settings.thinking else "off",
            effort=settings.effort,
            stop_reason=stop_reason,
            refusal_category=category,
            calls=calls,
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolCalled:
    # La primera tool llamada: la que se ejecuta.
    block: Any
    # El turno del assistant entero (thinking, texto, `tool_use` en paralelo), para
    # devolverlo intacto en la siguiente vuelta del loop.
    content: list[dict[str, Any]]
    usage: LLMUsage
    # `prefix_digest` de lo que precedía a este turno, para saber si al replayarlo sus
    # thinking blocks siguen valiendo.
    prefix: str = ""
    call: CallTrace | None = None


@dataclass(frozen=True)
class NoDecision:
    kind: Literal["refusal", "max_tokens", "tool_not_called", "call_failed"]
    detail: str
    usage: LLMUsage
    call: CallTrace | None = None

    @property
    def reason(self) -> str:
        if self.kind == "refusal":
            return f"llm_refusal: {self.detail}"
        suffix = f" ({self.detail})" if self.detail else ""
        return f"llm_no_decision: {self.kind}{suffix}"


@dataclass(frozen=True)
class _DecisionRequest:
    system: str | list[dict[str, Any]]
    tools: list[dict[str, Any]]
    tool_choice: dict[str, Any]
    max_tokens: int
    options: dict[str, Any]
    forced: bool
    settings: ThinkingSettings
    # Instrucción de cierre que va como mensaje del operador al final (5.5).
    closing_note: str | None = None
    # Thinking preservado sin `block_binding` (`between_tools`): el cliente no reenvía
    # thinking blocks cuyo prefijo cambió (`drop_stale_thinking`).
    drop_stale_thinking: bool = False


def _closing_note(decision: ToolDecision) -> str:
    return (
        "Ya no quedan consultas en este turno. Cierra ahora llamando a "
        f"`{decision.tool}` con lo que ya tienes; no llames a otras herramientas."
    )


def _instruction(decision: ToolDecision) -> str:
    if decision.any_tool:
        return (
            "Responde siempre llamando a una herramienta: usa las disponibles para consultar "
            f"y `{decision.tool}` para cerrar el turno. No respondas solo con texto."
        )
    return (
        f"Responde siempre llamando a la herramienta `{decision.tool}`. "
        "No respondas solo con texto."
    )


def _with_instruction(
    system: str | list[dict[str, Any]], instruction: str
) -> str | list[dict[str, Any]]:
    if isinstance(system, str):
        return f"{system}\n\n{instruction}"
    return [*system, {"type": "text", "text": instruction}]


def _strict(tool: dict[str, Any]) -> dict[str, Any]:
    schema = anthropic.transform_schema(tool["input_schema"])
    return {**tool, "strict": True, "input_schema": schema}


def decision_request(
    *,
    model: str,
    role: ModelRole,
    system: str | list[dict[str, Any]],
    tools: list[dict[str, Any]],
    decision: ToolDecision,
    max_tokens: int,
) -> _DecisionRequest:
    """Traduce la decisión que pide un nodo a la petición que acepta `model`.

    Modelos que aceptan tool forzada y no piensan: `tool_choice` `any`/`tool`, la petición
    de siempre. El resto (5.5, o un rol con thinking): `auto`, la tool de decisión
    estricta y la instrucción al final del system. Donde el modelo admite mensajes del
    operador, el system no cambia en la vuelta de cierre: la instrucción de cierre va como
    mensaje al final (con thinking preservado, editar el system invalida los thinking
    blocks de las vueltas anteriores)."""
    caps = capabilities_of(model)
    thinking = get_models().thinking(role, model=model)
    options = thinking.request_options()
    this_round = decision.this_round
    if caps.forced_tool_choice and not thinking.thinking_on:
        choice = {"type": "any"} if this_round.any_tool else {"type": "tool", "name": decision.tool}
        return _DecisionRequest(
            system, tools, choice, max_tokens, options, forced=True, settings=thinking
        )
    note_closing = caps.system_messages and decision.closing
    return _DecisionRequest(
        system=_with_instruction(system, _instruction(decision if note_closing else this_round)),
        tools=[
            _strict(tool) if caps.strict_tools and tool["name"] == decision.tool else tool
            for tool in tools
        ],
        tool_choice={"type": "auto"},
        max_tokens=(
            max(max_tokens, THINKING_MIN_MAX_TOKENS)
            if thinking.writes_thinking_blocks
            else max_tokens
        ),
        options=options,
        forced=False,
        settings=thinking,
        closing_note=_closing_note(decision) if note_closing else None,
        drop_stale_thinking=(
            caps.preserved_thinking
            and thinking.thinking is not None
            and "block_binding" not in thinking.thinking
        ),
    )


def _as_param(block: Any) -> dict[str, Any]:
    return block.model_dump(mode="json", exclude_none=True)  # type: ignore[no-any-return]


def read_decision(response: Any, usage: LLMUsage) -> ToolCalled | NoDecision:
    """Primera tool llamada, o por qué no hubo ninguna. `refusal` y `max_tokens` van antes
    que el contenido: un `tool_use` cortado trae un `input` a medias (un `response_text`
    truncado que llegaría al cliente)."""
    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason == "refusal":
        category = getattr(getattr(response, "stop_details", None), "category", None)
        return NoDecision("refusal", category or "sin_categoria", usage)
    if stop_reason == "max_tokens":
        return NoDecision("max_tokens", "", usage)
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            return ToolCalled(block, [_as_param(b) for b in response.content], usage)
    return NoDecision("tool_not_called", str(stop_reason), usage)


async def call_claude_for_decision(
    *,
    client: anthropic.AsyncAnthropic,
    model: str,
    role: ModelRole,
    system: str | list[dict[str, Any]],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    decision: ToolDecision,
    max_tokens: int = 1024,
    max_retries: int = 3,
    timeout_seconds: int = 30,
    cache: bool = False,
    trace_label: str | None = None,
    replay_prefixes: Mapping[str, str] | None = None,
) -> ToolCalled | NoDecision:
    """Pide una decisión estructurada al modelo de `role` (o `model`, si un tenant fija el
    suyo). Sin tool tras el reintento, refusal o max_tokens → `NoDecision`, logueado como
    error: el nodo decide cómo escalar, nunca un texto vacío al cliente.

    `usage` suma todas las llamadas, reintento incluido. `replay_prefixes`: el
    `ToolCalled.prefix` de cada turno replayado en `messages`, por su primer `tool_use`.
    """
    request = decision_request(
        model=model,
        role=role,
        system=system,
        tools=tools,
        decision=decision,
        max_tokens=max_tokens,
    )
    system_sent, tools_sent = _cached(request.system, request.tools, cache=cache)
    turn = list(messages)
    if request.drop_stale_thinking:
        turn = drop_stale_thinking(
            turn, system=system_sent, tools=tools_sent, prefixes=replay_prefixes or {}
        )
    if request.closing_note is not None:
        turn = _with_trailing_note(turn, request.closing_note)
    usage = LLMUsage()
    for attempt in range(NO_TOOL_RETRIES + 1):
        try:
            response = await call_claude_with_tools(
                client=client,
                model=model,
                role=role,
                system=request.system,
                messages=turn,
                tools=request.tools,
                tool_choice=request.tool_choice,
                max_tokens=request.max_tokens,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
                cache=cache,
                trace_label=trace_label,
                request_options=request.options,
            )
        except anthropic.APIError as exc:
            if attempt == 0:
                raise
            # La primera llamada ya se cobró: sin esto su usage se perdía con la excepción.
            outcome = NoDecision(
                "call_failed",
                type(exc).__name__,
                usage,
                call=CallTrace.of(model, request.settings, None, calls=attempt + 1),
            )
            logger.error(
                "%s label=%s role=%s model=%s",
                outcome.reason,
                trace_label,
                role,
                model,
                exc_info=True,
                extra={"role": role, "model": model, "no_decision": outcome.kind},
            )
            return outcome
        usage = usage + LLMUsage.from_anthropic(response.usage)
        call = CallTrace.of(model, request.settings, response, calls=attempt + 1)
        outcome = replace(read_decision(response, usage), call=call)
        if isinstance(outcome, ToolCalled):
            return replace(outcome, prefix=prefix_digest(system_sent, tools_sent, turn))
        if request.forced or outcome.kind != "tool_not_called" or attempt == NO_TOOL_RETRIES:
            break
        turn = [
            *turn,
            {"role": "assistant", "content": [_as_param(b) for b in response.content]},
            {
                "role": "user",
                "content": "Tu respuesta anterior no llamó a ninguna herramienta. "
                + _instruction(decision.this_round),
            },
        ]
    logger.error(
        "%s label=%s role=%s model=%s attempts=%d",
        outcome.reason,
        trace_label,
        role,
        model,
        attempt + 1,
        extra={"role": role, "model": model, "no_decision": outcome.kind},
    )
    return outcome


@dataclass(frozen=True)
class TextReply:
    text: str
    usage: LLMUsage
    stop_reason: str | None
    refusal_category: str | None
    call: CallTrace | None = None

    @property
    def refusal_reason(self) -> str | None:
        """`llm_refusal: <categoría>` si el modelo se negó; el texto viene vacío."""
        if self.stop_reason != "refusal":
            return None
        return f"llm_refusal: {self.refusal_category or 'sin_categoria'}"


async def call_claude_text(
    *,
    client: anthropic.AsyncAnthropic,
    role: ModelRole,
    system: str | list[dict[str, Any]],
    messages: list[dict[str, Any]],
    max_tokens: int,
    timeout_seconds: float = 60.0,
    model: str | None = None,
    temperature: float | None = None,
    attempts: int = 3,
    trace_label: str | None = None,
) -> TextReply:
    """Llamada que espera texto (jueces, simulador, mensajes al cliente) traducida para el
    modelo del rol: thinking y esfuerzo del registro, `temperature` solo donde se acepta, y
    el texto leído por tipo de bloque (con thinking, el primer bloque no es texto).
    `timeout_seconds` es por intento; los reintentos son los de `create_message`."""
    model = model or getattr(get_models(), role)
    thinking = get_models().thinking(role, model=model)
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max(max_tokens, THINKING_MIN_MAX_TOKENS)
        if thinking.writes_thinking_blocks
        else max_tokens,
        "system": system,
        "messages": messages,
        **thinking.request_options(),
    }
    if temperature is not None and capabilities_of(model).sampling_params:
        kwargs["extra_body"] = {"temperature": temperature}
    response = await create_message(
        client,
        kwargs,
        role=role,
        attempts=attempts,
        timeout_seconds=timeout_seconds,
        trace_label=trace_label,
    )
    call = CallTrace.of(model, thinking, response)
    if call.stop_reason == "refusal":
        logger.error(
            "llm_refusal: %s role=%s model=%s",
            call.refusal_category or "sin_categoria",
            role,
            model,
            extra={"role": role, "llm_call": call.as_dict()},
        )
    return TextReply(
        text="".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ),
        usage=LLMUsage.from_anthropic(response.usage),
        stop_reason=call.stop_reason,
        refusal_category=call.refusal_category,
        call=call,
    )


def build_anthropic_client(api_key: str, *, timeout: float = 60.0) -> anthropic.AsyncAnthropic:
    """Construye el cliente async. Sin reintentos propios del SDK: los hace `create_message`,
    dentro del presupuesto por llamada; con los dos a la vez un intento se multiplicaba por 3.
    `timeout` es el del transport HTTP global; cada llamada fija el suyo."""
    return anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=0)
