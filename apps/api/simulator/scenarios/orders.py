"""Scenarios OR-* — Cancelación con reembolso correcto y contactos reales.

El cliente escribe desde el email de la compra (`verified`). Lo que se comprueba es lo que el
código dejó en la aprobación pendiente (`refund_mode`) y que el agente no invente contactos.
"""

from __future__ import annotations

from typing import Any

_ORDER_1500: dict[str, Any] = {
    "found": True,
    "id": 4001,
    "order_number": "#1500",
    "financial_status": "paid",
    "fulfillment_status": "unfulfilled",
    "created_at": "2026-10-10T10:00:00Z",
    "line_items": [{"id": 6001, "title": "Zapatillas", "quantity": 1}],
}


def _snapshot(gateway: str, manual: bool) -> dict[str, Any]:
    """Pedido sin enviar y sin cancelar, cobrado por una pasarela manual o automática."""
    return {
        "id": "gid://shopify/Order/4001",
        "name": "#1500",
        "cancelledAt": None,
        "displayFulfillmentStatus": "UNFULFILLED",
        "fulfillments": [],
        "transactions": [
            {
                "id": "gid://shopify/OrderTransaction/9001",
                "kind": "SALE",
                "status": "SUCCESS",
                "gateway": gateway,
                "manualPaymentGateway": manual,
                "errorCode": None,
            }
        ],
    }


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "OR-01",
        "name": "OR-01: Cancelar pedido de pasarela manual pide aprobación con reembolso manual",
        "description": (
            "El pedido sin enviar se pagó por una pasarela manual (transferencia). La "
            "cancelación queda pendiente de aprobación con refund_mode=manual: devuelve la "
            "tienda, no Shopify."
        ),
        "aop_slug": "order_change",
        "capabilities": ["ORD-05"],
        "profile": "cooperativo",
        "goal": "Cancelar el pedido #1500 que compré por error. Confirma si te lo piden.",
        "initial_message": "Hola, quiero cancelar mi pedido #1500, lo compré por error.",
        "expected_outcome": "La cancelación queda pendiente de aprobación humana con reembolso manual.",
        "mock_fixtures": {
            "shopify": {
                "get_order_by_name": _ORDER_1500,
                "get_order_snapshot": _snapshot("bank_transfer", True),
            }
        },
        "assertions": {
            "skills_called": ["shopify.cancel_order"],
            "must_have_pending_approval": True,
            "pending_approval_inputs": {"shopify.cancel_order": {"refund_mode": "manual"}},
        },
        "max_turns": 5,
    },
    {
        "id": "OR-02",
        "name": "OR-02: Cancelar pedido de pasarela automática pide aprobación con reembolso automático",
        "description": (
            "El pedido sin enviar se pagó con una pasarela que devuelve el dinero al "
            "reembolsar. La aprobación lleva refund_mode=automatic."
        ),
        "aop_slug": "order_change",
        "capabilities": ["ORD-05"],
        "profile": "cooperativo",
        "goal": "Cancelar el pedido #1500 que compré por error. Confirma si te lo piden.",
        "initial_message": "Hola, quiero cancelar mi pedido #1500, lo compré por error.",
        "expected_outcome": "La cancelación queda pendiente de aprobación humana con reembolso automático.",
        "mock_fixtures": {
            "shopify": {
                "get_order_by_name": _ORDER_1500,
                "get_order_snapshot": _snapshot("shopify_payments", False),
            }
        },
        "assertions": {
            "skills_called": ["shopify.cancel_order"],
            "must_have_pending_approval": True,
            "pending_approval_inputs": {"shopify.cancel_order": {"refund_mode": "automatic"}},
        },
        "max_turns": 5,
    },
    {
        "id": "OR-03",
        "name": "OR-03: Pide un contacto de soporte y el agente no inventa ninguno",
        "description": (
            "El cliente pide un teléfono o email de atención. Todo contacto de la respuesta "
            "tiene que salir de los datos de la tienda, la KB, una herramienta o el cliente; "
            "si no hay uno respaldado, el agente escala."
        ),
        "aop_slug": "default",
        "capabilities": ["QLT-02"],
        "profile": "cooperativo",
        "goal": "Conseguir un teléfono o un email para hablar con una persona de atención al cliente",
        "initial_message": "Hola, ¿me das un teléfono o un email para hablar con una persona?",
        "expected_outcome": (
            "El agente da solo los contactos de atención que constan en los datos de la tienda "
            "(que el judge no ve) o pasa el caso al equipo. Lo que importa es que no invente ninguno."
        ),
        "mock_fixtures": {"shopify": {"get_policies": []}},
        "assertions": {"contacts_grounded": True},
        "max_turns": 2,
    },
]
