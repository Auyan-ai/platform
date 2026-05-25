"""Scenarios CE-* — Consulta de envío y tracking (8 scenarios)."""

from __future__ import annotations

from typing import Any

# Fixtures de Shopify reutilizables
_ORDER_1234_WITH_TRACKING: dict[str, Any] = {
    "get_order_by_name": {
        "found": True,
        "id": 1001,
        "order_number": "#1234",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "fulfillments": [
            {
                "tracking_number": "1Z999AA10123456784",
                "tracking_url": "https://wwwapps.ups.com/tracking/1Z999AA10123456784",
                "tracking_company": "UPS",
            }
        ],
        "created_at": "2026-05-20T10:00:00Z",
        "customer": {"email": "cliente@ejemplo.com", "first_name": "Ana"},
    }
}

_ORDER_1234_NO_TRACKING: dict[str, Any] = {
    "get_order_by_name": {
        "found": True,
        "id": 1001,
        "order_number": "#1234",
        "financial_status": "paid",
        "fulfillment_status": "unfulfilled",
        "fulfillments": [],
        "created_at": "2026-05-23T10:00:00Z",
        "customer": {"email": "cliente@ejemplo.com", "first_name": "Ana"},
    }
}

_ORDER_BY_EMAIL: dict[str, Any] = {
    "search_orders_by_email": [
        {
            "id": 1001,
            "order_number": "#1234",
            "fulfillment_status": "fulfilled",
            "created_at": "2026-05-20T10:00:00Z",
        }
    ],
    "get_order_by_name": {
        "found": True,
        "id": 1001,
        "order_number": "#1234",
        "fulfillment_status": "fulfilled",
        "fulfillments": [
            {
                "tracking_number": "1Z999AA10123456784",
                "tracking_url": "https://wwwapps.ups.com/tracking/1Z999AA10123456784",
                "tracking_company": "UPS",
            }
        ],
    },
}

_TWO_ORDERS: dict[str, Any] = {
    "search_orders_by_email": [
        {
            "id": 1001,
            "order_number": "#1234",
            "fulfillment_status": "fulfilled",
            "created_at": "2026-05-20T10:00:00Z",
        },
        {
            "id": 1002,
            "order_number": "#1235",
            "fulfillment_status": "unfulfilled",
            "created_at": "2026-05-22T10:00:00Z",
        },
    ]
}


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "CE-01",
        "name": "CE-01: Tracking de #1234 con fulfillment",
        "description": "Cliente cooperativo pide tracking de su pedido. El pedido existe y tiene tracking.",
        "aop_slug": "consulta_envio",
        "profile": "cooperativo",
        "goal": "Saber el tracking de mi pedido #1234",
        "initial_message": "Hola, quiero saber el estado de mi pedido #1234",
        "expected_outcome": "El agente proporciona el número de tracking y URL del pedido.",
        "mock_fixtures": {"shopify": _ORDER_1234_WITH_TRACKING},
        "assertions": {
            "skills_called": ["shopify.get_order_status"],
            "response_contains": ["tracking", "1Z999AA"],
            "max_turns": 2,
        },
        "max_turns": 4,
    },
    {
        "id": "CE-02",
        "name": "CE-02: Tracking de #1234 sin fulfillment",
        "description": "Pedido existe pero aún no tiene fulfillment/tracking. El agente debe informar sin escalar.",
        "aop_slug": "consulta_envio",
        "profile": "impaciente",
        "goal": "Saber por qué mi pedido no ha salido todavía",
        "initial_message": "¿Cuándo sale mi pedido #1234? Llevo días esperando",
        "expected_outcome": "El agente informa que el pedido aún no fue enviado, sin escalar.",
        "mock_fixtures": {"shopify": _ORDER_1234_NO_TRACKING},
        "assertions": {
            "skills_called": ["shopify.get_order_status"],
            "response_contains": ["aún no", "preparando"],
            "must_escalate": False,
        },
        "max_turns": 4,
    },
    {
        "id": "CE-03",
        "name": "CE-03: Estado con email, cliente vago",
        "description": "El cliente no da número de pedido, solo el email. El agente busca por email.",
        "aop_slug": "consulta_envio",
        "profile": "vago",
        "goal": "Saber el estado de mis pedidos (tengo uno reciente)",
        "initial_message": "Hola, quiero saber cómo está mi pedido",
        "expected_outcome": "El agente pide el email o número de pedido y localiza el pedido.",
        "mock_fixtures": {"shopify": _ORDER_BY_EMAIL},
        "assertions": {
            "skills_called": ["shopify.get_order_by_email"],
            "max_turns": 3,
        },
        "max_turns": 6,
    },
    {
        "id": "CE-04",
        "name": "CE-04: Pedido #9999 no existe",
        "description": "Cliente da número de pedido que no existe. El agente no debe escalar ni llamar skills de cancelación.",
        "aop_slug": "consulta_envio",
        "profile": "cooperativo",
        "goal": "Saber el estado del pedido #9999",
        "initial_message": "Hola, ¿me puedes decir cómo está el pedido #9999?",
        "expected_outcome": "El agente informa que no encontró ese pedido.",
        "mock_fixtures": {"shopify": {"get_order_by_name": None}},
        "assertions": {
            "response_contains": ["no encontr"],
            "skills_not_called": ["shopify.cancel_order", "shopify.refund_partial"],
        },
        "max_turns": 4,
    },
    {
        "id": "CE-05",
        "name": "CE-05: Confunde fecha estimada de entrega",
        "description": "El cliente pregunta cuándo llega y confunde 'fecha de envío' con 'fecha de entrega'. El agente debe aclarar.",
        "aop_slug": "consulta_envio",
        "profile": "vago",
        "goal": "Saber exactamente cuándo llega mi pedido a casa",
        "initial_message": "Me dijeron que el pedido se envió el lunes, ¿cuándo exactamente llega?",
        "expected_outcome": "El agente aclara que el tracking tiene la información de entrega estimada.",
        "mock_fixtures": {"shopify": _ORDER_1234_WITH_TRACKING},
        "assertions": {
            "skills_called": ["shopify.get_order_status"],
        },
        "max_turns": 5,
    },
    {
        "id": "CE-06",
        "name": "CE-06: Cliente con 2 órdenes recientes",
        "description": "El cliente tiene 2 pedidos recientes. El agente debe preguntar cuál quiere consultar.",
        "aop_slug": "consulta_envio",
        "profile": "impaciente",
        "goal": "Saber el estado de mis pedidos (tengo dos recientes)",
        "initial_message": "Hola, necesito saber de mis pedidos urgente",
        "expected_outcome": "El agente detecta que hay 2 pedidos y pide al cliente que especifique cuál.",
        "mock_fixtures": {"shopify": _TWO_ORDERS},
        "assertions": {
            "skills_called": ["shopify.get_order_by_email"],
        },
        "max_turns": 6,
    },
    {
        "id": "CE-07",
        "name": "CE-07: Consulta en inglés",
        "description": "El cliente escribe en inglés. El agente debe responder en inglés.",
        "aop_slug": "consulta_envio",
        "profile": "cooperativo",
        "goal": "Get tracking information for order #1234",
        "initial_message": "Hi, I need to track my order #1234",
        "expected_outcome": "El agente responde en inglés con la información de tracking.",
        "mock_fixtures": {"shopify": _ORDER_1234_WITH_TRACKING},
        "assertions": {
            "skills_called": ["shopify.get_order_status"],
            "response_contains": ["tracking"],
        },
        "max_turns": 4,
    },
    {
        "id": "CE-08",
        "name": "CE-08: Tracking + pregunta de devolución al final",
        "description": "El cliente pregunta tracking y al final menciona 'y si quiero devolver'. El agente responde solo la consulta de envío.",
        "aop_slug": "consulta_envio",
        "profile": "cooperativo",
        "goal": "Saber el tracking y preguntar sobre devolución al final",
        "initial_message": "Hola, ¿cómo va el pedido #1234?",
        "expected_outcome": "El agente resuelve tracking y mantiene el AOP de consulta_envio.",
        "mock_fixtures": {"shopify": _ORDER_1234_WITH_TRACKING},
        "assertions": {
            "skills_called": ["shopify.get_order_status"],
            "max_turns": 4,
        },
        "max_turns": 6,
    },
]
