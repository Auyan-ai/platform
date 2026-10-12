"""Scenarios RE-* — Devoluciones y reembolsos (7 scenarios)."""

from __future__ import annotations

from typing import Any

from apps.api.simulator.scenarios.dates import days_ago

_ORDER_IN_WINDOW: dict[str, Any] = {
    "get_order_by_name": {
        "found": True,
        "id": 2001,
        "order_number": "#1234",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "fulfillments": [
            {
                "tracking_number": "1Z999AA10123456784",
                "tracking_url": "https://wwwapps.ups.com/",
                "tracking_company": "UPS",
            }
        ],
        "created_at": days_ago(15),
        "line_items": [
            {"id": 5001, "title": "Camiseta azul L", "quantity": 1, "price": "29.99"}
        ],
    },
    "get_policies": [
        {
            "title": "Política de devolución",
            "body": "Tienes 30 días desde la fecha de compra para devolver tu pedido.",
        }
    ],
    "start_return": {"ok": True, "simulated": True, "id": 9001, "status": "open"},
}

_ORDER_OUT_OF_WINDOW: dict[str, Any] = {
    "get_order_by_name": {
        "found": True,
        "id": 2001,
        "order_number": "#1234",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "fulfillments": [{"tracking_number": "1Z999AA", "tracking_url": "https://"}],
        "created_at": days_ago(55),  # >30 días atrás
        "line_items": [
            {"id": 5001, "title": "Camiseta azul L", "quantity": 1, "price": "29.99"}
        ],
    },
    "get_policies": [
        {
            "title": "Política de devolución",
            "body": "Tienes 30 días desde la fecha de compra para devolver tu pedido.",
        }
    ],
}

_ORDER_BROKEN_PRODUCT: dict[str, Any] = {
    "get_order_by_name": {
        "found": True,
        "id": 2001,
        "order_number": "#1234",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "created_at": days_ago(10),
        "total_price": "49.99",
        "currency": "EUR",
        "line_items": [
            {"id": 5001, "title": "Lámpara LED", "quantity": 1, "price": "49.99"}
        ],
    },
    "get_refundable_balance": {"captured": "49.99", "refunded": "0", "currency": "EUR"},
    "refund_partial": {"ok": True, "simulated": True},
}

_ORDER_DIGITAL: dict[str, Any] = {
    "get_order_by_name": {
        "found": True,
        "id": 2002,
        "order_number": "#1235",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "created_at": days_ago(5),
        "line_items": [
            {"id": 5002, "title": "Plantilla digital Notion", "quantity": 1, "price": "12.00"}
        ],
        "tags": "digital",
    },
    "get_policies": [
        {
            "title": "Política de devolución",
            "body": (
                "Los productos digitales no son elegibles para devolución una vez descargados."
            ),
        }
    ],
}


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "RE-01",
        "name": "RE-01: Devolución en plazo",
        "description": "Cliente cooperativo quiere devolver pedido dentro del plazo de 30 días por talla/preferencia, sin defecto ni reembolso inmediato.",
        "aop_slug": "returns",
        "capabilities": [],
        "profile": "cooperativo",
        "goal": "Iniciar una devolución estándar del pedido #1234 porque la talla no me queda bien; no pedir reembolso inmediato ni cambio por defecto.",
        "initial_message": "Hola, quiero devolver mi pedido #1234 porque la talla no me queda bien",
        "expected_outcome": "El agente inicia la devolución y confirma el proceso.",
        "mock_fixtures": {"shopify": _ORDER_IN_WINDOW},
        "assertions": {
            "skills_called": ["shopify.start_return"],
            "skills_not_called": ["shopify.refund_partial"],
            "outcome_is": "resolved",
        },
        "max_turns": 6,
    },
    {
        "id": "RE-02",
        "name": "RE-02: Devolución fuera de plazo",
        "description": "Cliente quiere devolver pedido de hace más de 30 días. El agente informa la política sin iniciar devolución.",
        "aop_slug": "returns",
        "capabilities": [],
        "profile": "cooperativo",
        "goal": "Devolver pedido #1234 de hace 55 días",
        "initial_message": "Quiero devolver mi pedido #1234, lo compré hace un par de meses",
        "expected_outcome": "El agente informa que el plazo venció y cita la política de 30 días.",
        "mock_fixtures": {"shopify": _ORDER_OUT_OF_WINDOW},
        "assertions": {
            "response_contains": ["30 días", "política"],
            "skills_not_called": ["shopify.start_return"],
        },
        "max_turns": 4,
    },
    {
        "id": "RE-03",
        "name": "RE-03: Reembolso por producto roto (L3)",
        "description": (
            "Cliente reporta producto roto. `refund_partial` está apagada por defecto en todos "
            "los tenants (s84): el agente no la tiene, no promete el reembolso y escala."
        ),
        "aop_slug": "refunds",
        "capabilities": [],
        "profile": "cooperativo",
        "goal": "Obtener reembolso por lámpara que llegó rota",
        "initial_message": "Me llegó la lámpara del pedido #1234 completamente rota",
        "expected_outcome": "El agente pasa el caso al equipo sin prometer ni tramitar el reembolso.",
        "mock_fixtures": {"shopify": _ORDER_BROKEN_PRODUCT},
        "assertions": {
            "skills_not_called": ["shopify.refund_partial"],
            "must_escalate": True,
            "escalation_reason_present": True,
        },
        "max_turns": 6,
    },
    {
        "id": "RE-04",
        "name": "RE-04: Devolver sin número de pedido",
        "description": "Cliente vago no da número de pedido. El agente busca alternativas.",
        "aop_slug": "returns",
        "capabilities": [],
        "profile": "vago",
        "goal": "Devolver algo que compré pero no sé el número de pedido",
        "initial_message": "Quiero devolver algo, no sé bien el número",
        "expected_outcome": "El agente pide el email del cliente para localizar el pedido.",
        "mock_fixtures": {"shopify": {"search_orders_by_email": [], "get_order_by_name": None}},
        "assertions": {},
        "max_turns": 6,
    },
    {
        "id": "RE-05",
        "name": "RE-05: Devolver producto digital",
        "description": "Cliente quiere devolver un producto digital. El agente informa que no aplica devolución.",
        "aop_slug": "returns",
        "capabilities": [],
        "profile": "cooperativo",
        "goal": "Devolver plantilla digital que no me sirve",
        "initial_message": "Quiero devolver la plantilla digital que compré, pedido #1235",
        "expected_outcome": "El agente informa que los productos digitales no tienen devolución.",
        "mock_fixtures": {"shopify": _ORDER_DIGITAL},
        "assertions": {
            "response_contains": ["digital", "devolución"],
            "skills_not_called": ["shopify.start_return"],
        },
        "max_turns": 4,
    },
    {
        "id": "RE-06",
        "name": "RE-06: Cliente agresivo exige reembolso",
        "description": "Cliente impaciente y agresivo exige reembolso inmediato. El agente debe mantener tono profesional y escalar.",
        "aop_slug": "complaint",
        "capabilities": [],
        "profile": "impaciente",
        "goal": "Exigir reembolso inmediato por producto defectuoso",
        "initial_message": "¡Esto es una estafa! Quiero mi dinero ya, el producto está roto",
        "expected_outcome": "El agente mantiene tono profesional y escala al equipo humano.",
        "mock_fixtures": {"shopify": _ORDER_BROKEN_PRODUCT},
        "assertions": {
            "must_escalate": True,
        },
        "max_turns": 5,
    },
    {
        "id": "RE-07",
        "name": "RE-07: Inicia devolución, se arrepiente en turno 3",
        "description": "Cliente inicia proceso de devolución y luego decide no devolver.",
        "aop_slug": "returns",
        "capabilities": [],
        "profile": "cooperativo",
        "goal": "Iniciar devolución, luego cancelarla porque decidí quedarme con el producto",
        "initial_message": "Hola, quiero devolver el pedido #1234",
        "expected_outcome": "El agente acepta que el cliente no quiere proceder y cierra amablemente.",
        "mock_fixtures": {"shopify": _ORDER_IN_WINDOW},
        "assertions": {
            "outcome_is": "resolved",
        },
        "max_turns": 8,
    },
]
