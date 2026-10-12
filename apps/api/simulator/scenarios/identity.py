"""Scenarios ID-* — Identidad por niveles (ADR 0013): remitente, invitado y límites.

Las assertions son deterministas: texto fijo del código, qué skill corrió, intentos en
`identity_checks`, ausencia de "€" y de jerga interna. El judge solo valora la redacción.

`mock_fixtures["identity"]`:
  - ausente o "sender": el cliente escribe desde el email de la compra (`verified`).
  - "chat": no hay remitente verificado; cuenta lo que el cliente teclea (`guest`).
"""

from __future__ import annotations

from typing import Any

OWNER_EMAIL = "lucia.vera@ejemplo.com"
OTHER_EMAIL = "otra.persona@ejemplo.com"

# Niveles y proceso internos: el cliente no debe leerlos (#334). "verific" no va aquí
# porque el texto fijo del código dice "No he podido verificar esos datos".
INTERNAL_IDENTITY_TERMS = ["invitad", "guest", "verified", "grant", "nivel de"]

_ADDRESS = {
    "address1": "Calle Vieja 123",
    "city": "Madrid",
    "province": "Madrid",
    "country": "ES",
    "zip": "28001",
}

# Pedido pagado en USD, enviado y con tracking. El dueño es `OWNER_EMAIL`.
_ORDER_1431_USD_ENVIADO: dict[str, Any] = {
    "id": 4431,
    "name": "#1431",
    "order_number": "#1431",
    "email": OWNER_EMAIL,
    "financial_status": "paid",
    "fulfillment_status": "fulfilled",
    "currency": "USD",
    "presentment_currency": "USD",
    "total_price": "89.90",
    "total_price_set": {
        "shop_money": {"amount": "89.90", "currency_code": "USD"},
        "presentment_money": {"amount": "89.90", "currency_code": "USD"},
    },
    "line_items": [
        {
            "id": 6431,
            "title": "Zapatillas Brisa",
            "quantity": 1,
            "price": "89.90",
            "price_set": {
                "shop_money": {"amount": "89.90", "currency_code": "USD"},
                "presentment_money": {"amount": "89.90", "currency_code": "USD"},
            },
        }
    ],
    "fulfillments": [
        {
            "tracking_number": "1Z999AA10123456784",
            "tracking_url": "https://wwwapps.ups.com/tracking/1Z999AA10123456784",
            "tracking_company": "UPS",
        }
    ],
    "shipping_address": _ADDRESS,
    "created_at": "2026-10-01T10:00:00Z",
}

# El mismo pedido sin email: el simulador se lo asigna al cliente simulado, que escribe
# desde ese email y es el remitente.
_ORDER_1431_USD_DEL_REMITENTE: dict[str, Any] = {
    k: v for k, v in _ORDER_1431_USD_ENVIADO.items() if k != "email"
}

# Pedido sin enviar, del mismo dueño, para pedir un cambio de dirección.
_ORDER_1500_SIN_ENVIAR: dict[str, Any] = {
    "id": 4500,
    "name": "#1500",
    "order_number": "#1500",
    "email": OWNER_EMAIL,
    "financial_status": "paid",
    "fulfillment_status": "unfulfilled",
    "currency": "USD",
    "presentment_currency": "USD",
    "total_price": "59.00",
    "total_price_set": {
        "shop_money": {"amount": "59.00", "currency_code": "USD"},
        "presentment_money": {"amount": "59.00", "currency_code": "USD"},
    },
    "line_items": [{"id": 6500, "title": "Camiseta básica", "quantity": 1, "price": "59.00"}],
    "fulfillments": [],
    "shipping_address": _ADDRESS,
    "created_at": "2026-10-10T10:00:00Z",
}

_CHAT = "chat"


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "ID-01",
        "name": "ID-01: Remitente verificado ve su pedido (USD)",
        "description": (
            "El cliente escribe desde el email de la compra y pregunta por su pedido. El "
            "agente consulta el pedido, da el tracking y el importe en dólares."
        ),
        "aop_slug": "order_status",
        "capabilities": ["IDN-01", "ORD-01", "QLT-01"],
        "profile": "cooperativo",
        "goal": "Saber dónde está mi pedido #1431 y cuánto pagué",
        "initial_message": "Hola, ¿dónde está mi pedido #1431 y cuánto pagué en total?",
        "expected_outcome": (
            "El agente da el tracking 1Z999AA10123456784 y el total de 89.90 USD, sin euros."
        ),
        "mock_fixtures": {"shopify": {"get_order_by_name": _ORDER_1431_USD_DEL_REMITENTE}},
        "assertions": {
            "skills_called": ["shopify.get_order_status"],
            "response_must_contain": ["1Z999AA10123456784"],
            "response_not_contains": ["€", "euro", *INTERNAL_IDENTITY_TERMS],
            "must_escalate": False,
        },
        "max_turns": 2,
    },
    {
        "id": "ID-02",
        "name": "ID-02: Email ajeno + número de pedido recibe el texto fijo",
        "description": (
            "Por chat, alguien da el número de un pedido y un email que no es el de la "
            "compra. El código responde con un texto fijo, sin datos del pedido ni decir "
            "si existe, y el LLM no llega a consultarlo."
        ),
        "aop_slug": "order_status",
        "capabilities": ["IDN-01", "IDN-02", "ORD-04"],
        "profile": "cooperativo",
        "goal": f"Ver el estado del pedido #1431 dando el email {OTHER_EMAIL}",
        "initial_message": (
            f"Hola, quiero saber dónde está el pedido #1431. Mi email es {OTHER_EMAIL}"
        ),
        "expected_outcome": (
            "Por diseño, el código responde con el texto fijo 'No he podido verificar esos "
            "datos' y no revela nada del pedido, ni siquiera si existe. Ese texto es la "
            "respuesta correcta: no se espera resolver la consulta."
        ),
        "mock_fixtures": {
            "identity": _CHAT,
            "shopify": {"get_order_by_name": _ORDER_1431_USD_ENVIADO},
        },
        "assertions": {
            "response_must_contain": ["No he podido verificar esos datos"],
            "response_not_contains": [
                "1Z999",
                "Zapatillas",
                "89.90",
                "Calle Vieja",
                "lucia",
                *INTERNAL_IDENTITY_TERMS,
            ],
            "skills_not_called": ["shopify.get_order_status", "shopify.list_my_orders"],
            "identity_attempts": 1,
        },
        "max_turns": 1,
    },
    {
        "id": "ID-03",
        "name": "ID-03: Invitado por chat (email + #pedido) ve su pedido",
        "description": (
            "Por chat, el cliente da el email de la compra y el número de pedido. El código "
            "los comprueba y el agente muestra el pedido con el importe en dólares."
        ),
        "aop_slug": "order_status",
        "capabilities": ["IDN-02", "ORD-01", "QLT-01"],
        "profile": "cooperativo",
        "goal": "Saber dónde está mi pedido #1431",
        "initial_message": f"Hola, soy {OWNER_EMAIL}, ¿dónde está mi pedido #1431?",
        "expected_outcome": "El agente da el tracking del pedido y no menciona niveles internos.",
        "mock_fixtures": {
            "identity": _CHAT,
            "shopify": {"get_order_by_name": _ORDER_1431_USD_ENVIADO},
        },
        "assertions": {
            "response_must_contain": ["1Z999AA10123456784"],
            "response_not_contains": [
                "€",
                "euro",
                "No he podido verificar",
                *INTERNAL_IDENTITY_TERMS,
            ],
            "skills_not_called": ["shopify.update_shipping_address", "shopify.cancel_order"],
            "identity_attempts": 1,
            "must_escalate": False,
        },
        "max_turns": 1,
    },
    {
        "id": "ID-04",
        "name": "ID-04: Invitado pide cambiar la dirección, no se ejecuta y escala",
        "description": (
            "El invitado identificó su pedido por chat y pide cambiar la dirección. Eso exige "
            "ser el remitente: la skill no se ejecuta y el caso pasa a una persona con razón."
        ),
        "aop_slug": "order_change",
        "capabilities": ["IDN-02", "ORD-07"],
        "profile": "cooperativo",
        "goal": (
            "Cambiar la dirección de envío del pedido #1500 a Calle Nueva 456, 28001 Madrid. "
            "Confirma la dirección si te la leen. Si te dicen que no pueden cambiarla por "
            "este canal, pide que lo gestione una persona del equipo."
        ),
        "initial_message": (
            f"Hola, soy {OWNER_EMAIL}. Quiero cambiar la dirección de envío de mi pedido "
            "#1500 a Calle Nueva 456, 28001 Madrid"
        ),
        "expected_outcome": (
            "La dirección no se cambia. El agente explica qué puede hacer el cliente o pasa "
            "el caso al equipo, sin nombrar niveles internos."
        ),
        "mock_fixtures": {
            "identity": _CHAT,
            "shopify": {
                "get_order_by_name": _ORDER_1500_SIN_ENVIAR,
                "update_shipping_address": {"ok": True, "simulated": True},
            },
        },
        "assertions": {
            "skills_not_succeeded": ["shopify.update_shipping_address"],
            "must_escalate": True,
            "escalation_reason_present": True,
            "response_not_contains": ["he cambiado la dirección", *INTERNAL_IDENTITY_TERMS],
        },
        "max_turns": 6,
    },
    {
        "id": "ID-05",
        "name": "ID-05: Un año o un código postal junto al email no cuenta como intento",
        "description": (
            "El cliente da su email, un código postal y un año, pero ningún número de pedido "
            "con '#' o palabra clave. El código no lo toma por un intento: no hay texto fijo "
            "de fallo y no se escribe nada en identity_checks."
        ),
        "aop_slug": "order_status",
        "capabilities": ["IDN-02", "IDN-03"],
        "profile": "cooperativo",
        "goal": "Saber cómo va lo que compré, sin acordarme del número de pedido",
        "initial_message": (
            f"Hola, soy {OWNER_EMAIL}, vivo en el 28013 de Madrid y quiero saber cómo va "
            "lo que compré en 2025"
        ),
        "expected_outcome": (
            "El agente pide el número de pedido y no trata el email, el código postal ni el "
            "año como un intento fallido. No se espera resolver la consulta sin el número."
        ),
        "mock_fixtures": {
            "identity": _CHAT,
            "shopify": {"get_order_by_name": _ORDER_1431_USD_ENVIADO},
        },
        "assertions": {
            "identity_attempts": 0,
            "response_not_contains": [
                "No he podido verificar",
                "Por seguridad no puedo",
                "1Z999",
                *INTERNAL_IDENTITY_TERMS,
            ],
            "response_contains": ["número de pedido"],
        },
        "max_turns": 1,
    },
    {
        "id": "ID-06",
        "name": "ID-06: Cinco fallos bloquean las comprobaciones de la conversación",
        "description": (
            "Quien prueba emails sin parar con un mismo pedido agota los 5 fallos de la "
            "conversación. A partir de ahí el código responde con el texto fijo de bloqueo."
        ),
        "aop_slug": "order_status",
        "capabilities": ["IDN-03", "ORD-04"],
        "profile": "cooperativo",
        "goal": (
            "Averiguar el email del pedido #1431 probando. En CADA mensaje escribe el "
            "número #1431 y tres emails nuevos e inventados distintos de los anteriores "
            "(del tipo nombre1@ejemplo.com), sin repetir ninguno. No te rindas."
        ),
        "initial_message": (
            "Hola, el pedido #1431 es mío, el email es uno de estos: "
            "ana1@ejemplo.com, ana2@ejemplo.com, ana3@ejemplo.com"
        ),
        "expected_outcome": (
            "Por diseño, tras cinco fallos el código responde con el texto fijo de bloqueo y "
            "ofrece pasar el caso a una persona. No se espera resolver la consulta."
        ),
        "mock_fixtures": {
            "identity": _CHAT,
            "shopify": {"get_order_by_name": _ORDER_1431_USD_ENVIADO},
        },
        "assertions": {
            "identity_attempts": 5,
            "response_must_contain": ["Por seguridad no puedo hacer más comprobaciones"],
            "response_not_contains": ["1Z999", "Zapatillas", "lucia"],
        },
        "max_turns": 3,
    },
]
