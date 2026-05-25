"""Bot cliente sintético del simulador.

Usa Haiku 4.5 con temperature=0.7: necesita coherencia, no inteligencia.
El system prompt se marca para prompt caching entre turnos de la misma simulación.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from apps.api.db.models import UserProfile
from apps.api.simulator.prompts import SIMULATOR_PROMPT

logger = logging.getLogger(__name__)

SIMULATOR_MODEL = "claude-haiku-4-5-20251001"
SIMULATOR_TEMPERATURE = 0.7
SIMULATOR_MAX_TOKENS = 512
SIMULATOR_TIMEOUT_SECONDS = 30  # tope por llamada para no colgar el run
HISTORY_TRUNCATION = 5  # turnos visibles al simulador


@dataclass(frozen=True)
class SimulatorTurn:
    message: str
    goal_achieved: bool
    give_up: bool
    internal_reasoning: str
    input_tokens: int
    output_tokens: int


class UserSimulator:
    def __init__(self, profile: UserProfile, anthropic: AsyncAnthropic) -> None:
        self._profile = profile
        self._anthropic = anthropic
        self._system_prompt = _build_system_prompt(profile)

    def first_message(self) -> SimulatorTurn:
        """Primer mensaje de la persona — del fixture, sin llamar al LLM."""
        return SimulatorTurn(
            message=self._profile.initial_message,
            goal_achieved=False,
            give_up=False,
            internal_reasoning="initial_message",
            input_tokens=0,
            output_tokens=0,
        )

    async def next_turn(
        self,
        conversation_history: list[dict],
        turn_number: int,
    ) -> SimulatorTurn:
        """Genera el siguiente mensaje del cliente sintético."""
        # Truncar a los últimos HISTORY_TRUNCATION turnos
        history = conversation_history[-HISTORY_TRUNCATION:]

        response = await self._anthropic.messages.create(
            model=SIMULATOR_MODEL,
            max_tokens=SIMULATOR_MAX_TOKENS,
            temperature=SIMULATOR_TEMPERATURE,
            system=[
                {
                    "type": "text",
                    "text": self._system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=_build_messages(history),
            timeout=SIMULATOR_TIMEOUT_SECONDS,
        )

        raw = response.content[0].text.strip() if response.content else "{}"
        return _parse_turn(raw, response.usage.input_tokens, response.usage.output_tokens)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _build_system_prompt(profile: UserProfile) -> str:
    persona = profile.persona
    give_up_after = persona.get("give_up_after", 8)
    return SIMULATOR_PROMPT.format(
        persona_json=json.dumps(persona, ensure_ascii=False, indent=2),
        store_name="la tienda",
        language=profile.language,
        goal=profile.goal,
        give_up_after=give_up_after,
    )


def _build_messages(history: list[dict]) -> list[dict]:
    """Convierte el historial al formato messages de Anthropic DESDE LA PERSPECTIVA
    DEL CLIENTE (el simulador ES el cliente).

    Por eso el mapeo está "invertido" respecto al grafo:
    - mensajes del cliente (customer) → "assistant" (lo que el simulador YA dijo)
    - mensajes del agente (agent)      → "user" (lo que la otra parte le dijo)

    Si se mapeara al revés, el modelo creería que él dijo las palabras del agente
    y respondería en la voz del agente (eco/bucle).
    """
    messages = []
    for turn in history:
        role = turn.get("role", "")
        content = turn.get("content", "")
        # Anthropic rechaza mensajes con content vacío — los saltamos.
        if not content.strip():
            continue
        if role == "customer":
            messages.append({"role": "assistant", "content": content})
        elif role == "agent":
            messages.append({"role": "user", "content": content})
    # Anthropic exige que la secuencia empiece con "user". El historial suele empezar
    # con el mensaje inicial del cliente (→ assistant), así que descartamos cualquier
    # mensaje assistant inicial hasta el primer user (el primer mensaje del agente).
    while messages and messages[0]["role"] == "assistant":
        messages.pop(0)
    # El historial termina en el mensaje del agente → mapea a "user" → el modelo
    # genera el siguiente turno del cliente como "assistant". Correcto.
    return messages


def _parse_turn(raw: str, input_tokens: int, output_tokens: int) -> SimulatorTurn:
    """Parsea el JSON del simulador. Fallback conservador si falla."""
    try:
        # Buscar bloque JSON si hay texto alrededor
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
        else:
            data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("simulator_json_parse_failed raw=%s", raw[:200])
        return SimulatorTurn(
            message=raw[:500] if raw else "...",
            goal_achieved=False,
            give_up=False,
            internal_reasoning="parse_error",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    return SimulatorTurn(
        message=str(data.get("message", "")),
        goal_achieved=bool(data.get("goal_achieved", False)),
        give_up=bool(data.get("give_up", False)),
        internal_reasoning=str(data.get("internal_reasoning", "")),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
