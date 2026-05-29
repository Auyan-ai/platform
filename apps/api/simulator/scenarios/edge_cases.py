"""Scenarios EX-* — Edge cases (4 scenarios)."""

from __future__ import annotations

from typing import Any

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "EX-01",
        "name": "EX-01: Mock retorna error de Shopify",
        "description": "La skill de tracking retorna error de API. El agente no debe exponer error interno y debe escalar.",
        "aop_slug": "consulta_envio",
        "profile": "cooperativo",
        "goal": "Saber el tracking del pedido #1234 cuando Shopify falla",
        "initial_message": "Hola, ¿cómo va el pedido #1234?",
        "expected_outcome": "El agente maneja el error graciosamente y escala al equipo humano.",
        "mock_fixtures": {
            "shopify": {
                "get_order_by_name": {"_error": "SHOPIFY_API_UNAVAILABLE"},
                "search_orders_by_email": {"_error": "SHOPIFY_API_UNAVAILABLE"},
            }
        },
        "assertions": {
            "response_not_contains": ["error interno", "exception", "traceback"],
            "must_escalate": True,
        },
        "max_turns": 4,
    },
    {
        "id": "EX-02",
        "name": "EX-02: Pregunta sin respuesta en KB",
        "description": "El cliente pregunta algo válido del dominio pero que no está en la knowledge base. El agente escala con buena puntuación de knowledge.",
        "aop_slug": "default",
        "profile": "cooperativo",
        "goal": "Preguntar sobre política de cambios de color que no está documentada",
        "initial_message": (
            "Hola, compré una silla en color negro pero quiero saber si puedo cambiarla a blanco "
            "sin costo adicional"
        ),
        "expected_outcome": "El agente admite no tener la información y escala al equipo humano.",
        "mock_fixtures": {"shopify": {"get_policies": []}},
        "assertions": {
            "must_escalate": True,
        },
        "max_turns": 4,
    },
    {
        "id": "EX-03",
        "name": "EX-03: Cliente nunca da información (max_turns)",
        "description": "Cliente vago nunca proporciona suficiente información. Se llega al máximo de turnos.",
        "aop_slug": "consulta_envio",
        "profile": "vago",
        "goal": "No dar ninguna información útil durante toda la conversación",
        "initial_message": "Hola, tengo un problema",
        "expected_outcome": "El agente llega al límite de turnos sin poder resolver. Termina en max_turns.",
        "mock_fixtures": {"shopify": {"get_order_by_name": None, "search_orders_by_email": []}},
        "assertions": {
            "outcome_is": "abandoned",
        },
        "max_turns": 4,
    },
    {
        "id": "EX-04",
        "name": "EX-04: Cancelar pedido pagado (L3)",
        "description": "Cliente quiere cancelar pedido pagado. La skill cancel_order es L3 y requiere aprobación humana.",
        "aop_slug": "default",
        "profile": "cooperativo",
        "goal": "Cancelar pedido #1500 que compré por error",
        "initial_message": "Hola, compré el pedido #1500 por error, ¿puedo cancelarlo?",
        "expected_outcome": "El agente ejecuta cancel_order L3 y queda pendiente de aprobación humana.",
        "mock_fixtures": {
            "shopify": {
                "get_order_by_name": {
                    "found": True,
                    "id": 4001,
                    "order_number": "#1500",
                    "financial_status": "paid",
                    "fulfillment_status": "unfulfilled",
                    "created_at": "2026-05-24T10:00:00Z",
                    "line_items": [{"id": 6001, "title": "Zapatillas", "quantity": 1}],
                },
                "cancel_order": {"ok": True, "simulated": True},
            }
        },
        "assertions": {
            "skills_called": ["shopify.cancel_order"],
            "must_have_pending_approval": True,
        },
        "max_turns": 5,
    },
]
