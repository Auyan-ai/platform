"""Scenarios EX-* — Edge cases (4 scenarios)."""

from __future__ import annotations

from typing import Any

from apps.api.simulator.scenarios.dates import days_ago

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "EX-01",
        "name": "EX-01: Mock retorna error de Shopify",
        "description": "La skill de tracking retorna error de API. El agente no debe exponer error interno y debe escalar.",
        "aop_slug": "order_status",
        "capabilities": ["ORD-01"],
        "profile": "cooperativo",
        "goal": "Saber el tracking del pedido #1234 cuando Shopify falla",
        "initial_message": "Hola, ¿cómo va el pedido #1234?",
        "expected_outcome": (
            "El agente no expone el error ni le pide más datos al cliente: con la tienda "
            "caída, el código escala (`commerce_unavailable`) con el texto fijo."
        ),
        "mock_fixtures": {
            "shopify": {
                "get_order_by_name": {"_error": "SHOPIFY_API_UNAVAILABLE"},
                "search_orders_by_email": {"_error": "SHOPIFY_API_UNAVAILABLE"},
            }
        },
        "assertions": {
            "response_not_contains": ["error interno", "exception", "traceback"],
            "response_contains": ["no puedo consultar los pedidos"],
            "must_escalate": True,
        },
        "max_turns": 4,
    },
    {
        "id": "EX-02",
        "name": "EX-02: Pregunta sin respuesta en KB",
        "description": "El cliente pregunta algo válido del dominio pero que no está en la knowledge base. El agente escala con buena puntuación de knowledge.",
        "aop_slug": "default",
        "capabilities": [],
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
        "aop_slug": "order_status",
        "capabilities": [],
        "profile": "vago",
        "goal": "No dar ninguna información útil durante toda la conversación",
        "initial_message": "Hola, tengo un problema",
        "expected_outcome": (
            "Sin pedido ni datos, el agente pide lo que falta y acaba pasando el caso al equipo."
        ),
        "mock_fixtures": {"shopify": {"get_order_by_name": None, "search_orders_by_email": []}},
        "assertions": {
            "outcome_is": "escalated",
        },
        "max_turns": 4,
    },
    {
        "id": "EX-04",
        "name": "EX-04: Cancelar pedido pagado (L3)",
        "description": "Cliente quiere cancelar pedido pagado. La skill cancel_order es L3 y requiere aprobación humana.",
        "aop_slug": "order_change",
        "capabilities": ["ORD-05"],
        "profile": "cooperativo",
        "goal": "Cancelar pedido #1500 que compré por error",
        "initial_message": "Hola, compré el pedido #1500 por error, ¿puedo cancelarlo?",
        "expected_outcome": "El agente ejecuta cancel_order L3 y queda pendiente de aprobación humana.",
        "mock_fixtures": {
            "shopify": {
                "get_order_by_name": {
                    "found": True,
                    "id": 4001,
                    "name": "#1500",
                    "financial_status": "paid",
                    "fulfillment_status": "unfulfilled",
                    "created_at": days_ago(1),
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
    {
        "id": "EX-05",
        "name": "EX-05: Cancelar pedido ya enviado (L3 rechazada en código)",
        "description": (
            "Cliente quiere cancelar un pedido que el agente lee como no enviado, pero que "
            "sale del almacén antes de pedir la aprobación (la relectura del pedido trae "
            "tracking). El código rechaza la cancelación y escala con texto fijo."
        ),
        "aop_slug": "order_change",
        "capabilities": ["ORD-06"],
        "profile": "cooperativo",
        "goal": "Cancelar el pedido #1500 porque ya no lo necesito",
        "initial_message": "Hola, quiero cancelar el pedido #1500, ya no lo necesito.",
        "expected_outcome": (
            "No se crea aprobación: el agente dice que el pedido ya salió del almacén y pasa "
            "el caso al equipo, sin prometer la cancelación."
        ),
        "mock_fixtures": {
            "shopify": {
                "get_order_by_name": {
                    "found": True,
                    "id": 4001,
                    "name": "#1500",
                    "financial_status": "paid",
                    "fulfillment_status": "unfulfilled",
                    "created_at": days_ago(1),
                    "line_items": [{"id": 6001, "title": "Zapatillas", "quantity": 1}],
                },
                "get_order_snapshot": {
                    "id": "gid://shopify/Order/4001",
                    "name": "#1500",
                    "cancelledAt": None,
                    "displayFulfillmentStatus": "FULFILLED",
                    "fulfillments": [{"status": "SUCCESS", "trackingInfo": [{"number": "1Z9"}]}],
                    "transactions": [],
                },
            }
        },
        "assertions": {
            "must_escalate": True,
            "response_contains": ["ya ha salido del almacén"],
            # El texto del gate L3 de cancelación: si aparece, se creó la aprobación.
            "response_not_contains": ["tramitar la cancelación"],
        },
        "max_turns": 4,
    },
]
