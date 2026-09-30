"""Pseudonimización de PII para el audit log de skills.

Política (architecture-agent-v2.md § 11.3):
- Email       → sha256(value + salt)[:16] como "<email:XXXXXXXXXXXXXXXX>"
- Teléfono    → últimos 4 dígitos "***-1234"
- Nombre      → iniciales "J. P."
- Dirección   → "<dirección>" (la calle es PII; ciudad/provincia/país se conservan)
- Cód. postal → prefijo de 2 dígitos "28***" (en ES identifica provincia, no a la persona)
- IDs, números de pedido, textos libres → sin cambio (en el audit log; hacia
  observabilidad el texto libre sí se enmascara: ver `mask_free_text_pii`)

El hashing ocurre en Python para que el salt nunca aparezca en logs de Postgres.

Nota: esta es la copia FORENSE (skill_audit_log y pending_approvals.inputs_redacted).
El operador que aprueba una acción ve `inputs_raw` (su propio cliente, autorizado).
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
    "address1": "address",
    "address2": "address",
    "address": "address",
    "street": "address",
    "zip": "zip",
    "zip_code": "zip",
    "postal_code": "zip",
    "postcode": "zip",
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


def _redact_address(value: str) -> str:
    # La calle es PII directa; no dejamos rastro legible en la copia forense.
    return "<dirección>"


def _redact_zip(value: str) -> str:
    # En España el CP empieza por la provincia (2 dígitos): útil sin identificar.
    digits = re.sub(r"\D", "", str(value))
    if len(digits) >= 2:
        return f"{digits[:2]}***"
    return "***"


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
        elif pii_kind == "address":
            result[key] = _redact_address(value)
        elif pii_kind == "zip":
            result[key] = _redact_zip(value)
        else:
            result[key] = value
    return result


def hash_inputs(inputs: dict[str, Any]) -> str:
    """sha256 del JSON canónico de los inputs originales (para forense)."""
    canonical = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ─── Texto libre hacia observabilidad (LangSmith / Langfuse) ─────────────────
#
# El mensaje del cliente y la respuesta del agente viajan tal cual a un SaaS de
# terceros. Aquí no hay salt por tenant (es un camino síncrono sin DB): el email se
# reemplaza por un marcador sin hash y el teléfono conserva los últimos 4 dígitos.
# Números de pedido (#1429), importes e IDs cortos no se tocan.

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Teléfono: con prefijo internacional (+34 612 345 678) o 9 dígitos españoles que
# empiezan por 6/7/8/9, admitiendo separadores de espacio, punto o guion.
_PHONE_RE = re.compile(
    r"(?<![\w#])(?:\+\d{1,3}[\s.-]?(?:\d[\s.-]?){8,12}\d|[6-9](?:[\s.-]?\d){8})(?![\w])"
)


def mask_free_text_pii(text: str) -> str:
    """Enmascara emails y teléfonos en texto libre destinado a observabilidad."""
    masked = _EMAIL_RE.sub("<email>", text)
    return _PHONE_RE.sub(lambda m: _redact_phone(m.group(0)), masked)


def mask_pii_recursive(value: Any) -> Any:
    """`mask_free_text_pii` aplicado a todos los strings de una estructura JSON-like."""
    if isinstance(value, str):
        return mask_free_text_pii(value)
    if isinstance(value, dict):
        return {k: mask_pii_recursive(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_pii_recursive(v) for v in value]
    return value
