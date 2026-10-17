"""Scenarios LG-* — Idioma de la conversación, decidido en código (services/language.py).

Las aserciones de idioma usan el mismo detector que el agente: deterministas, sin judge.
"""

from __future__ import annotations

from typing import Any

from apps.api.simulator.scenarios.consulta_envio import _ORDER_1234_WITH_TRACKING
from apps.api.simulator.scenarios.default import _POLICIES

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "LG-01",
        "name": "LG-01: Consulta en catalán",
        "description": "El cliente escribe en catalán; el agente responde en catalán.",
        "aop_slug": "shipping_info",
        "capabilities": [],
        "profile": "cooperativo",
        "goal": "Saber cuánto tarda el envío estándar",
        "initial_message": "Bon dia, quant triga l'enviament normalment?",
        "expected_outcome": "El agente responde en catalán con el plazo de envío de la política.",
        "mock_fixtures": {"shopify": _POLICIES, "customer_language": "ca"},
        "assertions": {
            "skills_called": ["shopify.get_shop_policies"],
            "response_language": "ca",
        },
        "max_turns": 3,
    },
    {
        "id": "LG-02",
        "name": "LG-02: Cambia a inglés a mitad de conversación",
        "description": (
            "El cliente empieza en español y en su segundo mensaje pide seguir en inglés. "
            "Desde ahí el agente responde en inglés."
        ),
        "aop_slug": "order_status",
        "capabilities": ["ORD-01"],
        "profile": "cooperativo",
        "goal": (
            "Saber el tracking del pedido #1234. En tu segundo mensaje escribe en inglés y "
            "pide que te sigan atendiendo en inglés; a partir de ahí escribe solo en inglés. "
            "Solo das el objetivo por logrado cuando el agente te contesta en inglés."
        ),
        "initial_message": "Hola, ¿me dices cómo va mi pedido #1234?",
        "expected_outcome": "Primera respuesta en español; tras el cambio, respuestas en inglés.",
        "mock_fixtures": {"shopify": _ORDER_1234_WITH_TRACKING, "customer_language": "es"},
        "assertions": {
            "skills_called": ["shopify.get_order_status"],
            "final_response_language": "en",
        },
        "max_turns": 4,
    },
    {
        "id": "LG-03",
        "name": "LG-03: Política de devoluciones en inglés",
        "description": "El cliente pregunta en inglés por las devoluciones; el agente responde en inglés.",
        "aop_slug": "returns",
        "capabilities": [],
        "profile": "cooperativo",
        "goal": "Know how many days I have to return an item",
        "initial_message": "Hello, how many days do I have to return something?",
        "expected_outcome": "El agente responde en inglés con la ventana de devolución de la política.",
        "mock_fixtures": {"shopify": _POLICIES, "customer_language": "en"},
        "assertions": {
            "response_language": "en",
        },
        "max_turns": 3,
    },
]
