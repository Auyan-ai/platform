"""Tenants de demo (ADR 0015 §5): alta desde una URL, modo del turno, exclusiones y caducidad.

Una demo es un tenant con `origin = 'demo'`, sin admin ni canales y con skills solo L1.
Se crea con `scaffold_tenant` (la parte del alta que no depende del admin). Nunca recibe
credenciales de comercio: el turno usa el catálogo público de la tienda de origen.
"""

from __future__ import annotations

import logging
import secrets
import string
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
from apps.api.aops.canonical import CANONICAL_TOOL_PERMISSIONS
from apps.api.core.config import Settings
from apps.api.db.models import Tenant
from apps.api.db.queries import upsert_tool_permission
from apps.api.db.site_ingestions import enqueue_site_ingestion
from apps.api.integrations.demo_catalog import normalize_domain
from apps.api.services.tenant_provisioning import scaffold_tenant
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Las demos solo leen: cualquier otra skill queda apagada.
DEMO_ALLOWED_SKILLS: frozenset[str] = frozenset(
    {
        "shopify.get_order_status",
        "shopify.list_my_orders",
        "shopify.get_product_info",
        "shopify.get_shop_policies",
    }
)

_SLUG_SUFFIX_ALPHABET = string.ascii_lowercase + string.digits
_SLUG_SUFFIX_LENGTH = 6
_SLUG_SHOP_MAX = 30
_SLUG_ATTEMPTS = 5
_SLUG_UNIQUE_CONSTRAINT = "tenants_slug_key"
_SECOND_LEVEL_LABELS = frozenset({"co", "com", "org", "net", "gov", "edu"})


class DemoSlugExhaustedError(Exception):
    """Todos los sufijos aleatorios probados chocaron con un slug existente."""


def _shop_label(domain: str) -> str:
    """Etiqueta de la tienda: el dominio sin `www.` ni TLD (`www.thinkingmu.com` → `thinkingmu`)."""
    labels = [label for label in domain.split(".") if label]
    if labels and labels[0] == "www":
        labels = labels[1:]
    if len(labels) > 1:
        labels = labels[:-1]
    if len(labels) > 1 and labels[-1] in _SECOND_LEVEL_LABELS:
        labels = labels[:-1]
    return labels[-1] if labels else domain


def company_name_from_domain(domain: str) -> str:
    """Nombre provisional de la demo: la etiqueta de la tienda en mayúsculas iniciales."""
    return _shop_label(domain).replace("-", " ").title()


def demo_slug(domain: str) -> str:
    """`demo-<tienda>-<6 caracteres aleatorios>`. Cumple `^[a-z][a-z0-9-]{1,49}$`."""
    shop = "".join(c if c.isalnum() else "-" for c in _shop_label(domain).lower())
    shop = shop.strip("-")[:_SLUG_SHOP_MAX].strip("-") or "tienda"
    suffix = "".join(secrets.choice(_SLUG_SUFFIX_ALPHABET) for _ in range(_SLUG_SUFFIX_LENGTH))
    return f"demo-{shop}-{suffix}"


async def create_demo_tenant(
    conn: asyncpg.Connection,
    *,
    settings: Settings,
    url: str,
    now: datetime | None = None,
) -> Tenant:
    """Crea la demo de la tienda `url` y la deja lista para el turno. Todo o nada.

    Raises:
        ValueError: `url` no es un dominio público válido (`normalize_domain`).
        DemoSlugExhaustedError: cinco sufijos seguidos chocaron con un slug existente.
    """
    domain = normalize_domain(url)
    created_at = now or datetime.now(UTC)
    expires_at = created_at + timedelta(days=settings.demo_ttl_days)

    for _ in range(_SLUG_ATTEMPTS):
        slug = demo_slug(domain)
        try:
            async with conn.transaction():
                tenant = await scaffold_tenant(
                    conn,
                    tenant_id=uuid4(),
                    slug=slug,
                    company_name=company_name_from_domain(domain),
                    plan_tier="trial",
                    lifecycle_state="initial",
                    origin="demo",
                    demo_expires_at=expires_at,
                    demo_source_url=f"https://{domain}",
                )
                await _restrict_to_read_only_skills(conn, tenant)
        except asyncpg.UniqueViolationError as exc:
            if exc.constraint_name != _SLUG_UNIQUE_CONSTRAINT:
                raise
            logger.info("demo_slug_collision slug=%s", slug)
            continue
        logger.info(
            "demo_tenant_created tenant_id=%s slug=%s domain=%s expires_at=%s",
            tenant.id,
            tenant.slug,
            domain,
            expires_at.isoformat(),
        )
        return tenant
    raise DemoSlugExhaustedError(domain)


async def _restrict_to_read_only_skills(conn: asyncpg.Connection, tenant: Tenant) -> None:
    for perm in CANONICAL_TOOL_PERMISSIONS:
        if perm["skill_slug"] in DEMO_ALLOWED_SKILLS:
            continue
        await upsert_tool_permission(
            conn,
            tenant_id=tenant.id,
            skill_slug=perm["skill_slug"],
            is_enabled=False,
            human_approval_required=True,
        )


async def start_demo_ingestion(
    conn: asyncpg.Connection, tenant: Tenant, *, requested_by: UUID | None
) -> UUID | None:
    """Encola la ingesta del sitio de la demo (ADR 0015 §2). El worker del API la procesa.

    Aplicar lo leído como `applied_unconfirmed` llega con los borradores (PR 5): hasta entonces
    las fuentes quedan como submissions pendientes de la demo."""
    if not tenant.demo_source_url:
        logger.error("demo_ingestion_without_source_url tenant_id=%s", tenant.id)
        return None
    ingestion_id = await enqueue_site_ingestion(
        conn,
        tenant_id=tenant.id,
        root_url=f"https://{normalize_domain(tenant.demo_source_url)}",
        requested_by=requested_by,
    )
    logger.info(
        "demo_ingestion_queued tenant_id=%s ingestion_id=%s source_url=%s",
        tenant.id,
        ingestion_id,
        tenant.demo_source_url,
    )
    return ingestion_id


def demo_state_overrides(
    tenant: Tenant, *, scripted_commerce: bool = False, platform: str | None = None
) -> dict[str, object]:
    """Campos del estado del turno que fija el origen del tenant.

    Una demo nunca usa comercio `live`: lee el catálogo público de su tienda, también en
    "Probar agente". Solo un escenario del simulador con fixtures de Shopify
    (`scripted_commerce`) conserva el mock, porque sus respuestas están guionizadas.
    Un tenant cliente no cambia nada.
    """
    if tenant.origin != "demo":
        return {}
    if scripted_commerce:
        return {"commerce_integration_ctx": None}
    domain = normalize_domain(tenant.demo_source_url or "")
    overrides: dict[str, object] = {
        "commerce_integration_ctx": None,
        "commerce_mode": "demo_catalog",
        "demo_catalog_domain": domain,
    }
    if platform:
        overrides["demo_catalog_platform"] = platform
    return overrides


def reject_demo_intake(tenant: Tenant | None, *, source: str) -> None:
    """Corta el intake de webhooks hacia una demo, con el motivo en el log."""
    if tenant is None or tenant.origin != "demo":
        return
    logger.warning(
        "intake_rejected_demo_tenant source=%s tenant_id=%s slug=%s",
        source,
        tenant.id,
        tenant.slug,
    )
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail="tenant_is_demo")
