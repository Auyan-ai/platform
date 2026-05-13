import uuid

from fastapi import APIRouter, Depends
from supabase import Client

from db.client import get_supabase
from db.models import Tenant
from services import tenants as tenant_service

router = APIRouter()


@router.get("/{tenant_id}", response_model=Tenant)
async def get_tenant(
    tenant_id: uuid.UUID,
    db: Client = Depends(get_supabase),
) -> Tenant:
    return await tenant_service.get_tenant(db, tenant_id)
