"""Scenarios DE-* — Default / preguntas generales (8 scenarios)."""

from __future__ import annotations

from typing import Any

_POLICIES: dict[str, Any] = {
    "get_policies": [
        {
            "title": "Política de envío",
            "body": (
                "Envíos estándar: 3-5 días hábiles. "
                "Envíos express: 1-2 días hábiles. "
                "Gratis en pedidos superiores a $50."
            ),
        },
        {
            "title": "Política de devolución",
            "body": "30 días desde la fecha de compra para devoluciones sin preguntas.",
        },
    ]
}

_PRODUCT_TALLA_M: dict[str, Any] = {
    "search_products": [
        {
            "id": 3001,
            "title": "Camiseta básica",
            "variants": [
                {"title": "S", "inventory_quantity": 12},
                {"title": "M", "inventory_quantity": 5},
                {"title": "L", "inventory_quantity": 0},
            ],
            "price": "19.99",
        }
    ],
    "get_shop_currency": "USD",
}

# Issue #265 (s78): tienda en USD y el agente dijo "100,95 €" deduciendo la moneda.
_PRODUCT_TIENDA_USD: dict[str, Any] = {
    "search_products": [
        {
            "id": 3101,
            "title": "Bolso Tote Piel",
            "status": "active",
            "variants": [{"title": "Default Title", "price": "100.95", "inventory_quantity": 4}],
        }
    ],
    "get_shop_currency": "USD",
}

# Tienda en EUR, cliente de UK que pagó en GBP (Shopify Markets).
_ORDER_TIENDA_EUR_PAGADO_GBP: dict[str, Any] = {
    "get_order_by_name": {
        "id": 4002,
        "name": "#1502",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
        "total_price": "52.00",
        "currency": "EUR",
        "presentment_currency": "GBP",
        "total_price_set": {
            "shop_money": {"amount": "52.00", "currency_code": "EUR"},
            "presentment_money": {"amount": "45.00", "currency_code": "GBP"},
        },
        "line_items": [
            {
                "id": 6002,
                "title": "Bolso Tote Piel",
                "quantity": 1,
                "price": "52.00",
                "price_set": {
                    "shop_money": {"amount": "52.00", "currency_code": "EUR"},
                    "presentment_money": {"amount": "45.00", "currency_code": "GBP"},
                },
            }
        ],
        "created_at": "2026-05-24T10:00:00Z",
        "email": "cliente@ejemplo.com",
    }
}

_ORDER_PRE_ENVIO: dict[str, Any] = {
    "get_order_by_name": {
        "found": True,
        "id": 4001,
        "order_number": "#1500",
        "financial_status": "paid",
        "fulfillment_status": "unfulfilled",
        "shipping_address": {
            "address1": "Calle Vieja 123",
            "city": "Madrid",
            "province": "Madrid",
            "country": "ES",
            "zip": "28001",
        },
        "line_items": [{"id": 6001, "title": "Zapatillas", "quantity": 1}],
        "created_at": "2026-05-24T10:00:00Z",
    },
    "update_shipping_address": {
        "id": 4001,
        "order_number": "#1500",
        "shipping_address": {
            "address1": "Calle Nueva 456",
            "city": "Madrid",
            "province": "Madrid",
            "country": "ES",
            "zip": "28001",
        },
    },
}


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "DE-01",
        "name": "DE-01: Tiempo de envío estándar",
        "description": "Cliente pregunta cuánto tarda el envío sin pedido específico. El agente responde desde KB.",
        "aop_slug": "default",
        "profile": "cooperativo",
        "goal": "Saber cuántos días tarda el envío estándar",
        "initial_message": "Hola, ¿cuánto tarda el envío normalmente?",
        "expected_outcome": "El agente informa el tiempo de envío sin llamar skills de pedido.",
        "mock_fixtures": {"shopify": _POLICIES},
        "assertions": {
            "response_contains": ["días"],
            "skills_not_called": ["shopify.get_order_status"],
        },
        "max_turns": 3,
    },
    {
        "id": "DE-02",
        "name": "DE-02: Garantía de producto",
        "description": "Cliente pregunta sobre garantía de un producto. El agente responde desde KB en máximo 2 turnos.",
        "aop_slug": "default",
        "profile": "cooperativo",
        "goal": "Saber qué garantía tiene el producto que quiero comprar",
        "initial_message": "¿Cuánto tiempo de garantía tienen sus productos?",
        "expected_outcome": "El agente responde sobre la política de garantía desde la knowledge base.",
        "mock_fixtures": {"shopify": _POLICIES},
        "assertions": {
            "max_turns": 2,
        },
        "max_turns": 4,
    },
    {
        "id": "DE-03",
        "name": "DE-03: Pregunta fuera de alcance",
        "description": "El cliente pregunta algo completamente fuera del alcance (ej: soporte técnico de otro producto). El agente escala.",
        "aop_slug": "default",
        "profile": "cooperativo",
        "goal": "Obtener soporte técnico para un televisor de otra marca",
        "initial_message": "Hola, necesito ayuda con el televisor Samsung que compré hace un año, no enciende",
        "expected_outcome": "El agente explica que no puede ayudar con eso y escala.",
        "mock_fixtures": {"shopify": {}},
        "assertions": {
            "must_escalate": True,
            "response_not_contains": ["garantía de samsung", "samsung te puede"],
        },
        "max_turns": 4,
    },
    {
        "id": "DE-04",
        "name": "DE-04: Cambiar dirección antes de envío",
        "description": "Cliente quiere cambiar dirección del pedido #1500 que aún no salió. El agente ejecuta update_shipping_address.",
        "aop_slug": "default",
        "profile": "cooperativo",
        "goal": "Cambiar la dirección de envío del pedido #1500",
        "initial_message": (
            "Hola, cometí un error con la dirección del pedido #1500. "
            "¿Puedo cambiarla? La nueva es Calle Nueva 456, Madrid"
        ),
        "expected_outcome": "El agente actualiza la dirección de envío del pedido.",
        "mock_fixtures": {"shopify": _ORDER_PRE_ENVIO},
        "assertions": {
            "skills_called": ["shopify.update_shipping_address"],
        },
        "max_turns": 5,
    },
    {
        "id": "DE-05",
        "name": "DE-05: Disponibilidad de talla M",
        "description": "Cliente pregunta si hay talla M de una camiseta. El agente busca el producto.",
        "aop_slug": "default",
        "profile": "cooperativo",
        "goal": "Saber si hay camiseta básica en talla M",
        "initial_message": "¿Tienen la camiseta básica en talla M?",
        "expected_outcome": "El agente confirma disponibilidad de talla M con el stock.",
        "mock_fixtures": {"shopify": _PRODUCT_TALLA_M},
        "assertions": {
            "skills_called": ["shopify.get_product_info"],
            "response_contains": ["M"],
        },
        "max_turns": 4,
    },
    {
        "id": "DE-06",
        "name": "DE-06: Solo 'hola' — cliente abandona pronto",
        "description": "El cliente solo dice hola y no elabora. El agente pregunta clarificación sin llamar skills operativas.",
        "aop_slug": "default",
        "profile": "abandona_pronto",
        "goal": "Escribir hola y no dar más información",
        "initial_message": "Hola",
        "expected_outcome": "El agente saluda y pide en qué puede ayudar sin consultar ni modificar pedidos.",
        "mock_fixtures": {"shopify": {}},
        "assertions": {
            "skills_not_called": [
                "shopify.get_order_status",
                "shopify.cancel_order",
                "shopify.refund_partial",
            ],
        },
        "max_turns": 4,
    },
    {
        "id": "DE-07",
        "name": "DE-07: Precio de producto en la moneda de la tienda (USD)",
        "description": (
            "Issue #265: la tienda cobra en USD. El agente da el precio en dólares y no "
            "deduce euros por el idioma o el país del cliente."
        ),
        "aop_slug": "default",
        "profile": "cooperativo",
        "goal": "Saber cuánto cuesta el Bolso Tote Piel",
        "initial_message": "Hola, ¿cuánto cuesta el Bolso Tote Piel?",
        "expected_outcome": "El agente da el precio 100.95 en dólares (USD), nunca en euros.",
        "mock_fixtures": {"shopify": _PRODUCT_TIENDA_USD},
        "assertions": {
            "skills_called": ["shopify.get_product_info"],
            "response_contains": ["100"],
            "response_not_contains": ["€", "euro"],
        },
        "max_turns": 3,
    },
    {
        "id": "DE-08",
        "name": "DE-08: Importe del pedido en la moneda en que pagó el cliente (GBP)",
        "description": (
            "Issue #265: tienda en EUR, el cliente pagó en GBP. El agente dice lo que pagó "
            "en libras (45.00 GBP), no el importe de la tienda en euros."
        ),
        "aop_slug": "default",
        "profile": "cooperativo",
        "goal": "Saber cuánto pagué por mi pedido #1502",
        "initial_message": "Hola, ¿cuánto pagué en total por mi pedido #1502?",
        "expected_outcome": "El agente dice que pagó 45.00 GBP (libras), sin dar el importe en euros.",
        "mock_fixtures": {"shopify": _ORDER_TIENDA_EUR_PAGADO_GBP},
        "assertions": {
            "skills_called": ["shopify.get_order_status"],
            "response_contains": ["45"],
            "response_not_contains": ["€", "euro", "52"],
        },
        "max_turns": 3,
    },
]
