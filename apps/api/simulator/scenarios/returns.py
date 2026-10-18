"""Scenarios RE-* — Devoluciones y reembolsos (8 scenarios)."""

from __future__ import annotations

from typing import Any

from apps.api.simulator.scenarios.dates import days_ago

# Política del escenario (ADR 0014): la fija el escenario, no el tenant del simulador.
_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "window": {"days": 30, "starts_at": "delivery"},
    "reasons": [
        {
            "code": "talla",
            "label": "La talla no me queda bien",
            "fault": "customer",
            "shopify_reason": "too-small",
            "required_evidence": [],
        },
        {
            "code": "defectuoso",
            "label": "Llegó roto o defectuoso",
            "fault": "store",
            "required_evidence": ["photo"],
            "shopify_reason": "damaged-or-defective",
        },
        {
            "code": "no_lo_quiero",
            "label": "Ya no lo quiero",
            "fault": "customer",
            "shopify_reason": "changed-my-mind",
            "required_evidence": [],
        },
    ],
    "shipping": {
        "method": "store_label",
        "payer": {"store_fault": "store", "customer_fault": "customer"},
        "customer_fee_mode": "fixed",
        "customer_fee": {"amount": "4.95", "currency": "EUR"},
    },
    "refund_days": 14,
    "refund_method": "original_payment",
    "restocking_fee_percent": {"store_fault": "0", "customer_fault": "0"},
    "excluded_product_tags": ["digital"],
    "exchanges": {
        "enabled": True,
        "kinds": ["variant"],
        "requires_approval": True,
        "higher_price": "customer_pays",
        "lower_price": "refund_difference",
        "ship_replacement": "after_receipt",
    },
    "returns_require_approval": True,
}


def _returnable(
    order_id: int, name: str, line_id: int, title: str, delivered: str, tags: list[str]
) -> dict[str, Any]:
    return {
        "order": {
            "id": f"gid://shopify/Order/{order_id}",
            "name": name,
            "processedAt": delivered,
            "cancelledAt": None,
            "taxesIncluded": True,
            "presentmentCurrencyCode": "EUR",
        },
        "returnableFulfillments": {
            "nodes": [
                {
                    "fulfillment": {"createdAt": delivered, "deliveredAt": delivered},
                    "returnableFulfillmentLineItems": {
                        "nodes": [
                            {
                                "quantity": 1,
                                "fulfillmentLineItem": {
                                    "id": f"gid://shopify/FulfillmentLineItem/{line_id}0",
                                    "lineItem": {
                                        "id": f"gid://shopify/LineItem/{line_id}",
                                        "name": title,
                                        "title": title,
                                        "product": {
                                            "id": "gid://shopify/Product/7001",
                                            "tags": tags,
                                        },
                                    },
                                },
                            }
                        ]
                    },
                }
            ]
        },
    }


def _calculated(line_id: int, amount: str) -> dict[str, Any]:
    def money(value: str) -> dict[str, Any]:
        return {"presentmentMoney": {"amount": value, "currencyCode": "EUR"}}

    return {
        "returnLineItems": [
            {
                "quantity": 1,
                "fulfillmentLineItem": {"id": f"gid://shopify/FulfillmentLineItem/{line_id}0"},
                "subtotalSet": money(f"-{amount}"),
                "totalTaxSet": money("0"),
            }
        ],
        "exchangeLineItems": [],
    }


_ORDER_IN_WINDOW: dict[str, Any] = {
    "get_order_by_name": {
        "found": True,
        "id": 2001,
        "name": "#1234",
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
        "line_items": [{"id": 5001, "title": "Camiseta azul L", "quantity": 1, "price": "29.99"}],
    },
    "get_policies": [
        {
            "title": "Política de devolución",
            "url": "https://tienda-sim.myshopify.com/policies/refund-policy",
            "body": "Tienes 30 días desde la fecha de compra para devolver tu pedido.",
        }
    ],
    "get_returnable_order": _returnable(
        2001, "#1234", 5001, "Camiseta azul L", days_ago(13), ["camisetas"]
    ),
    "calculate_return": _calculated(5001, "29.99"),
}

_ORDER_OUT_OF_WINDOW: dict[str, Any] = {
    "get_order_by_name": {
        "found": True,
        "id": 2001,
        "name": "#1234",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "fulfillments": [{"tracking_number": "1Z999AA", "tracking_url": "https://"}],
        "created_at": days_ago(55),  # >30 días atrás
        "line_items": [{"id": 5001, "title": "Camiseta azul L", "quantity": 1, "price": "29.99"}],
    },
    "get_returnable_order": _returnable(
        2001, "#1234", 5001, "Camiseta azul L", days_ago(52), ["camisetas"]
    ),
    "get_policies": [
        {
            "title": "Política de devolución",
            "url": "https://tienda-sim.myshopify.com/policies/refund-policy",
            "body": "Tienes 30 días desde la fecha de compra para devolver tu pedido.",
        }
    ],
}

_ORDER_BROKEN_PRODUCT: dict[str, Any] = {
    "get_order_by_name": {
        "found": True,
        "id": 2001,
        "name": "#1234",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "created_at": days_ago(10),
        "total_price": "49.99",
        "currency": "EUR",
        "line_items": [{"id": 5001, "title": "Lámpara LED", "quantity": 1, "price": "49.99"}],
    },
    "get_refundable_balance": {"captured": "49.99", "refunded": "0", "currency": "EUR"},
    "refund_partial": {"ok": True, "simulated": True},
}

_ORDER_DIGITAL: dict[str, Any] = {
    "get_order_by_name": {
        "found": True,
        "id": 2002,
        "name": "#1235",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "created_at": days_ago(5),
        "line_items": [
            {"id": 5002, "title": "Plantilla digital Notion", "quantity": 1, "price": "12.00"}
        ],
        "tags": "digital",
    },
    "get_returnable_order": _returnable(
        2002, "#1235", 5002, "Plantilla digital Notion", days_ago(4), ["digital"]
    ),
    "get_policies": [
        {
            "title": "Política de devolución",
            "url": "https://tienda-sim.myshopify.com/policies/refund-policy",
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
        "expected_outcome": (
            "El agente pide la devolución (L3) con el motivo 'talla' de la política, que queda "
            "pendiente de aprobación humana, y le explica al cliente que el equipo la "
            "confirmará, sin decir que el dinero ya vuelve."
        ),
        "mock_fixtures": {"shopify": _ORDER_IN_WINDOW, "returns_policy": _POLICY},
        "assertions": {
            "skills_called": ["shopify.start_return"],
            "skills_not_called": ["shopify.refund_partial"],
            "must_have_pending_approval": True,
        },
        "max_turns": 6,
    },
    {
        "id": "RE-02",
        "name": "RE-02: Devolución fuera de plazo",
        "description": (
            "Cliente quiere devolver un pedido entregado hace 52 días. El código rechaza la "
            "devolución por plazo y pasa el caso al equipo con la fecha límite."
        ),
        "aop_slug": "returns",
        "capabilities": [],
        "profile": "cooperativo",
        "goal": "Devolver pedido #1234 de hace 55 días",
        "initial_message": "Quiero devolver mi pedido #1234, lo compré hace un par de meses",
        "expected_outcome": (
            "El cliente lee que el plazo terminó y que su caso pasa al equipo; no se abre "
            "ninguna devolución."
        ),
        "mock_fixtures": {"shopify": _ORDER_OUT_OF_WINDOW, "returns_policy": _POLICY},
        "assertions": {
            "must_escalate": True,
            "escalation_reason_present": True,
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
        "description": (
            "Cliente quiere devolver un producto con la etiqueta 'digital', que la política "
            "excluye. El código lo rechaza y pasa el caso al equipo."
        ),
        "aop_slug": "returns",
        "capabilities": [],
        "profile": "cooperativo",
        "goal": "Devolver plantilla digital que no me sirve",
        "initial_message": "Quiero devolver la plantilla digital que compré, pedido #1235",
        "expected_outcome": (
            "El cliente lee que ese artículo no admite devolución y que su caso pasa al equipo."
        ),
        "mock_fixtures": {"shopify": _ORDER_DIGITAL, "returns_policy": _POLICY},
        "assertions": {
            "must_escalate": True,
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
        "mock_fixtures": {"shopify": _ORDER_IN_WINDOW, "returns_policy": _POLICY},
        "assertions": {
            "outcome_is": "resolved",
        },
        "max_turns": 8,
    },
    {
        "id": "RE-08",
        "name": "RE-08: Tienda sin política de devoluciones",
        "description": (
            "La tienda no ha configurado su política (ADR 0014): no hay valores por defecto. "
            "El código no abre la devolución y pasa el caso al equipo con la razón."
        ),
        "aop_slug": "returns",
        "capabilities": [],
        "profile": "cooperativo",
        "goal": "Devolver el pedido #1234 porque la talla no me queda bien",
        "initial_message": "Hola, quiero devolver mi pedido #1234 porque la talla no me queda bien",
        "expected_outcome": (
            "El agente no inventa plazos ni condiciones; el caso pasa al equipo sin abrir "
            "ninguna devolución."
        ),
        "mock_fixtures": {"shopify": _ORDER_IN_WINDOW, "returns_policy": None},
        "assertions": {
            "must_escalate": True,
            "escalation_reason_present": True,
        },
        "max_turns": 4,
    },
]
