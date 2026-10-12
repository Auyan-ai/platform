"""Textos fijos de la verificación de identidad (ADR 0013 §10). Sin LLM, trato de tú.

Cada tenant puede sobrescribirlos en `tenant_facts.identity_messages` (clave → texto).
Ningún texto dice si un pedido existe ni qué contacto tiene.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

MessageKey = Literal["guest_not_verified", "guest_locked", "guest_paused"]

DEFAULT_MESSAGES: dict[MessageKey, str] = {
    "guest_not_verified": (
        "No he podido verificar esos datos. Revisa el número de pedido y el email o "
        "teléfono con el que compraste."
    ),
    "guest_locked": (
        "Por seguridad no puedo hacer más comprobaciones en esta conversación. Si quieres, "
        "paso tu caso a una persona del equipo para que te ayude."
    ),
    "guest_paused": (
        "Ahora mismo no puedo verificar pedidos. Inténtalo de nuevo en unos minutos o dime "
        "si prefieres que pase tu caso a una persona del equipo."
    ),
}


def identity_message(key: MessageKey, tenant_facts: Mapping[str, Any] | None = None) -> str:
    """Texto fijo de `key`; el del tenant si lo define como texto no vacío."""
    overrides = (tenant_facts or {}).get("identity_messages")
    if isinstance(overrides, Mapping):
        custom = overrides.get(key)
        if isinstance(custom, str) and custom.strip():
            return custom.strip()
    return DEFAULT_MESSAGES[key]
