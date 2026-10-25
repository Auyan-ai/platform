"""Construye el IntegrationContext de comercio de un tenant y resuelve su adapter.

Fuente única de la lógica sensible de cripto (descifrado + token exchange Shopify).
Lo usan tanto `load_tenant_context` (hot path del agente) como el endpoint de
approvals, que ejecuta skills L3 fuera del grafo. El endpoint /approve leía las
creds de `tenant_config.extra` (camino legacy) y armaba un SkillContext con kwargs
obsoletos → 500. Centralizar evita que ambos caminos diverjan.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apps.api.core.config import get_settings
from apps.api.db.queries import (
    get_integration_credentials_encrypted,
    get_primary_integration_for_kind,
)
from apps.api.integrations import shopify
from apps.api.integrations.base import IntegrationContext
from apps.api.integrations.commerce import CommerceAdapter
from apps.api.integrations.registry import IntegrationRegistry
from apps.api.services.integrations_crypto import decrypt_credentials, get_integration_crypto_key

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


async def build_commerce_integration_ctx(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    extra: dict[str, Any] | None = None,
) -> IntegrationContext | None:
    """Devuelve el IntegrationContext de commerce del tenant, o None si no hay.

    Prioriza `tenant_integrations` (creds cifradas + token exchange Shopify);
    cae a `tenant_config.extra` (legacy) si se pasa `extra` con shopify_domain/token.
    Debe llamarse con un `conn` ya dentro de su `tenant_scope`.
    """
    integration = await get_primary_integration_for_kind(conn, tenant_id=tenant_id, kind="commerce")
    if integration:
        encrypted = await get_integration_credentials_encrypted(
            conn, tenant_id=tenant_id, integration_id=integration.id
        )
        if encrypted:
            try:
                key = get_integration_crypto_key(get_settings())
                creds = json.loads(decrypt_credentials(encrypted, key).decode())
                config_jsonb = integration.config or {}

                # Shopify 2026 flow: si hay client_id/secret, resolver el access_token
                # corto (cache en memoria) antes de pasar al adapter, que espera
                # 'access_token' (no client_id/secret).
                if (
                    integration.provider == "shopify"
                    and creds.get("client_id")
                    and creds.get("client_secret")
                ):
                    access_token, _expires = await shopify.ensure_shopify_access_token(
                        tenant_id=tenant_id,
                        domain=creds["domain"],
                        client_id=creds["client_id"],
                        client_secret=creds["client_secret"],
                    )
                    creds = {"domain": creds["domain"], "access_token": access_token}

                return IntegrationContext(
                    tenant_id=tenant_id,
                    credentials=creds,
                    config=config_jsonb,
                    provider=integration.provider,
                )
            except Exception:
                logger.warning("commerce_integration_decrypt_failed tenant_id=%s", tenant_id)

    extra = extra or {}
    shopify_domain = extra.get("shopify_domain")
    shopify_token = extra.get("shopify_token")
    if shopify_domain and shopify_token:
        return IntegrationContext(
            tenant_id=tenant_id,
            credentials={"domain": shopify_domain, "token": shopify_token},
            config={},
            provider="shopify",
        )
    return None


def commerce_adapter(integration: IntegrationContext) -> CommerceAdapter:
    """El adapter registrado para el proveedor de la integración de comercio."""
    if integration.provider is None:
        raise ValueError("commerce_provider_missing")
    adapter_cls: type[CommerceAdapter] = IntegrationRegistry.get("commerce", integration.provider)
    return adapter_cls()
