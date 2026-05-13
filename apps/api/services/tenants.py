import uuid

from fastapi import HTTPException, status
from supabase import Client

from db import queries
from db.models import Tenant, TenantConfiguration


async def get_tenant(db: Client, tenant_id: uuid.UUID) -> Tenant:
    data = await queries.get_tenant_by_id(db, tenant_id)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return Tenant(**data)


async def get_tenant_config(db: Client, tenant_id: uuid.UUID) -> TenantConfiguration:
    data = await queries.get_tenant_config(db, tenant_id)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant configuration not found")
    return TenantConfiguration(**data)
