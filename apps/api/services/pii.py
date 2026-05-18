"""Pseudonimización de PII para el audit log de skills.

Política (architecture-agent-v2.md § 11.3):
- Email       → sha256(value + salt)[:16] como "<email:XXXXXXXXXXXXXXXX>"
- Teléfono    → últimos 4 dígitos "***-1234"
- Nombre      → iniciales "J. P."
- IDs, números de pedido, textos libres → sin cambio

El hashing ocurre en Python para que el salt nunca aparezca en logs de Postgres.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# Campos cuyo nombre indica PII, mapeados a su tipo de redacción.
_PII_FIELDS: dict[str, str] = {
    "email": "email",
    "customer_email": "email",
    "from_email": "email",
    "to_email": "email",
    "phone": "phone",
    "phone_number": "phone",
    "mobile": "phone",
    "name": "name",
    "customer_name": "name",
    "first_name": "name",
    "last_name": "name",
    "full_name": "name",
    "contact_name": "name",
}


def _redact_email(value: str, salt: str) -> str:
    digest = hashlib.sha256(f"{value}{salt}".encode()).hexdigest()[:16]
    return f"<email:{digest}>"


def _redact_phone(value: str) -> str:
    digits = re.sub(r"\D", "", str(value))
    if len(digits) >= 4:
        return f"***-{digits[-4:]}"
    return "***"


def _redact_name(value: str) -> str:
    parts = str(value).split()
    return " ".join(f"{p[0].upper()}." for p in parts if p)


def redact_inputs(inputs: dict[str, Any], salt: str) -> dict[str, Any]:
    """Devuelve una copia del dict con los campos PII pseudonimizados."""
    result: dict[str, Any] = {}
    for key, value in inputs.items():
        pii_kind = _PII_FIELDS.get(key.lower())
        if not isinstance(value, str):
            result[key] = value
            continue
        if pii_kind == "email":
            result[key] = _redact_email(value, salt)
        elif pii_kind == "phone":
            result[key] = _redact_phone(value)
        elif pii_kind == "name":
            result[key] = _redact_name(value)
        else:
            result[key] = value
    return result


def hash_inputs(inputs: dict[str, Any]) -> str:
    """sha256 del JSON canónico de los inputs originales (para forense)."""
    canonical = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
