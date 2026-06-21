"""Endpoints de billing por resolución (Bloque 2).

- GET  /billing/usage         → uso del periodo actual (tenant_admin ve el suyo;
                                 super_admin con X-Tenant-Id ve el del cliente).
- PUT  /billing/subscription  → crea/edita el plan del tenant (super_admin only).

El cobro real (Stripe) se conecta después; estos endpoints exponen la MEDICIÓN.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from apps.api.core.errors import ValidationFailed
from apps.api.core.security import get_tenant_id, require_role
from apps.api.db.client import tenant_scope
from apps.api.db.models import BillingSubscription, BillingTier, BillingUsage
from apps.api.db.queries import upsert_billing_subscription
from apps.api.services.billing import compute_period_usage, tier_defaults
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

router = APIRouter(prefix="/billing", tags=["billing"])

TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]


class SubscriptionUpsertRequest(BaseModel):
    """Plan a aplicar. Para starter/growth/scale, floor/included/overage se toman del
    catálogo (BILLING_TIERS) salvo override explícito. `founding` no tiene defaults →
    los tres valores son obligatorios en el body."""

    tier: BillingTier
    floor_cents: int | None = Field(default=None, ge=0)
    included_resolutions: int | None = Field(default=None, ge=0)
    overage_cents: int | None = Field(default=None, ge=0)
    currency: str = "EUR"
    reopen_window_days: int = Field(default=7, ge=0)
    period_anchor_day: int = Field(default=1, ge=1, le=31)


@router.get("/usage", response_model=BillingUsage, summary="Uso del periodo actual")
async def get_usage(tenant_id: TenantIdDep) -> BillingUsage:
    async with tenant_scope(tenant_id) as conn:
        return await compute_period_usage(conn, tenant_id)


@router.put(
    "/subscription",
    response_model=BillingSubscription,
    summary="Crear o editar el plan del tenant (super_admin)",
    dependencies=[Depends(require_role("super_admin"))],
)
async def upsert_subscription(
    tenant_id: TenantIdDep,
    body: SubscriptionUpsertRequest,
) -> BillingSubscription:
    defaults = {} if body.tier == "founding" else tier_defaults(body.tier)
    floor_cents = body.floor_cents if body.floor_cents is not None else defaults.get("floor_cents")
    included = (
        body.included_resolutions
        if body.included_resolutions is not None
        else defaults.get("included_resolutions")
    )
    overage = (
        body.overage_cents if body.overage_cents is not None else defaults.get("overage_cents")
    )
    if floor_cents is None or included is None or overage is None:
        raise ValidationFailed(
            "tier 'founding' requiere floor_cents, included_resolutions y overage_cents explícitos",
            code="billing_founding_requires_explicit_values",
        )

    async with tenant_scope(tenant_id) as conn:
        return await upsert_billing_subscription(
            conn,
            tenant_id=tenant_id,
            tier=body.tier,
            floor_cents=floor_cents,
            included_resolutions=included,
            overage_cents=overage,
            currency=body.currency,
            reopen_window_days=body.reopen_window_days,
            period_anchor_day=body.period_anchor_day,
        )
