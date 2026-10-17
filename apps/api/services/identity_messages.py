"""Textos fijos de la verificación de identidad (ADR 0013 §10). Sin LLM, trato de tú.

El catálogo por idioma vive en `services/fixed_texts.py`. Cada tenant puede sobrescribirlos
en `tenant_facts.identity_messages` (clave → texto, o clave → {idioma: texto}).
Ningún texto dice si un pedido existe ni qué contacto tiene.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from apps.api.services.fixed_texts import FALLBACK_LANGUAGE, fixed_text

MessageKey = Literal["guest_not_verified", "guest_locked", "guest_paused", "commerce_unavailable"]


def identity_message(
    key: MessageKey,
    tenant_facts: Mapping[str, Any] | None = None,
    *,
    language: str | None = None,
    tenant_default: str = FALLBACK_LANGUAGE,
) -> str:
    """Texto fijo de `key` en `language`; el del tenant si lo define."""
    overrides = (tenant_facts or {}).get("identity_messages")
    return fixed_text(
        key,
        language,
        tenant_default=tenant_default,
        overrides=overrides if isinstance(overrides, Mapping) else None,
    )
