"""Scenarios LG-* — Idioma de la conversación, decidido en código (services/language.py).

Las aserciones de idioma usan el mismo detector que el agente: deterministas, sin judge.
"""

from __future__ import annotations

from typing import Any

from apps.api.simulator.scenarios.consulta_envio import _ORDER_1234_WITH_TRACKING
from apps.api.simulator.scenarios.default import _POLICIES
from apps.api.simulator.scenarios.orders import _ORDER_1500, _snapshot

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
    {
        "id": "LG-04",
        "name": "LG-04: Tienda caída con el cliente en inglés",
        "description": (
            "Shopify no responde y el cliente escribe en inglés. El texto fijo de "
            "`commerce_unavailable` sale del catálogo en inglés, no en español."
        ),
        "aop_slug": "order_status",
        "capabilities": ["ORD-01"],
        "profile": "cooperativo",
        "goal": "Find out where my order #1234 is",
        "initial_message": "Hi, where is my order #1234?",
        "expected_outcome": "Escala con el texto fijo de tienda caída, en inglés.",
        "mock_fixtures": {
            "shopify": {
                "get_order_by_name": {"_error": "SHOPIFY_API_UNAVAILABLE"},
                "search_orders_by_email": {"_error": "SHOPIFY_API_UNAVAILABLE"},
            },
            "customer_language": "en",
        },
        "assertions": {
            "response_contains": ["I can't look up the store's orders"],
            "response_language": "en",
            "must_escalate": True,
        },
        "max_turns": 4,
    },
    {
        "id": "LG-05",
        "name": "LG-05: Cancelación (L3) en inglés deja la aprobación pendiente y responde en inglés",
        "description": (
            "El cliente pide en inglés cancelar un pedido sin enviar. La acción queda "
            "pendiente de aprobación y todo lo que recibe el cliente, incluido el mensaje "
            "del gate, está en inglés."
        ),
        "aop_slug": "order_change",
        "capabilities": ["ORD-05"],
        "profile": "cooperativo",
        "goal": "Cancel my order #1500, I bought it by mistake. Confirm if asked.",
        "initial_message": "Hi, I want to cancel my order #1500, I bought it by mistake.",
        "expected_outcome": "Aprobación pendiente de la cancelación; respuestas en inglés.",
        "mock_fixtures": {
            "shopify": {
                "get_order_by_name": _ORDER_1500,
                "get_order_snapshot": _snapshot("shopify_payments", False),
            },
            "customer_language": "en",
        },
        "assertions": {
            "skills_called": ["shopify.cancel_order"],
            "must_have_pending_approval": True,
            "response_language": "en",
        },
        "max_turns": 5,
    },
]
